"""Tests for scripts/archive.py: export/import roundtrip."""

from __future__ import annotations

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
- A test arises.

## Procedure
1. Do thing.

## Verification
- Thing was done.
"""


class ArchiveRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine_a = tempfile.mkdtemp(prefix="compounded-machine-a-")
        self.machine_b = tempfile.mkdtemp(prefix="compounded-machine-b-")
        self.archive_path = Path(tempfile.gettempdir()) / "compounded-test-archive.tar.gz"
        if self.archive_path.exists():
            self.archive_path.unlink()

    def tearDown(self) -> None:
        shutil.rmtree(self.machine_a, ignore_errors=True)
        shutil.rmtree(self.machine_b, ignore_errors=True)
        if self.archive_path.exists():
            self.archive_path.unlink()

    def _run(self, env_home: str, script: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["COMPOUNDED_HOME"] = env_home
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / script), *args],
            input=stdin,
            capture_output=True, text=True, env=env,
        )

    def test_export_import_roundtrip(self) -> None:
        # On machine A: write USER.md, propose+verify a skill.
        Path(self.machine_a).mkdir(parents=True, exist_ok=True)
        user_md = Path(self.machine_a) / "USER.md"
        user_md.write_text("User prefers tabs.\nUser is in PST.\n", encoding="utf-8")

        propose = self._run(
            self.machine_a, "skill_propose.py",
            "--name", "example-skill",
            "--verification-hint", "next time user does an example task this should reproduce",
            stdin=VALID_SKILL,
        )
        self.assertEqual(propose.returncode, 0, propose.stderr)
        graduate = self._run(
            self.machine_a, "pin_skill.py", "trust", "example-skill", "--to", "verified",
        )
        self.assertEqual(graduate.returncode, 0, graduate.stderr)

        # Export
        export = self._run(
            self.machine_a, "archive.py", "export",
            "--output", str(self.archive_path),
            "--force",
        )
        self.assertEqual(export.returncode, 0, export.stderr)
        self.assertTrue(self.archive_path.exists(), "archive was not written")

        # Import on machine B
        import_ = self._run(
            self.machine_b, "archive.py", "import",
            "--input", str(self.archive_path),
        )
        self.assertEqual(import_.returncode, 0, import_.stderr)

        # Verify USER.md and skill made it across.
        b_user = Path(self.machine_b) / "USER.md"
        self.assertTrue(b_user.exists())
        self.assertIn("tabs", b_user.read_text(encoding="utf-8"))

        b_skill = Path(self.machine_b) / "skills" / ".verified" / "example-skill" / "SKILL.md"
        self.assertTrue(b_skill.exists())
        self.assertIn("Example Skill", b_skill.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
