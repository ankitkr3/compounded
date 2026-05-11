#!/usr/bin/env python3
"""
compounded trust ladder.

Implements the promotion/demotion rules:

  .proposed   -> never auto-promoted; only via verification (finalize_verification.py)
  .verified   -> .trusted    after PROMOTION_VERIFIED_TO_TRUSTED_USES clean uses
  .trusted    -> .autonomous after PROMOTION_TRUSTED_TO_AUTONOMOUS_USES total uses
                 AND PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN consecutive clean uses
  Any active  -> demote one step on a single correction event
  Any active  -> demote to .proposed after DEMOTION_CORRECTIONS_FOR_PROPOSED corrections
                 within DEMOTION_WINDOW_DAYS

Pinned skills are exempt from auto-demotion below their pinned tier.

Two main entry points:

  --process-session
      Called from the SessionEnd hook. Reads the session's logged events
      (via the trust DB or a session marker file), decides on transitions,
      applies them.

  --report-skill <name>
      Prints the current state and counters for a skill.

  --record-use <name> [--corrected]
      Manually record a use event (for the demo skill or testing).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    AUTONOMOUS,
    DEMOTION_CORRECTIONS_FOR_PROPOSED,
    DEMOTION_WINDOW_DAYS,
    EVENT_CORRECTED,
    EVENT_DEMOTED,
    EVENT_PROMOTED,
    EVENT_USED,
    PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN,
    PROMOTION_TRUSTED_TO_AUTONOMOUS_USES,
    PROMOTION_VERIFIED_TO_TRUSTED_USES,
    PROPOSED,
    TRUSTED,
    VERIFIED,
    db,
    ensure_layout,
    find_skill_dir,
    get_skill,
    is_pinned,
    is_valid_skill_name,
    log_event,
    move_skill,
    now_ts,
)

ACTIVE_TIERS = (VERIFIED, TRUSTED, AUTONOMOUS)
TIER_ORDER = (PROPOSED, VERIFIED, TRUSTED, AUTONOMOUS)


def tier_above(tier: str) -> str | None:
    if tier not in TIER_ORDER:
        return None
    idx = TIER_ORDER.index(tier)
    return TIER_ORDER[idx + 1] if idx + 1 < len(TIER_ORDER) else None


def tier_below(tier: str) -> str | None:
    if tier not in TIER_ORDER:
        return None
    idx = TIER_ORDER.index(tier)
    return TIER_ORDER[idx - 1] if idx > 0 else None


def record_use(name: str, corrected: bool = False) -> dict:
    """Record a single use event, with optional correction. Apply transitions.
    Returns a dict describing what happened."""
    if not is_valid_skill_name(name):
        raise ValueError(f"invalid skill name: {name!r}")

    found = find_skill_dir(name)
    if found is None:
        raise FileNotFoundError(f"skill {name!r} not found")
    state, _ = found
    if state not in ACTIVE_TIERS:
        # Cannot record uses against proposed/rejected skills.
        return {"action": "ignored", "reason": f"skill is at .{state}", "name": name}

    pinned = is_pinned(name)
    result: dict = {"name": name, "from_state": state, "pinned": pinned}

    with db() as conn:
        row = get_skill(conn, name)
        if row is None:
            # Skill exists on disk but not in DB; create a minimal row.
            conn.execute(
                "INSERT INTO skills (name, state, proposed_at, use_count) VALUES (?, ?, ?, 0)",
                (name, state, now_ts()),
            )
            row = get_skill(conn, name)
        use_count = row["use_count"] + 1
        correction_count = row["correction_count"]
        clean_uses = row["clean_uses_since_correction"]

        if corrected:
            correction_count += 1
            clean_uses = 0
            log_event(conn, name, EVENT_CORRECTED, None)
        else:
            clean_uses += 1

        log_event(conn, name, EVENT_USED, {"corrected": corrected})

        conn.execute(
            """
            UPDATE skills
               SET use_count = ?, correction_count = ?,
                   clean_uses_since_correction = ?, last_used_at = ?
             WHERE name = ?
            """,
            (use_count, correction_count, clean_uses, now_ts(), name),
        )

    # Now apply transitions outside the DB context to avoid moving directories
    # while holding a transaction. We re-open db() inside transition helpers.
    transition = decide_transition(
        state=state,
        use_count=use_count,
        clean_uses=clean_uses,
        corrected=corrected,
        correction_count=correction_count,
        pinned=pinned,
    )

    if transition is None:
        result["action"] = "no-transition"
        return result

    apply_transition(name, state, transition, reason=transition_reason(transition))
    result["action"] = "transitioned"
    result["to_state"] = transition
    return result


def decide_transition(
    state: str,
    use_count: int,
    clean_uses: int,
    corrected: bool,
    correction_count: int,
    pinned: bool,
) -> str | None:
    """Return the destination tier if a transition should fire, else None.

    Promotion rules:
      .verified  + clean_uses >= PROMOTION_VERIFIED_TO_TRUSTED_USES  -> .trusted
      .trusted   + use_count  >= PROMOTION_TRUSTED_TO_AUTONOMOUS_USES
                 + clean_uses >= PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN -> .autonomous

    Demotion rule:
      any + corrected -> demote one tier (unless pinned at current tier)
    """
    if corrected:
        # Demote one tier, but never below .proposed; pinned skills stay.
        if pinned:
            return None
        below = tier_below(state)
        return below

    # Not corrected: consider promotion.
    if state == VERIFIED and clean_uses >= PROMOTION_VERIFIED_TO_TRUSTED_USES:
        return TRUSTED
    if (
        state == TRUSTED
        and use_count >= PROMOTION_TRUSTED_TO_AUTONOMOUS_USES
        and clean_uses >= PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN
    ):
        return AUTONOMOUS
    return None


def transition_reason(to_state: str) -> str:
    if to_state == TRUSTED:
        return f"promoted: {PROMOTION_VERIFIED_TO_TRUSTED_USES}+ clean uses at .verified"
    if to_state == AUTONOMOUS:
        return (
            f"promoted: {PROMOTION_TRUSTED_TO_AUTONOMOUS_USES}+ uses, "
            f"{PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN}+ clean in a row"
        )
    if to_state == VERIFIED:
        return "demoted: correction event at .trusted"
    if to_state == TRUSTED:
        return "demoted: correction event at .autonomous"
    if to_state == PROPOSED:
        return "demoted: correction event at .verified"
    return "transition"


def apply_transition(name: str, from_state: str, to_state: str, reason: str) -> None:
    move_skill(name, from_state, to_state)
    direction = (
        EVENT_PROMOTED
        if TIER_ORDER.index(to_state) > TIER_ORDER.index(from_state)
        else EVENT_DEMOTED
    )
    with db() as conn:
        if direction == EVENT_PROMOTED:
            conn.execute(
                "UPDATE skills SET state = ?, last_promoted_at = ?, clean_uses_since_correction = 0 WHERE name = ?",
                (to_state, now_ts(), name),
            )
        else:
            conn.execute(
                "UPDATE skills SET state = ?, last_demoted_at = ? WHERE name = ?",
                (to_state, now_ts(), name),
            )
        log_event(conn, name, direction, {"from": from_state, "to": to_state, "reason": reason})


def cascade_demote_on_correction_window(name: str) -> None:
    """If a skill has DEMOTION_CORRECTIONS_FOR_PROPOSED corrections in the last
    DEMOTION_WINDOW_DAYS, drop it all the way to .proposed."""
    cutoff = now_ts() - DEMOTION_WINDOW_DAYS * 86400
    with db() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM events WHERE skill_name = ? AND event_type = ? AND timestamp >= ?",
            (name, EVENT_CORRECTED, cutoff),
        )
        count = cur.fetchone()["c"]
    if count < DEMOTION_CORRECTIONS_FOR_PROPOSED:
        return
    if is_pinned(name):
        return
    found = find_skill_dir(name)
    if found is None:
        return
    state, _ = found
    if state == PROPOSED:
        return
    apply_transition(
        name,
        from_state=state,
        to_state=PROPOSED,
        reason=f"demoted to .proposed: {count} corrections in {DEMOTION_WINDOW_DAYS} days",
    )


def report_skill(name: str) -> int:
    found = find_skill_dir(name)
    if found is None:
        print(f"error: skill {name!r} not found", file=sys.stderr)
        return 1
    state, path = found
    with db() as conn:
        row = get_skill(conn, name)
    print(f"name: {name}")
    print(f"state: .{state}")
    print(f"path: {path}")
    print(f"pinned: {is_pinned(name)}")
    if row:
        print(f"use_count: {row['use_count']}")
        print(f"correction_count: {row['correction_count']}")
        print(f"clean_uses_since_correction: {row['clean_uses_since_correction']}")
        if row["last_used_at"]:
            print(f"last_used_at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['last_used_at']))}")
        if row["last_promoted_at"]:
            print(f"last_promoted_at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['last_promoted_at']))}")
        if row["last_demoted_at"]:
            print(f"last_demoted_at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['last_demoted_at']))}")
    return 0


def process_session() -> int:
    """Currently a hook for SessionEnd processing. v1: cascade-check demotion windows
    for all active skills. Future: auto-prune stale .verified, etc."""
    ensure_layout()
    with db() as conn:
        cur = conn.execute(
            "SELECT name FROM skills WHERE state IN (?, ?, ?)",
            (VERIFIED, TRUSTED, AUTONOMOUS),
        )
        names = [row["name"] for row in cur.fetchall()]
    for name in names:
        try:
            cascade_demote_on_correction_window(name)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"compounded trust_ladder cascade {name}: {exc}\n")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("process-session-cmd", help="(internal)")  # placeholder

    parser.add_argument("--process-session", action="store_true")
    parser.add_argument("--report-skill")
    parser.add_argument("--record-use", help="record a use event for skill")
    parser.add_argument("--corrected", action="store_true", help="mark the use as corrected")

    args = parser.parse_args(argv)
    ensure_layout()

    if args.process_session:
        return process_session()
    if args.report_skill:
        return report_skill(args.report_skill)
    if args.record_use:
        result = record_use(args.record_use, corrected=args.corrected)
        print(f"recorded: {result}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        print(f"error: trust_ladder: {exc}", file=sys.stderr)
        sys.exit(1)
