#!/usr/bin/env python3
"""
compounded skill proposal mechanism.

Invoked by the agent (via Bash) when it has authored a new SKILL.md and
wants it staged for verification.

Reads the SKILL.md content from stdin and the skill name + verification
hint from CLI args. Validates frontmatter, runs a security scan, writes
to ~/.claude/compounded/skills/.proposed/<name>/SKILL.md, and records a
proposal row in the trust DB.

Exit 0 on success; non-zero with an error message to stderr on failure.

Usage:
    skill_propose.py --name <kebab-name> --verification-hint "<hint>" < SKILL.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    EVENT_PROPOSED,
    PROPOSED,
    PROPOSED_DIR,
    db,
    ensure_layout,
    find_skill_dir,
    is_valid_skill_name,
    log_event,
    parse_frontmatter,
    scan_for_threats,
    upsert_skill,
)

REQUIRED_FRONTMATTER_FIELDS = {"name", "description"}
MAX_SKILL_BYTES = 64 * 1024  # 64 KB sanity ceiling
MIN_HINT_CHARS = 20


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Propose a new compounded skill.")
    parser.add_argument("--name", required=True, help="kebab-case skill name")
    parser.add_argument(
        "--verification-hint",
        required=True,
        help="one-sentence description of when a future task qualifies for replay verification",
    )
    parser.add_argument("--force", action="store_true", help="overwrite an existing proposal of the same name")
    args = parser.parse_args(argv)

    name = args.name.strip()
    hint = args.verification_hint.strip()

    if not is_valid_skill_name(name):
        print(
            f"error: skill name {name!r} is not valid kebab-case "
            "(must start with a lowercase letter, only [a-z0-9-], max 64 chars)",
            file=sys.stderr,
        )
        return 2

    if len(hint) < MIN_HINT_CHARS:
        print(
            f"error: verification hint is too short ({len(hint)} chars, need >= {MIN_HINT_CHARS}). "
            "A useful hint describes the trigger condition concretely.",
            file=sys.stderr,
        )
        return 2

    raw = sys.stdin.read()
    if not raw.strip():
        print("error: no SKILL.md content received on stdin", file=sys.stderr)
        return 2

    if len(raw.encode("utf-8")) > MAX_SKILL_BYTES:
        print(f"error: SKILL.md exceeds {MAX_SKILL_BYTES} bytes", file=sys.stderr)
        return 2

    fields, body = parse_frontmatter(raw)
    if fields is None:
        print("error: SKILL.md has no YAML frontmatter (--- ... ---)", file=sys.stderr)
        return 2

    missing = REQUIRED_FRONTMATTER_FIELDS - set(fields)
    if missing:
        print(f"error: SKILL.md frontmatter missing required fields: {sorted(missing)}", file=sys.stderr)
        return 2

    if fields.get("name") != name:
        print(
            f"error: frontmatter name {fields.get('name')!r} does not match --name argument {name!r}",
            file=sys.stderr,
        )
        return 2

    if not body.strip():
        print("error: SKILL.md has no body after frontmatter", file=sys.stderr)
        return 2

    threat = scan_for_threats(raw)
    if threat:
        print(f"error: rejected by security scan: {threat}", file=sys.stderr)
        return 3

    ensure_layout()

    # Refuse to clobber an existing skill in any state, unless --force.
    found = find_skill_dir(name)
    if found is not None:
        existing_state, existing_path = found
        if not args.force:
            print(
                f"error: skill {name!r} already exists at state '.{existing_state}' "
                f"({existing_path}). Use --force to replace, or pick a different name.",
                file=sys.stderr,
            )
            return 4
        # If forcing, only allow replacing a proposed/rejected; never clobber an active skill.
        if existing_state in ("verified", "trusted", "autonomous"):
            print(
                f"error: refusing to clobber active skill {name!r} at state '.{existing_state}'. "
                "Demote or delete it first.",
                file=sys.stderr,
            )
            return 4

    target_dir = PROPOSED_DIR / name
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_path = target_dir / "SKILL.md"
    skill_path.write_text(raw, encoding="utf-8")

    hint_path = target_dir / ".verification_hint"
    hint_path.write_text(hint, encoding="utf-8")

    with db() as conn:
        upsert_skill(conn, name=name, state=PROPOSED, verification_hint=hint)
        log_event(conn, name, EVENT_PROPOSED, {"hint": hint})

    print(
        f"proposed: {name} → {skill_path.relative_to(target_dir.parent.parent.parent)}\n"
        f"verification will run on the next applicable task.",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        print(f"error: unexpected failure in skill_propose: {exc}", file=sys.stderr)
        sys.exit(1)
