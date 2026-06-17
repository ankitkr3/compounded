"""Tests for scripts/auto_propose.py — heuristic-based skill proposal nudge."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _user(text: str) -> dict:
    return {"type": "user", "content": [{"type": "text", "text": text}]}


def _tool_result(text: str = "ok", is_error: bool = False) -> dict:
    return {
        "type": "user",
        "content": [{"type": "tool_result", "tool_use_id": "x", "content": text, "is_error": is_error}],
    }


def _assistant(tool_uses: list[tuple[str, dict]] | None = None, text: str = "") -> dict:
    content: list[dict] = []
    if text:
        content.append({"type": "text", "text": text})
    for name, inp in tool_uses or []:
        content.append({"type": "tool_use", "name": name, "input": inp})
    return {"type": "assistant", "content": content}


def _wrap(ev: dict) -> dict:
    """Re-shape a top-level-content event into Claude Code's transcript schema.

    Real session transcripts nest the message body under a "message" key, e.g.
    ``{"type": "assistant", "message": {"role": ..., "content": [...]}}``. The
    scorer must read content from there, not from the top level.
    """
    role = ev.get("type") or ev.get("role")
    return {"type": role, "message": {"role": role, "content": ev.get("content")}}


class AutoProposeScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="compounded-test-"))
        os.environ["COMPOUNDED_HOME"] = str(self.tmp)
        # Force-reimport _lib + auto_propose to pick up the env var.
        for mod in list(sys.modules):
            if mod in ("auto_propose", "_lib"):
                del sys.modules[mod]
        import auto_propose  # noqa: F401
        self.auto_propose = auto_propose

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("COMPOUNDED_HOME", None)

    def test_empty_turn_does_not_fire(self) -> None:
        events = [_user("hi"), _assistant(text="hello")]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["fire"])
        self.assertEqual(signals["score"], 0)

    def test_one_tool_call_does_not_fire(self) -> None:
        events = [
            _user("read this file"),
            _assistant(tool_uses=[("Read", {"file_path": "/a.py"})]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["fire"])

    def test_multi_tool_multi_edit_fires(self) -> None:
        events = [
            _user("refactor the auth module across three files"),
            _assistant(tool_uses=[
                ("Read", {"file_path": "/auth.py"}),
                ("Read", {"file_path": "/user.py"}),
                ("Read", {"file_path": "/session.py"}),
                ("Edit", {"file_path": "/auth.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/user.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/session.py", "old_string": "x", "new_string": "y"}),
                ("Bash", {"command": "pytest"}),
            ]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["fire"])
        self.assertGreaterEqual(signals["tool_uses"], 5)
        self.assertGreaterEqual(len(signals["edit_files"]), 2)

    def test_recovery_signal_boosts_score(self) -> None:
        events = [
            _user("run the tests"),
            _assistant(tool_uses=[("Bash", {"command": "pytest"})]),
            _tool_result(text="FAILED", is_error=True),
            _assistant(tool_uses=[("Edit", {"file_path": "/fix.py", "old_string": "x", "new_string": "y"})]),
            _tool_result(),
            _assistant(tool_uses=[("Bash", {"command": "pytest"})]),
            _tool_result(text="passed"),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["recovery"])
        # 3 tool uses + 1 edit + 2 bash + recovery (+2) → score 3, fires
        self.assertGreaterEqual(signals["score"], self.auto_propose.SCORE_TO_FIRE)

    def test_correction_with_work_captures_rule(self) -> None:
        # A correction followed by real corrective work is the primary
        # learning trigger: it fires in RULE mode, not procedure mode.
        events = [
            _user("no, that's wrong. search the web for the latest model first."),
            _assistant(tool_uses=[
                ("WebSearch", {"query": "latest gemini embedding model"}),
                ("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"}),
                ("Bash", {"command": "pytest"}),
            ]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["correction"])
        self.assertTrue(signals["fire"])
        self.assertEqual(signals["capture_kind"], "rule")

    def test_correction_without_work_stays_silent(self) -> None:
        # A correction answered with plain text (no corrective tool work)
        # has nothing concrete to learn from yet.
        events = [
            _user("no, that's wrong."),
            _assistant(text="You're right, sorry — here is the corrected explanation."),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["correction"])
        self.assertFalse(signals["fire"])
        self.assertIsNone(signals["capture_kind"])

    def test_soft_user_correction_captures_rule(self) -> None:
        # Regression: real user phrasing from the field — polite doubt, no
        # hard "no"/"wrong" keywords. Must still arm rule capture.
        events = [
            _user("i think its gemini 2 , can u web search and confirm on this"),
            _assistant(tool_uses=[
                ("WebSearch", {"query": "best Gemini embedding model 2026"}),
                ("WebSearch", {"query": "Google Gemini 2 embedding model release"}),
            ]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["correction_user"])
        self.assertEqual(signals["capture_kind"], "rule")

    def test_assistant_acknowledgment_captures_rule_for_any_phrasing(self) -> None:
        # Channel 2: the user's phrasing matches NO hard correction pattern, but
        # the message shows doubt ("?" / "maybe") and the assistant's reply
        # acknowledges the correction. Doubt corroborates the ack → fires.
        events = [
            _user("hmm gemini 2 maybe?"),
            _assistant(
                tool_uses=[("WebSearch", {"query": "latest gemini embedding"})],
                text="You're right — there's a newer one. gemini-embedding-2 supersedes it.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction_user"])   # phrasing matched nothing
        self.assertTrue(signals["correction_ack"])     # Claude's reaction did
        self.assertEqual(signals["capture_kind"], "rule")

    def test_ack_alone_without_user_doubt_does_not_fire(self) -> None:
        # Regression (field): the dominant false positive. The user gives a
        # neutral directive (no doubt, no question) and Claude's reply happens
        # to open with ack vocabulary ("I was wrong …"). Channel 2 must NOT
        # arm a correction without user-side corroboration.
        events = [
            _user("yes, write up the plan and make sure we only improve it, not degrade it"),
            _assistant(
                tool_uses=[
                    ("Read", {"file_path": "/a.py"}),
                    ("Bash", {"command": "ls"}),
                ],
                text="I was wrong about that earlier — fair point. Here is the corrected plan.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["correction_ack"])     # ack phrasing present
        self.assertFalse(signals["user_doubt"])        # but user expressed none
        self.assertFalse(signals["correction"])        # so no correction armed
        self.assertIsNone(signals["capture_kind"])

    def test_assistant_self_correction_in_meta_discussion_silent(self) -> None:
        # Claude correcting its OWN prior analysis (no user pushback at all)
        # must stay silent — there is no user correction to learn from.
        events = [
            _user("find why it's misfiring"),
            _assistant(
                tool_uses=[("Read", {"file_path": "/auto_propose.py"})],
                text="You're right to ask. I was wrong in my earlier read — here's the real cause.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["user_doubt"])
        self.assertNotEqual(signals["capture_kind"], "rule")

    def test_ack_with_user_question_mark_still_fires(self) -> None:
        # Preserve channel 2 for genuine doubt: a bare question + ack still
        # arms rule capture even with no hard correction keyword.
        events = [
            _user("wait is that the current api?"),
            _assistant(
                tool_uses=[("WebSearch", {"query": "current anthropic api version"})],
                text="Good catch — you're right, there's a newer one.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction_user"])
        self.assertTrue(signals["user_doubt"])         # via "?"
        self.assertEqual(signals["capture_kind"], "rule")

    def test_ack_with_soft_doubt_no_question_mark_fires(self) -> None:
        # Soft doubt without a question mark ("i think u are wrong …") still
        # corroborates the ack. Mirrors the settle-race field case at unit level.
        events = [
            _user("i think u are wrong, gemini already has a newer model, can u web search and tell"),
            _assistant(
                tool_uses=[("WebSearch", {"query": "latest gemini embedding model"})],
                text="You were right — Google shipped a newer one.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction_user"])   # no hard pattern matches
        self.assertTrue(signals["user_doubt"])         # via "i think" / "wrong"
        self.assertEqual(signals["capture_kind"], "rule")

    def test_pattern_buried_in_user_paste_is_not_a_correction(self) -> None:
        # Regression (field): the user pasted a transcript that contained
        # "Is there a newer [model / SDK / tool] than [X]?" ~1000 chars in —
        # quoted content, not a correction. Only the opening counts.
        paste = (
            "here is what happened in my other session, it worked great:\n"
            + "lorem ipsum status output " * 40
            + "\n## When this fires\n- \"Is there a newer [model / SDK / tool] than [X]?\"\n"
        )
        events = [
            _user(paste),
            _assistant(
                tool_uses=[("Bash", {"command": "ls"})],
                text="Glad it worked — both rules are active now.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction_user"])
        self.assertNotEqual(signals["capture_kind"], "rule")

    def test_ack_phrase_quoted_deep_in_assistant_reply_is_not_a_correction(self) -> None:
        # Regression (field): the assistant *explaining* the detector quoted
        # phrases like "You're right" mid-message and tripped channel 2.
        long_explainer = (
            "Here is how the detection design works. " * 12
            + 'The model normalizes phrasing into forms like "you\'re right" or "my mistake", '
            "which the hook reads as channel 2."
        )
        events = [
            _user("explain how the detector works"),
            _assistant(tool_uses=[("Read", {"file_path": "/x.py"})], text=long_explainer),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction_ack"])
        self.assertNotEqual(signals["capture_kind"], "rule")

    def test_neutral_exchange_is_not_a_correction(self) -> None:
        events = [
            _user("thanks, also add a docstring please"),
            _assistant(
                tool_uses=[("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"})],
                text="Added the docstring.",
            ),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction"])
        self.assertNotEqual(signals["capture_kind"], "rule")

    def test_clean_high_signal_turn_captures_procedure(self) -> None:
        events = [
            _user("set up the project scaffolding"),
            _assistant(tool_uses=[
                ("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/b.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/c.py", "old_string": "x", "new_string": "y"}),
                ("Bash", {"command": "pytest"}),
                ("Bash", {"command": "ls"}),
            ]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertFalse(signals["correction"])
        self.assertTrue(signals["fire"])
        self.assertEqual(signals["capture_kind"], "procedure")

    def test_distinct_files_counted_not_duplicate_edits(self) -> None:
        events = [
            _user("fix it"),
            _assistant(tool_uses=[
                ("Edit", {"file_path": "/same.py", "old_string": "a", "new_string": "b"}),
                ("Edit", {"file_path": "/same.py", "old_string": "c", "new_string": "d"}),
                ("Edit", {"file_path": "/same.py", "old_string": "e", "new_string": "f"}),
            ]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertEqual(len(signals["edit_files"]), 1)
        # 3 tools, 1 file, no bash, no recovery → score 0
        self.assertEqual(signals["score"], 0)

    def test_tool_result_user_messages_not_treated_as_user_prompts(self) -> None:
        # Real user "fix it" → assistant uses tools → Claude Code sends tool_result
        # back wrapped as a "user" message. The tool_result wrapper must not be
        # treated as a fresh user prompt that splits the turn.
        events = [
            _user("refactor the module"),
            _assistant(tool_uses=[("Bash", {"command": "ls"})]),
            _tool_result(),
            _assistant(tool_uses=[("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"})]),
            _tool_result(),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        # Should treat both assistant events as part of the same turn.
        tool_uses = list(self.auto_propose._iter_tool_uses(turn))
        self.assertEqual(len(tool_uses), 2)
        # Prior user is the real user prompt.
        self.assertIn("refactor", self.auto_propose._extract_text(prior).lower())


class AutoProposeTranscriptSchemaTests(unittest.TestCase):
    """Regression: real Claude Code transcripts nest content under "message".

    Before the fix, the scorer read ``ev.get("content")`` at the top level,
    which is always absent in real transcripts — so every session scored 0 and
    the proposer never fired. These tests feed the wrapped schema.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="compounded-test-"))
        os.environ["COMPOUNDED_HOME"] = str(self.tmp)
        for mod in list(sys.modules):
            if mod in ("auto_propose", "_lib"):
                del sys.modules[mod]
        import auto_propose
        self.auto_propose = auto_propose

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("COMPOUNDED_HOME", None)

    def test_wrapped_schema_counts_tool_uses(self) -> None:
        events = [
            _wrap(_user("refactor the auth module across three files")),
            _wrap(_assistant(tool_uses=[
                ("Read", {"file_path": "/auth.py"}),
                ("Edit", {"file_path": "/auth.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/user.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/session.py", "old_string": "x", "new_string": "y"}),
                ("Bash", {"command": "pytest"}),
            ])),
            _wrap(_tool_result()),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertGreaterEqual(signals["tool_uses"], 5)
        self.assertGreaterEqual(len(signals["edit_files"]), 2)
        self.assertTrue(signals["fire"])

    def test_wrapped_correction_signal_read_from_message(self) -> None:
        events = [
            _wrap(_user("no, that's wrong. undo it.")),
            _wrap(_assistant(tool_uses=[("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"})])),
            _wrap(_tool_result()),
        ]
        turn, prior = self.auto_propose._split_into_turns(events)
        signals = self.auto_propose.score_turn(turn, prior)
        self.assertTrue(signals["correction"])
        self.assertEqual(signals["capture_kind"], "rule")


