#!/usr/bin/env python3
"""
compounded auto-proposer.

Stop-hook companion. Scans the most recent assistant turn in the session
transcript and decides whether the just-completed procedure is worth
proposing as a compounded skill.

Conservative by design:
- The hook itself NEVER writes to .proposed/.
- It only emits additionalContext when heuristic signals cross a threshold.
- Claude decides whether to actually invoke `compounded-author` and propose.

Signals we count (in the last assistant turn):
  tool_uses        — total tool invocations
  edit_files       — distinct files touched via Edit/Write/NotebookEdit
  bash_count       — Bash tool invocations
  plan_used        — Plan/ExitPlanMode/EnterPlanMode tool usage
  recovery         — at least one tool error followed by a successful retry
  correction       — user message before the assistant turn contains a correction signal

Scoring (additive, threshold-based):
  +2  tool_uses >= 5
  +2  edit_files >= 2
  +1  bash_count >= 2
  +2  recovery == True
  +1  plan_used == True
  ----------
  fire if score >= 3 AND correction == False

Debounce:
- If any .proposed/ skill already exists, do not auto-propose (avoid pile-up).
- Hook never re-fires within the same turn (Claude Code's hook semantics).

Failure mode:
- ANY exception → silent exit with {"continue": true, "suppressOutput": true}.
- Stop-hook failures must never break a session.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    PROPOSED_DIR,
    ensure_layout,
    jsonl_log,
    now_ts,
    read_hook_input,
)

# -----------------------------------------------------------------------------
# Tunables — chosen to be conservative on a first release.
# -----------------------------------------------------------------------------

THRESHOLD_TOOL_USES = 5
THRESHOLD_EDIT_FILES = 2
THRESHOLD_BASH = 2
SCORE_TO_FIRE = 3
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024  # don't OOM on huge sessions
TRANSCRIPT_TAIL_LINES = 400

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
BASH_TOOLS = {"Bash"}
PLAN_TOOLS = {"Plan", "EnterPlanMode", "ExitPlanMode"}

CORRECTION_PATTERNS = (
    "no, ",
    "no.",
    "no,",
    "undo",
    "revert",
    "that's wrong",
    "thats wrong",
    "incorrect",
    "you broke",
    "didn't work",
    "doesn't work",
    "not what i ",
    "not what i'",
    "stop, ",
    "wait, ",
    "wait,",
)


# -----------------------------------------------------------------------------
# Transcript parsing
# -----------------------------------------------------------------------------

def _iter_transcript(transcript_path: str) -> Iterable[dict]:
    """Yield parsed JSON objects from the last TRANSCRIPT_TAIL_LINES of the file.

    Stop-hook transcripts can be large; we only need the tail (current turn).
    """
    if not transcript_path:
        return
    p = Path(transcript_path)
    if not p.exists():
        return
    try:
        size = p.stat().st_size
        if size > MAX_TRANSCRIPT_BYTES:
            with p.open("rb") as fh:
                fh.seek(max(0, size - MAX_TRANSCRIPT_BYTES))
                fh.readline()  # discard partial first line
                raw = fh.read().decode("utf-8", errors="replace")
        else:
            raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return

    lines = raw.splitlines()[-TRANSCRIPT_TAIL_LINES:]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _split_into_turns(events: list[dict]) -> tuple[list[dict], dict | None]:
    """Return (last_assistant_turn_events, prior_user_message).

    A "turn" is the run of events from the last user message to the end of the
    transcript. The prior user message is returned separately so we can scan
    it for correction signals.
    """
    last_user_idx = -1
    for i, ev in enumerate(events):
        role = ev.get("type") or ev.get("role")
        if role == "user":
            # Skip tool-result messages (those come from Claude Code, not the user).
            if _is_tool_result_only(ev):
                continue
            last_user_idx = i

    if last_user_idx == -1:
        return events, None

    prior_user = events[last_user_idx]
    turn = events[last_user_idx + 1:]
    return turn, prior_user


def _is_tool_result_only(ev: dict) -> bool:
    """True if a 'user' message is just a tool_result wrapper from Claude Code."""
    content = ev.get("content")
    if not isinstance(content, list):
        return False
    return all(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in content
    )


def _extract_text(ev: dict) -> str:
    """Pull free text out of an event regardless of content shape."""
    content = ev.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


# -----------------------------------------------------------------------------
# Signal extraction
# -----------------------------------------------------------------------------

def _iter_tool_uses(turn_events: list[dict]) -> Iterable[dict]:
    """Yield every tool_use content-block in the assistant turn."""
    for ev in turn_events:
        if (ev.get("type") or ev.get("role")) != "assistant":
            continue
        content = ev.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                yield item


def _iter_tool_results(turn_events: list[dict]) -> Iterable[dict]:
    """Yield every tool_result content-block in the turn."""
    for ev in turn_events:
        content = ev.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                yield item


def _edit_target(tool_use: dict) -> str | None:
    """Return the file path edited/written by this tool_use, if any."""
    name = tool_use.get("name", "")
    if name not in EDIT_TOOLS:
        return None
    inp = tool_use.get("input") or {}
    if not isinstance(inp, dict):
        return None
    return inp.get("file_path") or inp.get("path") or inp.get("notebook_path")


def _has_recovery(turn_events: list[dict]) -> bool:
    """True if at least one tool_result was an error followed later by a non-error of the same tool."""
    errored_tools: list[str] = []
    for ev in turn_events:
        content = ev.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "tool_result":
                if item.get("is_error"):
                    # Track that some tool failed in this turn.
                    errored_tools.append("any")
            elif t == "tool_use":
                if errored_tools:
                    # Any successful tool call after an error counts as a recovery attempt.
                    return True
    return False


def _has_correction_signal(prior_user: dict | None) -> bool:
    if prior_user is None:
        return False
    text = _extract_text(prior_user).lower()
    if not text:
        return False
    return any(p in text for p in CORRECTION_PATTERNS)


# -----------------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------------

def score_turn(turn_events: list[dict], prior_user: dict | None) -> dict:
    tool_uses = list(_iter_tool_uses(turn_events))
    edit_files = {p for p in (_edit_target(tu) for tu in tool_uses) if p}
    bash_count = sum(1 for tu in tool_uses if tu.get("name") in BASH_TOOLS)
    plan_used = any(tu.get("name") in PLAN_TOOLS for tu in tool_uses)
    recovery = _has_recovery(turn_events)
    correction = _has_correction_signal(prior_user)

    score = 0
    if len(tool_uses) >= THRESHOLD_TOOL_USES:
        score += 2
    if len(edit_files) >= THRESHOLD_EDIT_FILES:
        score += 2
    if bash_count >= THRESHOLD_BASH:
        score += 1
    if recovery:
        score += 2
    if plan_used:
        score += 1

    fire = score >= SCORE_TO_FIRE and not correction

    return {
        "score": score,
        "fire": fire,
        "tool_uses": len(tool_uses),
        "edit_files": sorted(edit_files),
        "bash_count": bash_count,
        "plan_used": plan_used,
        "recovery": recovery,
        "correction": correction,
    }


# -----------------------------------------------------------------------------
# Suggestion message
# -----------------------------------------------------------------------------

def _suggested_name(signals: dict) -> str:
    """Pick a placeholder skill name for the suggestion. Claude renames it."""
    files = signals.get("edit_files") or []
    if files:
        stem = Path(files[0]).stem.lower().replace("_", "-")
        # Conservative truncation.
        if stem and len(stem) <= 32:
            return f"{stem}-procedure"
    return "your-skill-name"


def build_suggestion(signals: dict) -> str:
    name_hint = _suggested_name(signals)
    bullets = []
    if signals["tool_uses"] >= THRESHOLD_TOOL_USES:
        bullets.append(f"{signals['tool_uses']} tool calls")
    if len(signals["edit_files"]) >= THRESHOLD_EDIT_FILES:
        bullets.append(f"{len(signals['edit_files'])} files edited")
    if signals["bash_count"] >= THRESHOLD_BASH:
        bullets.append(f"{signals['bash_count']} shell commands")
    if signals["recovery"]:
        bullets.append("recovered from a tool error")
    if signals["plan_used"]:
        bullets.append("planned execution")

    summary = ", ".join(bullets) if bullets else "non-trivial procedure"
    return (
        f"\n[compounded] Auto-propose threshold reached "
        f"({summary}; score={signals['score']}). "
        f"If the procedure you just completed is generalizable to similar future tasks, "
        f"invoke the `compounded-author` skill to save it as `{name_hint}` (rename as appropriate). "
        f"If it's a one-off, ignore this nudge.\n"
    )


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def _has_pending_proposal() -> bool:
    if not PROPOSED_DIR.exists():
        return False
    return any(
        p.is_dir() and (p / "SKILL.md").exists()
        for p in PROPOSED_DIR.iterdir()
    )


def main() -> int:
    ensure_layout()
    hook_input = read_hook_input()
    transcript_path = hook_input.get("transcript_path", "")

    # If a proposal is already pending, don't pile up. The other Stop hook
    # (skill_verify.py) is responsible for moving those forward.
    if _has_pending_proposal():
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    events = list(_iter_transcript(transcript_path))
    if not events:
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    turn_events, prior_user = _split_into_turns(events)
    if not turn_events:
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    signals = score_turn(turn_events, prior_user)

    # Log for observability — useful for tuning thresholds later.
    jsonl_log("auto_propose.jsonl", {
        "ts": now_ts(),
        "session_id": hook_input.get("session_id"),
        **signals,
    })

    if not signals["fire"]:
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    sys.stdout.write(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "additionalContext": build_suggestion(signals),
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"compounded auto_propose: {exc}\n")
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        sys.exit(0)
