#!/usr/bin/env python3
"""
SessionStart hook for compounded.

Reads ~/.claude/compounded/USER.md and injects it as additionalContext
for Claude Code at session start. Also surfaces a one-line trust
ladder summary so the user knows compounded is active.

Output format (Claude Code SessionStart hook spec):
    {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "<text>"
        }
    }

Budget: <100ms. Pure stdlib. No LLM calls. No DB writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    ACTIVE_STATES,
    PROPOSED,
    REJECTED,
    STATE_DIRS,
    USER_MD,
    USER_MD_CHAR_LIMIT,
    ensure_layout,
    read_hook_input,
    write_hook_output,
)


def count_skills_by_state() -> dict[str, int]:
    counts = {state: 0 for state in (*ACTIVE_STATES, PROPOSED, REJECTED)}
    for state, base in STATE_DIRS.items():
        if not base.exists():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "SKILL.md").exists():
                counts[state] = counts.get(state, 0) + 1
    return counts


def build_user_block() -> str:
    if not USER_MD.exists():
        return ""
    text = USER_MD.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    if len(text) > USER_MD_CHAR_LIMIT:
        text = text[:USER_MD_CHAR_LIMIT] + "\n[truncated to char limit]"
    return text


def build_summary_line(counts: dict[str, int], user_chars: int) -> str:
    return (
        f"compounded: USER.md {user_chars}/{USER_MD_CHAR_LIMIT} chars · "
        f"skills: {counts.get('verified', 0)} verified, "
        f"{counts.get('trusted', 0)} trusted, "
        f"{counts.get('autonomous', 0)} autonomous, "
        f"{counts.get('proposed', 0)} pending"
    )


def main() -> int:
    ensure_layout()
    _ = read_hook_input()  # we don't need fields from this, but read to keep stdin clean

    user_block = build_user_block()
    counts = count_skills_by_state()
    user_chars = len(user_block)

    summary = build_summary_line(counts, user_chars)

    if user_block:
        body = (
            "═══════════════════════════════════════════════\n"
            f"USER.md (compounded, user-global) [{user_chars}/{USER_MD_CHAR_LIMIT} chars]\n"
            "═══════════════════════════════════════════════\n"
            f"{user_block}\n"
            "═══════════════════════════════════════════════\n"
            f"{summary}\n"
        )
    else:
        body = f"{summary}\n(USER.md is empty. Add user-global preferences via /compounded:status or by editing ~/.claude/compounded/USER.md.)\n"

    write_hook_output({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": body,
        }
    })
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # Never fail loudly in a session-start hook. A broken hook should not break sessions.
        sys.stderr.write(f"compounded memory_inject: {exc}\n")
        sys.exit(0)
