#!/usr/bin/env python3
"""
compounded status reporter.

Prints a human-readable view of compounded state to stdout.

Two main outputs:

  --overview (default)
      USER.md size, skill counts by tier, recent transitions,
      recent rejections.

  --trust-ladder
      ASCII visualization of the trust ladder. Skills approaching
      promotion or demotion get highlighted.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    ACTIVE_STATES,
    AUTONOMOUS,
    DEMOTION_CORRECTIONS_FOR_PROPOSED,
    DEMOTION_WINDOW_DAYS,
    EVENT_DEMOTED,
    EVENT_PROMOTED,
    EVENT_REJECTED,
    PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN,
    PROMOTION_TRUSTED_TO_AUTONOMOUS_USES,
    PROMOTION_VERIFIED_TO_TRUSTED_USES,
    PROPOSED,
    REJECTED,
    REJECTED_DIR,
    SKILLS_DIR,
    STATE_DIRS,
    TRUSTED,
    USER_MD,
    USER_MD_CHAR_LIMIT,
    VERIFIED,
    db,
    ensure_layout,
    is_pinned,
)


def fmt_ago(ts: int | None) -> str:
    if not ts:
        return "never"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def list_skills_in_state(state: str) -> list[str]:
    base = STATE_DIRS[state]
    if not base.exists():
        return []
    return sorted(
        child.name
        for child in base.iterdir()
        if child.is_dir() and (child / "SKILL.md").exists()
    )


def overview() -> int:
    user_chars = len(USER_MD.read_text(encoding="utf-8")) if USER_MD.exists() else 0
    counts = {state: len(list_skills_in_state(state)) for state in (*ACTIVE_STATES, PROPOSED, REJECTED)}

    print("=== compounded status ===\n")
    print(f"USER.md: {user_chars}/{USER_MD_CHAR_LIMIT} chars  ({USER_MD})")
    print()
    print("skills by tier:")
    print(f"  .autonomous : {counts[AUTONOMOUS]:>3}")
    print(f"  .trusted    : {counts[TRUSTED]:>3}")
    print(f"  .verified   : {counts[VERIFIED]:>3}")
    print(f"  .proposed   : {counts[PROPOSED]:>3}  (awaiting verification)")
    print(f"  .rejected   : {counts[REJECTED]:>3}")
    print()

    with db() as conn:
        # Recent transitions
        cur = conn.execute(
            "SELECT skill_name, event_type, timestamp, detail FROM events "
            "WHERE event_type IN (?, ?, ?) ORDER BY timestamp DESC LIMIT 5",
            (EVENT_PROMOTED, EVENT_DEMOTED, EVENT_REJECTED),
        )
        recent = list(cur.fetchall())

    if recent:
        print("recent transitions:")
        for row in recent:
            print(f"  {fmt_ago(row['timestamp']):>10}  {row['event_type']:>10}  {row['skill_name']}")
        print()

    # Recent rejections with reasons
    rejected_dir_skills = list_skills_in_state(REJECTED)
    if rejected_dir_skills:
        print("recent rejections:")
        for name in rejected_dir_skills[:5]:
            reason_path = REJECTED_DIR / name / ".rejection_reason"
            reason = reason_path.read_text(encoding="utf-8").strip().splitlines()[0] if reason_path.exists() else "(no reason logged)"
            print(f"  {name}: {reason}")
        print()

    print("commands:")
    print("  /compounded:trust-status   show the trust ladder visualization")
    print("  /compounded:export <path>  produce a portable archive")
    print("  /compounded:import <path>  merge an archive on this machine")
    return 0


def trust_ladder() -> int:
    print("=== compounded trust ladder ===\n")

    # Header diagram
    print("  .proposed  →  .verified  →  .trusted  →  .autonomous")
    print(f"               (1 verify)    ({PROMOTION_VERIFIED_TO_TRUSTED_USES} clean   ({PROMOTION_TRUSTED_TO_AUTONOMOUS_USES} uses,")
    print(f"                              uses)         {PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN}+ clean)")
    print()

    with db() as conn:
        cur = conn.execute(
            "SELECT name, state, use_count, correction_count, clean_uses_since_correction, "
            "       last_used_at, last_promoted_at "
            "FROM skills WHERE state IN (?, ?, ?, ?) ORDER BY state DESC, use_count DESC",
            (AUTONOMOUS, TRUSTED, VERIFIED, PROPOSED),
        )
        rows = list(cur.fetchall())

    if not rows:
        print("(no skills yet — propose your first one via the compounded-author skill)")
        return 0

    # Group and print.
    by_state: dict[str, list] = {AUTONOMOUS: [], TRUSTED: [], VERIFIED: [], PROPOSED: []}
    for row in rows:
        by_state.setdefault(row["state"], []).append(row)

    promotion_candidates: list[str] = []
    demotion_candidates: list[str] = []

    for state in (AUTONOMOUS, TRUSTED, VERIFIED, PROPOSED):
        items = by_state.get(state, [])
        if not items:
            continue
        print(f".{state}/")
        for row in items:
            pin = " 📌" if is_pinned(row["name"]) else ""
            uses = row["use_count"]
            clean = row["clean_uses_since_correction"]
            corr = row["correction_count"]
            last_used = fmt_ago(row["last_used_at"])

            line = f"  {row['name']:30}{pin}  uses={uses:<3} clean={clean:<3} corrections={corr:<3} last={last_used}"
            print(line)

            # Promotion candidates
            if state == VERIFIED and clean >= PROMOTION_VERIFIED_TO_TRUSTED_USES - 1:
                promotion_candidates.append(f"{row['name']}: .verified → .trusted ({clean}/{PROMOTION_VERIFIED_TO_TRUSTED_USES} clean)")
            if state == TRUSTED and uses >= PROMOTION_TRUSTED_TO_AUTONOMOUS_USES - 2 and clean >= PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN - 1:
                promotion_candidates.append(
                    f"{row['name']}: .trusted → .autonomous "
                    f"({uses}/{PROMOTION_TRUSTED_TO_AUTONOMOUS_USES} uses, {clean}/{PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN} clean)"
                )
            # Demotion warning: high recent corrections
            if corr >= DEMOTION_CORRECTIONS_FOR_PROPOSED - 1 and state in (VERIFIED, TRUSTED, AUTONOMOUS):
                demotion_candidates.append(f"{row['name']}: {corr} corrections (drops to .proposed at {DEMOTION_CORRECTIONS_FOR_PROPOSED})")
        print()

    if promotion_candidates:
        print("approaching promotion:")
        for c in promotion_candidates:
            print(f"  ↑ {c}")
        print()

    if demotion_candidates:
        print("approaching demotion:")
        for c in demotion_candidates:
            print(f"  ↓ {c}")
        print()

    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trust-ladder", action="store_true", help="show ladder visualization")
    args = parser.parse_args(argv)

    ensure_layout()
    if args.trust_ladder:
        return trust_ladder()
    return overview()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        print(f"error: status: {exc}", file=sys.stderr)
        sys.exit(1)
