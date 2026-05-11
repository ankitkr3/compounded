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

    def test_correction_kills_proposal(self) -> None:
        events = [
            _user("no, that's wrong. undo all of it and try again."),
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
        self.assertTrue(signals["correction"])
        self.assertFalse(signals["fire"])  # kill switch

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
        ]
        self._write_transcript(events)
        result = self._run({"transcript_path": str(self.transcript), "session_id": "abc"})
        self.assertEqual(result["rc"], 0)
        self.assertIn("additionalContext", result["output"])
        self.assertIn("Auto-propose threshold reached", result["output"]["additionalContext"])

    def test_pending_proposal_debounces(self) -> None:
        # Create a pre-existing .proposed/foo
        home = Path(os.environ["COMPOUNDED_HOME"])
        proposed_dir = home / "skills" / ".proposed" / "foo"
        proposed_dir.mkdir(parents=True, exist_ok=True)
        (proposed_dir / "SKILL.md").write_text("---\nname: foo\ndescription: x\n---\n", encoding="utf-8")

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
        ]
        self._write_transcript(events)
        result = self._run({"transcript_path": str(self.transcript)})
        # Should be silent because a proposal is pending.
        self.assertTrue(result["output"].get("suppressOutput"))
        self.assertNotIn("additionalContext", result["output"])


if __name__ == "__main__":
    unittest.main()
