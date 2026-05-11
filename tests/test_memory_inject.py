"""Tests for scripts/memory_inject.py and the shared library."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"


class MemoryInjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="compounded-test-")
        self.env = os.environ.copy()
        self.env["COMPOUNDED_HOME"] = self.tmpdir

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_script(self, script: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / script), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_session_start_with_empty_user_md(self) -> None:
        result = self.run_script("memory_inject.py", stdin=json.dumps({"source": "startup"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("USER.md is empty", ctx)
        self.assertIn("compounded:", ctx)

    def test_session_start_with_user_content(self) -> None:
        user_md = Path(self.tmpdir) / "USER.md"
        user_md.write_text("User prefers tabs over spaces.\nUser is in PST.\n", encoding="utf-8")
        result = self.run_script("memory_inject.py", stdin=json.dumps({"source": "startup"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("tabs over spaces", ctx)
        self.assertIn("PST", ctx)
        self.assertIn("USER.md (compounded, user-global)", ctx)

    def test_session_start_truncates_oversized_user_md(self) -> None:
        user_md = Path(self.tmpdir) / "USER.md"
        user_md.write_text("X" * 5000, encoding="utf-8")
        result = self.run_script("memory_inject.py", stdin=json.dumps({}))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[truncated to char limit]", ctx)

    def test_session_start_never_fails_loudly(self) -> None:
        # Even with garbage stdin, the hook should not return non-zero.
        result = self.run_script("memory_inject.py", stdin="not json at all")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
