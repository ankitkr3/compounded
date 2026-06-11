#!/usr/bin/env python3
"""
compounded auto-proposer.

Stop-hook companion. Scans the most recent assistant turn in the session
transcript and decides whether the just-completed procedure is worth
proposing as a compounded skill.

Conservative by design:
- The hook itself NEVER writes to .proposed/.
- Delivery (Stop hooks do not honor additionalContext):
    rule capture      -> decision:"block" + reason, so the instruction reaches
                         Claude (guarded by stop_hook_active to prevent loops)
    procedure capture -> systemMessage shown to the user (no forced turn)
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
  procedure capture: fire if score >= 3 AND correction == False
  rule capture:      fire if correction == True AND tool_uses >= 1

Two capture kinds:
  procedure — a successful multi-step task worth saving as a replayable
              procedure (the original compounded behavior).
  rule      — the user corrected Claude and Claude then did real work to
              fix it. The intent→mistake→correction delta is a behavioral
              lesson worth saving as a trigger-keyed rule skill
              (kind: rule). Corrections are the highest-signal learning
              events; they trigger capture rather than suppress it.

Debounce:
- Pending proposals do NOT mute capture: saves are user-approved, so the
  queue cannot grow on its own, and a pending rule may legitimately wait
  weeks for its verifying task.
- stop_hook_active guards against block loops within a turn-chain.

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
RULE_MIN_TOOL_USES = 1  # corrective turn must show real work, not just chat
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024  # don't OOM on huge sessions
TRANSCRIPT_TAIL_LINES = 400

EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
BASH_TOOLS = {"Bash"}
PLAN_TOOLS = {"Plan", "EnterPlanMode", "ExitPlanMode"}

# --- correction detection: two channels ------------------------------------
# Channel 1: the USER's message. Users phrase corrections in unbounded ways
# ("i think its gemini 2, can u confirm?"), so patterns here are a fast path,
# never the whole story.
CORRECTION_PATTERNS = (
    # hard corrections
    "no, ",
    "no.",
    "no,",
    "no —",
    "no -",
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
    # soft corrections / doubt
    "i think it",
    "i thought it",
    "are you sure",
    "are u sure",
    "can you confirm",
    "can u confirm",
    "can you check",
    "can u check",
    "double check",
    "double-check",
    "isn't it",
    "isnt it",
    "isn't there",
    "isnt there",
    "is there a newer",
    "that's old",
    "thats old",
    "outdated",
    "out of date",
    "not the latest",
    "check again",
    "look it up",
    "verify that",
    "recheck",
)

# Channel 2: the ASSISTANT's reaction. This is the channel that generalizes:
# however the user phrases a correction, the model's acknowledgment is highly
# standardized ("you're right", "my mistake", "good catch"). The LLM in the
# loop does the semantic understanding; the hook just reads its reaction.
ACK_PATTERNS = (
    "you're right",
    "you are right",
    "youre right",
    "you're correct",
    "you are correct",
    "you're absolutely right",
    "your instinct was correct",
    "good catch",
    "my mistake",
    "my bad",
    "i was wrong",
    "i was incorrect",
    "i stand corrected",
    "stand corrected",
    "i misspoke",
    "you were right",
    "fair point",
    "i apologize",
    "apologies —",
    "apologies,",
    "has superseded",
    "supersedes the",
    "i mentioned earlier",
    "i said earlier",
    "correcting my",
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


def _content(ev: dict) -> object:
    """Return an event's content blocks, normalizing the transcript schema.

    Claude Code's session transcript wraps each message under a top-level
    "message" key (``{"type": "assistant", "message": {"content": [...]}}``),
    whereas the raw Anthropic Messages shape carries ``content`` at the top
    level. We read from ``message.content`` when present and fall back to the
    top-level key so both shapes work.
    """
    msg = ev.get("message")
    if isinstance(msg, dict) and "content" in msg:
        return msg.get("content")
    return ev.get("content")


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
    content = _content(ev)
    if not isinstance(content, list):
        return False
    return all(
        isinstance(item, dict) and item.get("type") == "tool_result"
        for item in content
    )


def _extract_text(ev: dict) -> str:
    """Pull free text out of an event regardless of content shape."""
    content = _content(ev)
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
        content = _content(ev)
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                yield item


def _iter_tool_results(turn_events: list[dict]) -> Iterable[dict]:
    """Yield every tool_result content-block in the turn."""
    for ev in turn_events:
        content = _content(ev)
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
        content = _content(ev)
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
    """Channel 1: correction phrasing in the user's message (fast path)."""
    if prior_user is None:
        return False
    text = _extract_text(prior_user).lower()
    if not text:
        return False
    return any(p in text for p in CORRECTION_PATTERNS)


