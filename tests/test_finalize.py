"""Tests for scripts/finalize_verification.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"

VALID_SKILL = """---
name: example-skill
description: Test skill.
---

# Example Skill

## When to use
- A test situation arises.

## Procedure
1. Do thing.

## Verification
- Thing was done.
"""


class FinalizeVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="compounded-test-")
        self.env = os.environ.copy()
        self.env["COMPOUNDED_HOME"] = self.tmpdir

        # Stage a proposed skill.
        propose = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "skill_propose.py"),
             "--name", "example-skill",
             "--verification-hint", "next time the user does an example task this should reproduce"],
            input=VALID_SKILL,
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(propose.returncode, 0, propose.stderr)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_finalize(self, name: str, verdict: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "finalize_verification.py"),
             "--name", name, "--verdict-json", json.dumps(verdict)],
            capture_output=True, text=True, env=self.env,
        )

    def test_pass_verdict_graduates_to_verified(self) -> None:
        verdict = {
            "verdict": "PASS",
            "reason_code": "ok",
            "reason_text": "looks good",
            "step_or_field": None,
            "confidence": 0.9,
        }
        result = self._run_finalize("example-skill", verdict)
        self.assertEqual(result.returncode, 0, result.stderr)
        verified = Path(self.tmpdir) / "skills" / ".verified" / "example-skill" / "SKILL.md"
        proposed = Path(self.tmpdir) / "skills" / ".proposed" / "example-skill"
        self.assertTrue(verified.exists())
        self.assertFalse(proposed.exists())

    def test_pass_with_notes_graduates_to_verified(self) -> None:
        verdict = {"verdict": "PASS-with-notes", "reason_code": "ok", "reason_text": "minor caveat", "step_or_field": None, "confidence": 0.7}
        result = self._run_finalize("example-skill", verdict)
        self.assertEqual(result.returncode, 0, result.stderr)
        verified = Path(self.tmpdir) / "skills" / ".verified" / "example-skill" / "SKILL.md"
        self.assertTrue(verified.exists())

    def test_fail_verdict_moves_to_rejected(self) -> None:
        verdict = {
            "verdict": "FAIL",
            "reason_code": "step-would-have-failed",
            "reason_text": "step 1 references hardcoded path",
            "step_or_field": "step-1",
            "confidence": 0.95,
        }
        result = self._run_finalize("example-skill", verdict)
        self.assertEqual(result.returncode, 0, result.stderr)
        rejected = Path(self.tmpdir) / "skills" / ".rejected" / "example-skill" / "SKILL.md"
        proposed = Path(self.tmpdir) / "skills" / ".proposed" / "example-skill"
        self.assertTrue(rejected.exists())
        self.assertFalse(proposed.exists())
        reason = (Path(self.tmpdir) / "skills" / ".rejected" / "example-skill" / ".rejection_reason").read_text(encoding="utf-8")
        self.assertIn("step-would-have-failed", reason)

    def test_unknown_verdict_rejected(self) -> None:
        verdict = {"verdict": "MAYBE", "reason_code": "ok", "reason_text": "x", "step_or_field": None, "confidence": 0.5}
        result = self._run_finalize("example-skill", verdict)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown verdict", result.stderr)


if __name__ == "__main__":
    unittest.main()