class AutoProposeMainTests(unittest.TestCase):
    """End-to-end: feed a transcript file to main() and inspect stdout."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="compounded-test-"))
        self.transcript = self.tmp / "transcript.jsonl"
        os.environ["COMPOUNDED_HOME"] = str(self.tmp / "home")
        for mod in list(sys.modules):
            if mod in ("auto_propose", "_lib"):
                del sys.modules[mod]
        import auto_propose
        self.auto_propose = auto_propose

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("COMPOUNDED_HOME", None)

    def _write_transcript(self, events: list[dict]) -> None:
        self.transcript.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8",
        )

    def _run(self, hook_input: dict) -> dict:
        from io import StringIO

        old_stdin, old_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = StringIO(json.dumps(hook_input))
            sys.stdout = StringIO()
            rc = self.auto_propose.main()
            output = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
        return {"rc": rc, "output": json.loads(output) if output.strip() else {}}

    def test_missing_transcript_path_safe_default(self) -> None:
        result = self._run({})
        self.assertEqual(result["rc"], 0)
        self.assertTrue(result["output"].get("continue"))
        self.assertTrue(result["output"].get("suppressOutput"))

    def test_low_signal_session_silent(self) -> None:
        self._write_transcript([_user("hello"), _assistant(text="hi")])
        result = self._run({"transcript_path": str(self.transcript)})
        self.assertEqual(result["rc"], 0)
        self.assertTrue(result["output"].get("suppressOutput"))
        self.assertNotIn("additionalContext", result["output"])

    def test_high_signal_session_fires(self) -> None:
        events = [
            _user("set up the project"),
            _assistant(tool_uses=[
                ("Bash", {"command": "mkdir -p src tests"}),
                ("Bash", {"command": "touch src/main.py tests/test_main.py"}),
                ("Edit", {"file_path": "/src/main.py", "old_string": "", "new_string": "def main(): pass"}),
                ("Edit", {"file_path": "/tests/test_main.py", "old_string": "", "new_string": "def test(): assert True"}),
                ("Bash", {"command": "pytest"}),
            ]),
            _tool_result(),
            _assistant(text="Project scaffolding is set up and tests pass."),
        ]
        self._write_transcript(events)
        result = self._run({"transcript_path": str(self.transcript), "session_id": "abc"})
        self.assertEqual(result["rc"], 0)
        # Procedure capture surfaces to the USER via systemMessage and never
        # blocks the stop (additionalContext is not honored for Stop hooks).
        self.assertNotIn("decision", result["output"])
        self.assertIn("systemMessage", result["output"])
        self.assertIn("Auto-propose threshold reached", result["output"]["systemMessage"])
        self.assertIn("save this as a skill", result["output"]["systemMessage"])

    def _correction_events(self) -> list[dict]:
        return [
            _user("no, that's wrong — web-search for the latest embedding model first."),
            _assistant(tool_uses=[
                ("WebSearch", {"query": "latest gemini embedding model 2026"}),
                ("Edit", {"file_path": "/embed.py", "old_string": "old-model", "new_string": "new-model"}),
            ]),
            _tool_result(),
            _assistant(text="Done — switched to the newer model."),
        ]

    def test_correction_session_blocks_with_rule_reason(self) -> None:
        # Rule capture must use the Stop-hook block channel — additionalContext
        # is silently dropped for Stop hooks and would never reach Claude.
        self._write_transcript(self._correction_events())
        result = self._run({"transcript_path": str(self.transcript), "session_id": "abc"})
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["output"].get("decision"), "block")
        reason = result["output"]["reason"]
        self.assertIn("Correction detected", reason)
        self.assertIn("RULE MODE", reason)
        self.assertIn("AskUserQuestion", reason)  # approval gate is part of the nudge

    def test_rule_block_suppressed_when_stop_hook_active(self) -> None:
        # Loop guard: when this Stop fires after a previous block, never
        # block again — otherwise blocked-stop -> work -> blocked-stop forever.
        self._write_transcript(self._correction_events())
        result = self._run({
            "transcript_path": str(self.transcript),
            "session_id": "abc",
            "stop_hook_active": True,
        })
        self.assertEqual(result["rc"], 0)
        self.assertNotIn("decision", result["output"])
        self.assertTrue(result["output"].get("suppressOutput"))

    def _make_pending_proposal(self, name: str = "foo") -> None:
        home = Path(os.environ["COMPOUNDED_HOME"])
        proposed_dir = home / "skills" / ".proposed" / name
        proposed_dir.mkdir(parents=True, exist_ok=True)
        (proposed_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: x\n---\n", encoding="utf-8"
        )

    def test_pending_proposal_does_not_block_rule_capture(self) -> None:
        # Regression (field): a saved rule sat in .proposed/ and the old
        # binary debounce muted ALL further learning — the next correction
        # (the Gemini case) was never even scored. Saves are user-approved,
        # so pending proposals must not gate capture.
        self._make_pending_proposal()
        self._write_transcript(self._correction_events())
        result = self._run({"transcript_path": str(self.transcript), "session_id": "abc"})
        self.assertEqual(result["output"].get("decision"), "block")
        self.assertIn("RULE MODE", result["output"]["reason"])

    def test_pending_proposal_does_not_block_procedure_hint(self) -> None:
        self._make_pending_proposal()
        events = [
            _user("do a big refactor"),
            _assistant(tool_uses=[
                ("Edit", {"file_path": "/a.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/b.py", "old_string": "x", "new_string": "y"}),
                ("Edit", {"file_path": "/c.py", "old_string": "x", "new_string": "y"}),
                ("Bash", {"command": "pytest"}),
                ("Bash", {"command": "git status"}),
            ]),
            _tool_result(),
            _assistant(text="Refactor complete."),
        ]
        self._write_transcript(events)
        result = self._run({"transcript_path": str(self.transcript)})
        self.assertIn("systemMessage", result["output"])
        self.assertNotIn("decision", result["output"])

    def test_settle_waits_for_late_final_message(self) -> None:
        # Regression (field): Claude Code fired the Stop hook before the
        # turn's final assistant message hit the transcript. The ack lived
        # only in that message ("You were right — ..."), so channel 2
        # silently read stale data and never fired. The hook must wait for
        # the tail to settle.
        import threading

        events = [
            _user("i think u are wrong gemini already has newer model can u web search and tell"),
            _assistant(tool_uses=[("WebSearch", {"query": "latest gemini embedding model 2026"})]),
            _tool_result(),
            # final assistant message intentionally missing — flushed late
        ]
        self._write_transcript(events)

        def append_final_message() -> None:
            with self.transcript.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_assistant(
                    text="You were right — Google released Gemini Embedding 2 in 2026."
                )) + "\n")

        t = threading.Timer(0.4, append_final_message)
        t.start()
        try:
            result = self._run({"transcript_path": str(self.transcript), "session_id": "race"})
        finally:
            t.join()
        # With the settle wait, the late ack is seen and rule capture fires.
        self.assertEqual(result["output"].get("decision"), "block")
        self.assertIn("RULE MODE", result["output"]["reason"])


if __name__ == "__main__":
    unittest.main()
