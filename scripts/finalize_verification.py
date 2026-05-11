#!/usr/bin/env python3
"""
Apply a verifier subagent's verdict to a proposed skill.

Called by Claude (via Bash) after the skill-verifier subagent returns its
JSON verdict. Moves the skill between trust state directories accordingly:

    PASS / PASS-with-notes / PASS-low-confidence  → .verified/
    FAIL                                          → .rejected/

Records an event in the trust DB and updates the skills row.

Usage:
    finalize_verification.py --name <name> --verdict-json '<JSON>'

The JSON shape must match what skill-verifier returns:
    {"verdict": "...", "reason_code": "...", "reason_text": "...",
     "step_or_field": null, "confidence": 0.85}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    EVENT_REJECTED,
    EVENT_VERIFIED,
    PROPOSED,
    PROPOSED_DIR,
    REJECTED,
    REJECTED_DIR,
    VERIFIED,
    VERIFIED_DIR,
    db,
    ensure_layout,
    find_skill_dir,
    is_valid_skill_name,
    log_event,
    move_skill,
    now_ts,
)

PASS_VERDICTS = {"PASS", "PASS-with-notes", "PASS-low-confidence"}
FAIL_VERDICTS = {"FAIL"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--verdict-json", required=True)
    args = parser.parse_args(argv)

    name = args.name.strip()
    if not is_valid_skill_name(name):
        print(f"error: invalid skill name {name!r}", file=sys.stderr)
        return 2

    try:
        verdict = json.loads(args.verdict_json)
    except json.JSONDecodeError as exc:
        print(f"error: --verdict-json is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(verdict, dict) or "verdict" not in verdict:
        print("error: verdict JSON missing required field 'verdict'", file=sys.stderr)
        return 2

    v = verdict["verdict"]
    reason_code = verdict.get("reason_code", "ok")
    reason_text = verdict.get("reason_text", "")
    confidence = verdict.get("confidence", 0.0)

    ensure_layout()

    found = find_skill_dir(name)
    if found is None:
        print(f"error: skill {name!r} not found in any state", file=sys.stderr)
        return 2
    state, _path = found
    if state != PROPOSED:
        print(
            f"error: skill {name!r} is at state '.{state}', not '.proposed'. "
            "finalize_verification only operates on proposals.",
            file=sys.stderr,
        )
        return 2

    if v in PASS_VERDICTS:
        new_path = move_skill(name, PROPOSED, VERIFIED)
        # Carry the verification hint and verdict alongside the SKILL.md.
        verdict_path = new_path / ".verification_verdict"
        verdict_path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        with db() as conn:
            conn.execute(
                "UPDATE skills SET state = ?, verified_at = ?, last_promoted_at = ? WHERE name = ?",
                (VERIFIED, now_ts(), now_ts(), name),
            )
            log_event(conn, name, EVENT_VERIFIED, {
                "verdict": v,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "confidence": confidence,
            })
        print(f"verified: {name} (verdict={v}, confidence={confidence})")
        return 0

    if v in FAIL_VERDICTS:
        new_path = move_skill(name, PROPOSED, REJECTED)
        rejection_path = new_path / ".rejection_reason"
        rejection_path.write_text(
            f"verifier-fail: {reason_code}: {reason_text}\n"
            f"step_or_field: {verdict.get('step_or_field')}\n"
            f"confidence: {confidence}\n",
            encoding="utf-8",
        )
        with db() as conn:
            conn.execute(
                "UPDATE skills SET state = ? WHERE name = ?",
                (REJECTED, name),
            )
            log_event(conn, name, EVENT_REJECTED, {
                "verdict": v,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "confidence": confidence,
            })
        print(f"rejected: {name} ({reason_code}: {reason_text})")
        return 0

    print(
        f"error: unknown verdict {v!r}; expected one of {sorted(PASS_VERDICTS | FAIL_VERDICTS)}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        print(f"error: unexpected failure in finalize_verification: {exc}", file=sys.stderr)
        sys.exit(1)