def _assistant_acknowledged_correction(turn_events: list[dict]) -> bool:
    """Channel 2: the assistant's own text admits it was corrected.

    Generalizes to ANY user phrasing — the model already understood the
    correction semantically, and its acknowledgment language is standardized.
    """
    for ev in turn_events:
        if (ev.get("type") or ev.get("role")) != "assistant":
            continue
        text = _extract_text(ev).lower()
        if text and any(p in text for p in ACK_PATTERNS):
            return True
    return False


# -----------------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------------

def score_turn(turn_events: list[dict], prior_user: dict | None) -> dict:
    tool_uses = list(_iter_tool_uses(turn_events))
    edit_files = {p for p in (_edit_target(tu) for tu in tool_uses) if p}
    bash_count = sum(1 for tu in tool_uses if tu.get("name") in BASH_TOOLS)
    plan_used = any(tu.get("name") in PLAN_TOOLS for tu in tool_uses)
    recovery = _has_recovery(turn_events)
    correction_user = _has_correction_signal(prior_user)
    correction_ack = _assistant_acknowledged_correction(turn_events)
    correction = correction_user or correction_ack

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

    # A correction followed by real corrective work is the highest-signal
    # learning event: capture the lesson as a rule. Otherwise a high-signal
    # clean turn captures as a procedure (the original behavior).
    if correction and len(tool_uses) >= RULE_MIN_TOOL_USES:
        capture_kind = "rule"
    elif score >= SCORE_TO_FIRE and not correction:
        capture_kind = "procedure"
    else:
        capture_kind = None

    return {
        "score": score,
        "fire": capture_kind is not None,
        "capture_kind": capture_kind,
        "tool_uses": len(tool_uses),
        "edit_files": sorted(edit_files),
        "bash_count": bash_count,
        "plan_used": plan_used,
        "recovery": recovery,
        "correction": correction,
        "correction_user": correction_user,
        "correction_ack": correction_ack,
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


def build_procedure_message(signals: dict) -> str:
    """User-facing hint (systemMessage). Stop hooks cannot inject context into
    Claude without blocking the stop, and procedure nudges fire too often to
    justify forcing an extra turn — so we surface them to the user instead."""
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
        f"[compounded] Auto-propose threshold reached ({summary}; score={signals['score']}). "
        f"If this procedure is worth keeping, say \"save this as a skill\" "
        f"(suggested name: {name_hint})."
    )


def build_rule_reason(signals: dict) -> str:
    """Instruction fed to Claude via the Stop-hook block channel (`reason`).

    `additionalContext` is not honored for Stop hooks; `decision: "block"`
    with a `reason` is the documented way to get an instruction in front of
    Claude after a turn ends. Corrections are rare and high-value, so the
    forced continuation is justified here (and stop_hook_active guards loops).
    """
    return (
        f"[compounded] Correction detected — the user corrected your previous "
        f"approach and you then did {signals['tool_uses']} tool call(s) of corrective work. "
        f"This may encode a reusable behavioral rule (the delta between what the user "
        f"asked, what you did, and how they corrected you). "
        f"Invoke the `compounded-author` skill in RULE MODE: extract the generalizable "
        f"lesson, ask the user to approve it via AskUserQuestion BEFORE saving, and if "
        f"approved propose it as a `kind: rule` skill. "
        f"If the correction was a one-off (specific value, path, or taste call with no "
        f"general trigger), do nothing further and end your turn."
    )


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main() -> int:
    ensure_layout()
    hook_input = read_hook_input()
    transcript_path = hook_input.get("transcript_path", "")
    # True when this Stop fires after a previous Stop hook already blocked
    # and Claude continued. Never nudge again in that state — loop guard.
    stop_hook_active = bool(hook_input.get("stop_hook_active"))

    # NOTE: pending proposals deliberately do NOT debounce capture. Every
    # save is gated by explicit user approval, so the queue cannot pile up
    # on its own — and a pending rule may wait weeks for its verifying task,
    # during which learning must not be muted.

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

    if not signals["fire"] or stop_hook_active:
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    if signals["capture_kind"] == "rule":
        # Block the stop so the instruction actually reaches Claude.
        sys.stdout.write(json.dumps({
            "decision": "block",
            "reason": build_rule_reason(signals),
        }))
        return 0

    # Procedure capture: surface a hint to the user; never force a turn.
    sys.stdout.write(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "systemMessage": build_procedure_message(signals),
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"compounded auto_propose: {exc}\n")
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        sys.exit(0)
