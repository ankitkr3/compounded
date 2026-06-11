"""Tests for scripts/skill_verify.py — task-text extraction and stale sweep."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


class SkillVerifyTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="compounded-test-"))
        os.environ["COMPOUNDED_HOME"] = str(self.tmp / "home")
        for mod in list(sys.modules):
            if mod in ("skill_verify", "_lib"):
                del sys.modules[mod]
        import skill_verify
        self.skill_verify = skill_verify
        self.skill_verify.ensure_layout()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("COMPOUNDED_HOME", None)


class ExtractTaskTextTests(SkillVerifyTestBase):
    """Regression: real Claude Code transcripts nest content under "message".

    Before the fix, extract_task_text read top-level "content", which is
    always absent in real transcripts — so keyword matching never fired and
    proposals sat unverified until the stale sweep rejected them.
    """

    def _write_transcript(self, events: list[dict]) -> Path:
        p = self.tmp / "transcript.jsonl"
        p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return p

    def test_wrapped_schema_text_extracted(self) -> None:
        events = [
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "migrate the express server to fastify"},
            ]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "text", "text": "Done — routes preserved."},
            ]}},
        ]
        p = self._write_transcript(events)
        text = self.skill_verify.extract_task_text({"transcript_path": str(p)})
        self.assertIn("fastify", text)
        self.assertIn("routes preserved", text)

    def test_top_level_content_still_works(self) -> None:
        events = [
            {"type": "user", "content": [{"type": "text", "text": "convert tabs to spaces"}]},
        ]
        p = self._write_transcript(events)
        text = self.skill_verify.extract_task_text({"transcript_path": str(p)})
        self.assertIn("tabs", text)


class StaleSweepTests(SkillVerifyTestBase):
    def _propose(self, name: str, kind: str | None, age_days: int) -> Path:
        d = self.skill_verify.PROPOSED_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        kind_line = f"kind: {kind}\n" if kind else ""
        skill_md = d / "SKILL.md"
        skill_md.write_text(
            f"---\nname: {name}\ndescription: test skill\n{kind_line}---\n\n# {name}\n",
            encoding="utf-8",
        )
        old = time.time() - age_days * 86400
        os.utime(skill_md, (old, old))
        return d

    def test_stale_procedure_is_rejected(self) -> None:
        self._propose("old-procedure", kind=None, age_days=45)
        rejected = self.skill_verify.auto_reject_stale()
        self.assertIn("old-procedure", rejected)
        self.assertTrue((self.skill_verify.REJECTED_DIR / "old-procedure").exists())

    def test_stale_rule_is_exempt(self) -> None:
        # Rule skills capture corrections whose trigger may not recur within
        # the procedure TTL; the sweep must leave them in .proposed/.
        self._propose("latest-model-web-search", kind="rule", age_days=45)
        rejected = self.skill_verify.auto_reject_stale()
        self.assertNotIn("latest-model-web-search", rejected)
        self.assertTrue(
            (self.skill_verify.PROPOSED_DIR / "latest-model-web-search" / "SKILL.md").exists()
        )

    def test_fresh_procedure_is_kept(self) -> None:
        self._propose("fresh-procedure", kind=None, age_days=2)
        rejected = self.skill_verify.auto_reject_stale()
        self.assertNotIn("fresh-procedure", rejected)


class VerifierDispatchTests(SkillVerifyTestBase):
    """The dispatch must use decision:"block" — additionalContext is silently
    dropped for Stop hooks and the verifier would never run."""

    def _setup_matching_proposal_and_transcript(self) -> Path:
        d = self.skill_verify.PROPOSED_DIR / "express-to-fastify"
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            "---\nname: express-to-fastify\ndescription: migrate express to fastify\n---\n\n# x\n",
            encoding="utf-8",
        )
        (d / ".verification_hint").write_text(
            "next time the user asks to migrate an express server to fastify",
            encoding="utf-8",
        )
        p = self.tmp / "transcript.jsonl"
        events = [
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "please migrate my express server to fastify"},
            ]}},
        ]
        p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        return p

    def _run_main(self, hook_input: dict) -> dict:
        from io import StringIO
        old_stdin, old_stdout = sys.stdin, sys.stdout
        try:
            sys.stdin = StringIO(json.dumps(hook_input))
            sys.stdout = StringIO()
            rc = self.skill_verify.main(["--check-pending"])
            out = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
        return {"rc": rc, "output": json.loads(out) if out.strip() else {}}

    def test_matching_task_blocks_with_dispatch_reason(self) -> None:
        p = self._setup_matching_proposal_and_transcript()
        result = self._run_main({"transcript_path": str(p)})
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["output"].get("decision"), "block")
        self.assertIn("express-to-fastify", result["output"]["reason"])
        self.assertIn("skill-verifier", result["output"]["reason"])

    def test_dispatch_suppressed_when_stop_hook_active(self) -> None:
        p = self._setup_matching_proposal_and_transcript()
        result = self._run_main({"transcript_path": str(p), "stop_hook_active": True})
        self.assertEqual(result["rc"], 0)
        self.assertNotIn("decision", result["output"])
        self.assertTrue(result["output"].get("suppressOutput"))


if __name__ == "__main__":
    unittest.main()
