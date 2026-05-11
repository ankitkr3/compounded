#!/usr/bin/env python3
"""
compounded Stop hook.

Fires when Claude finishes a turn. Checks ~/.claude/compounded/skills/.proposed/
for any skills whose verification_hint matches the just-completed task.

Matching is intentionally conservative: we use a keyword-overlap heuristic
between the hint and the task summary. If a match is found, we record an
intent-to-verify in the trust DB and emit a hookSpecificOutput that asks
Claude to dispatch the skill-verifier subagent on the next turn.

We do NOT call an LLM directly from this hook. The verifier subagent runs
inside Claude Code's normal agent dispatch, using the user's own auth.

Budget: <500ms typical, <90s ceiling. Most sessions exit early (no pending
proposals or no match).

Auto-rejection: any proposal older than PROPOSAL_TTL_DAYS is moved to
.rejected/ with a `stale` reason at the start of every run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).parent))

from _lib import (
    EVENT_REJECTED,
    PROPOSAL_TTL_DAYS,
    PROPOSED,
    PROPOSED_DIR,
    REJECTED_DIR,
    db,
    ensure_layout,
    jsonl_log,
    log_event,
    now_ts,
    read_hook_input,
    upsert_skill,
)

STOPWORDS = {
    "the", "a", "an", "to", "of", "and", "or", "but", "in", "on", "at", "for",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "their", "they", "them",
    "i", "you", "we", "he", "she", "him", "her", "us", "next", "time",
    "user", "asks", "ask", "should", "will", "would", "could", "task",
    "should", "produce", "reproduce", "successfully", "again", "any",
    "into", "onto", "out", "over", "all", "some", "more", "less",
    "do", "does", "did", "doing", "have", "has", "had", "make",
}

WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")

# Minimum keyword overlap to count as a match.
MIN_OVERLAP_WORDS = 2
MIN_OVERLAP_RATIO = 0.20  # 20% of the hint's significant words


def keywords(text: str) -> set[str]:
    return {
        m.group(0).lower()
        for m in WORD_RE.finditer(text or "")
        if m.group(0).lower() not in STOPWORDS
    }


def overlap_score(hint_kw: set[str], task_kw: set[str]) -> tuple[int, float]:
    """Return (overlap_count, overlap_ratio_against_hint)."""
    if not hint_kw:
        return 0, 0.0
    common = hint_kw & task_kw
    return len(common), len(common) / max(1, len(hint_kw))


def matches_task(hint: str, task_text: str) -> tuple[bool, dict]:
    hint_kw = keywords(hint)
    task_kw = keywords(task_text)
    overlap, ratio = overlap_score(hint_kw, task_kw)
    matched = overlap >= MIN_OVERLAP_WORDS and ratio >= MIN_OVERLAP_RATIO
    return matched, {
        "overlap_words": overlap,
        "overlap_ratio": round(ratio, 3),
        "hint_keywords": sorted(hint_kw),
        "matched_keywords": sorted(hint_kw & task_kw),
    }


def auto_reject_stale() -> list[str]:
    """Move stale proposals to .rejected/. Returns list of names rejected."""
    if not PROPOSED_DIR.exists():
        return []
    cutoff = now_ts() - PROPOSAL_TTL_DAYS * 86400
    rejected: list[str] = []
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    for child in PROPOSED_DIR.iterdir():
        if not child.is_dir() or not (child / "SKILL.md").exists():
            continue
        # Use mtime of the SKILL.md (set when proposed).
        mtime = (child / "SKILL.md").stat().st_mtime
        if mtime < cutoff:
            dst = REJECTED_DIR / child.name
            if dst.exists():
                # Don't clobber.
                continue
            child.rename(dst)
            (dst / ".rejection_reason").write_text(
                f"stale: not verified within {PROPOSAL_TTL_DAYS} days\n",
                encoding="utf-8",
            )
            rejected.append(child.name)
            with db() as conn:
                upsert_skill(conn, name=child.name, state="rejected")
                log_event(conn, child.name, EVENT_REJECTED, {"reason": "stale"})
    return rejected


def list_pending_with_hints() -> list[tuple[str, str, Path]]:
    """Return list of (name, hint, proposal_dir) for all pending proposals."""
    out: list[tuple[str, str, Path]] = []
    if not PROPOSED_DIR.exists():
        return out
    for child in PROPOSED_DIR.iterdir():
        if not child.is_dir() or not (child / "SKILL.md").exists():
            continue
        hint_path = child / ".verification_hint"
        hint = hint_path.read_text(encoding="utf-8").strip() if hint_path.exists() else ""
        if hint:
            out.append((child.name, hint, child))
    return out


def extract_task_text(hook_input: dict) -> str:
    """Build a single string representing what just happened, from hook input."""
    parts: list[str] = []
    # The Claude Code Stop hook input includes a transcript_path for the JSONL
    # log of the session. We do NOT read this fully (too expensive); instead we
    # use the last user message and any session_id-derived prompt history if
    # available.
    transcript_path = hook_input.get("transcript_path")
    if transcript_path:
        try:
            p = Path(transcript_path)
            if p.exists() and p.stat().st_size < 2 * 1024 * 1024:  # <2MB
                # Sample the last ~50 lines for keywords.
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Pull text from user/assistant messages.
                    role = obj.get("role") or obj.get("type")
                    content = obj.get("content")
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                txt = item.get("text") or ""
                                if txt:
                                    parts.append(txt)
        except OSError:
            pass

    # Fallback: any field on the hook input itself.
    for key in ("last_user_message", "prompt", "user_input"):
        v = hook_input.get(key)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-pending", action="store_true")
    args = parser.parse_args(argv)

    ensure_layout()
    hook_input = read_hook_input()

    if not args.check_pending:
        # Reserved for future flags; for now, no-op.
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    # 1. Sweep stale proposals.
    stale = auto_reject_stale()

    # 2. Load remaining pending proposals.
    pending = list_pending_with_hints()
    if not pending:
        # Quietly exit. No verifier dispatch needed.
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    # 3. Build a single task summary string.
    task_text = extract_task_text(hook_input)
    if not task_text.strip():
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    # 4. Find the best-matching pending proposal.
    best: tuple[str, str, Path, dict] | None = None
    for name, hint, proposal_dir in pending:
        matched, detail = matches_task(hint, task_text)
        if matched and (best is None or detail["overlap_ratio"] > best[3]["overlap_ratio"]):
            best = (name, hint, proposal_dir, detail)

    if best is None:
        # No proposal matched. Log nothing; quiet exit.
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        return 0

    name, hint, proposal_dir, detail = best

    # 5. Record intent and emit a hookSpecificOutput suggesting verification.
    jsonl_log("verifier_dispatches.jsonl", {
        "ts": now_ts(),
        "skill": name,
        "hint": hint,
        "match_detail": detail,
    })

    # We do not call an LLM here. We surface a small marker in the next-turn
    # context that suggests Claude run the verifier subagent. Claude Code will
    # dispatch agents in agents/ when natural-language asked; this is a
    # deliberate, low-friction nudge.
    additional_context = (
        f"\n[compounded] Pending verification: skill `{name}` matches this task "
        f"(overlap {detail['overlap_words']} words, {detail['overlap_ratio']:.0%}). "
        f"Run the `skill-verifier` subagent against `{proposal_dir}` to graduate or reject it. "
        f"After the subagent returns its JSON verdict, run:\n"
        f"  python3 ${{CLAUDE_PLUGIN_ROOT}}/scripts/finalize_verification.py "
        f"--name {name} --verdict-json '<the JSON>'\n"
    )

    sys.stdout.write(json.dumps({
        "continue": True,
        "suppressOutput": False,
        "additionalContext": additional_context,
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        # Stop-hook failures should never break a session.
        sys.stderr.write(f"compounded skill_verify: {exc}\n")
        sys.stdout.write(json.dumps({"continue": True, "suppressOutput": True}))
        sys.exit(0)
