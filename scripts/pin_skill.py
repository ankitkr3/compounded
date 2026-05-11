#!/usr/bin/env python3
"""
Manual trust manipulation for compounded.

Subcommands:
  pin    <skill>             lock a skill at its current trust state
  unpin  <skill>             clear the pin
  trust  <skill> --to <state> manually promote (skip the gradient)
  demote <skill>             manually drop one tier
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    AUTONOMOUS,
    EVENT_DEMOTED,
    EVENT_PINNED,
    EVENT_PROMOTED,
    EVENT_UNPINNED,
    PROPOSED,
    TRUSTED,
    VERIFIED,
    db,
    ensure_layout,
    find_skill_dir,
    is_valid_skill_name,
    log_event,
    move_skill,
    set_pinned,
)

VALID_TARGETS = (VERIFIED, TRUSTED, AUTONOMOUS)
TIER_ORDER = (PROPOSED, VERIFIED, TRUSTED, AUTONOMOUS)


def cmd_pin(args: argparse.Namespace) -> int:
    if not is_valid_skill_name(args.skill):
        print(f"error: invalid skill name {args.skill!r}", file=sys.stderr)
        return 2
    if find_skill_dir(args.skill) is None:
        print(f"error: skill {args.skill!r} not found", file=sys.stderr)
        return 2
    set_pinned(args.skill, True)
    with db() as conn:
        log_event(conn, args.skill, EVENT_PINNED, None)
    print(f"pinned: {args.skill}")
    return 0


def cmd_unpin(args: argparse.Namespace) -> int:
    if not is_valid_skill_name(args.skill):
        print(f"error: invalid skill name {args.skill!r}", file=sys.stderr)
        return 2
    set_pinned(args.skill, False)
    with db() as conn:
        log_event(conn, args.skill, EVENT_UNPINNED, None)
    print(f"unpinned: {args.skill}")
    return 0


def cmd_trust(args: argparse.Namespace) -> int:
    if not is_valid_skill_name(args.skill):
        print(f"error: invalid skill name {args.skill!r}", file=sys.stderr)
        return 2
    target = args.to
    if target not in VALID_TARGETS:
        print(f"error: --to must be one of {VALID_TARGETS}", file=sys.stderr)
        return 2
    found = find_skill_dir(args.skill)
    if found is None:
        print(f"error: skill {args.skill!r} not found", file=sys.stderr)
        return 2
    state, _ = found
    if state == target:
        print(f"no-op: {args.skill} is already at .{target}")
        return 0
    move_skill(args.skill, state, target)
    direction = (
        EVENT_PROMOTED
        if TIER_ORDER.index(target) > TIER_ORDER.index(state)
        else EVENT_DEMOTED
    )
    with db() as conn:
        conn.execute("UPDATE skills SET state = ? WHERE name = ?", (target, args.skill))
        log_event(conn, args.skill, direction, {"from": state, "to": target, "manual": True})
    print(f"{args.skill}: .{state} → .{target}")
    return 0


def cmd_demote(args: argparse.Namespace) -> int:
    if not is_valid_skill_name(args.skill):
        print(f"error: invalid skill name {args.skill!r}", file=sys.stderr)
        return 2
    found = find_skill_dir(args.skill)
    if found is None:
        print(f"error: skill {args.skill!r} not found", file=sys.stderr)
        return 2
    state, _ = found
    idx = TIER_ORDER.index(state)
    if idx == 0:
        print(f"no-op: {args.skill} is already at .{state}")
        return 0
    target = TIER_ORDER[idx - 1]
    move_skill(args.skill, state, target)
    with db() as conn:
        conn.execute("UPDATE skills SET state = ? WHERE name = ?", (target, args.skill))
        log_event(conn, args.skill, EVENT_DEMOTED, {"from": state, "to": target, "manual": True})
    print(f"{args.skill}: .{state} → .{target}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pin = sub.add_parser("pin")
    p_pin.add_argument("skill")
    p_pin.set_defaults(func=cmd_pin)

    p_unpin = sub.add_parser("unpin")
    p_unpin.add_argument("skill")
    p_unpin.set_defaults(func=cmd_unpin)

    p_trust = sub.add_parser("trust")
    p_trust.add_argument("skill")
    p_trust.add_argument("--to", required=True, choices=VALID_TARGETS)
    p_trust.set_defaults(func=cmd_trust)

    p_demote = sub.add_parser("demote")
    p_demote.add_argument("skill")
    p_demote.set_defaults(func=cmd_demote)

    args = parser.parse_args(argv)
    ensure_layout()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        print(f"error: pin_skill: {exc}", file=sys.stderr)
        sys.exit(1)
