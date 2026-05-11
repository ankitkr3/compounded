"""Tests for scripts/trust_ladder.py and the promotion/demotion logic."""

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
description: A test skill that abstracts a procedure for example purposes.
---

# Example Skill

## When to use
- A test situation arises.

## Inputs
- `<x>`: input.

## Procedure
1. Do thing.
2. Verify thing.

## Pitfalls
- None.

## Verification
- It worked.
"""


class TrustLadderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="compounded-test-")
        self.env = os.environ.copy()
        self.env["COMPOUNDED_HOME"] = self.tmpdir
        self._stage_verified_skill("example-skill")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stage_verified_skill(self, name: str) -> None:
        # Propose and force-graduate to .verified for testing.
        propose = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "skill_propose.py"),
             "--name", name,
             "--verification-hint", "next time the user does an example task this should reproduce"],
            input=VALID_SKILL,
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(propose.returncode, 0, propose.stderr)
        # Manually graduate via pin_skill.py trust --to verified
        graduate = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "pin_skill.py"), "trust", name, "--to", "verified"],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(graduate.returncode, 0, graduate.stderr)

    def _record_use(self, name: str, corrected: bool = False) -> subprocess.CompletedProcess:
        args = [sys.executable, str(SCRIPTS_DIR / "trust_ladder.py"), "--record-use", name]
        if corrected:
            args.append("--corrected")
        return subprocess.run(args, capture_output=True, text=True, env=self.env)

    def _read_state(self, name: str) -> str:
        for state in ("proposed", "verified", "trusted", "autonomous", "rejected"):
            if (Path(self.tmpdir) / "skills" / f".{state}" / name / "SKILL.md").exists():
                return state
        return "missing"

    def test_three_clean_uses_promotes_verified_to_trusted(self) -> None:
        for _ in range(3):
            r = self._record_use("example-skill")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._read_state("example-skill"), "trusted")

    def test_correction_demotes_verified_to_proposed(self) -> None:
        r = self._record_use("example-skill", corrected=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._read_state("example-skill"), "proposed")

    def test_correction_at_trusted_demotes_to_verified(self) -> None:
        # Promote first.
        for _ in range(3):
            self._record_use("example-skill")
        self.assertEqual(self._read_state("example-skill"), "trusted")
        # Now correct.
        r = self._record_use("example-skill", corrected=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._read_state("example-skill"), "verified")

    def test_path_to_autonomous_requires_total_uses_and_clean_run(self) -> None:
        # 3 clean → trusted
        for _ in range(3):
            self._record_use("example-skill")
        self.assertEqual(self._read_state("example-skill"), "trusted")
        # Now need total uses ≥ 10 AND ≥5 consecutive clean to reach autonomous.
        # We've already used 3. Use 7 more clean → total=10, clean_run=10 ≥ 5.
        for _ in range(7):
            self._record_use("example-skill")
        self.assertEqual(self._read_state("example-skill"), "autonomous")

    def test_pin_blocks_demotion(self) -> None:
        # Pin the skill, then correct.
        pin = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "pin_skill.py"), "pin", "example-skill"],
            capture_output=True, text=True, env=self.env,
        )
        self.assertEqual(pin.returncode, 0, pin.stderr)
        self._record_use("example-skill", corrected=True)
        # Should still be at .verified despite the correction.
        self.assertEqual(self._read_state("example-skill"), "verified")


if __name__ == "__main__":
    unittest.main()
