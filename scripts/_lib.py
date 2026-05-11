"""
compounded shared library.

Single source of truth for:
- Paths to compounded state on disk
- Trust state names and transitions
- The trust database (SQLite)
- Helpers used across all scripts and hooks

This file is imported by every other script in compounded. Keep it lean.
Never import anything outside the Python stdlib here.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

COMPOUNDED_HOME = Path(os.environ.get("COMPOUNDED_HOME", Path.home() / ".claude" / "compounded"))
USER_MD = COMPOUNDED_HOME / "USER.md"
SKILLS_DIR = COMPOUNDED_HOME / "skills"
LOGS_DIR = COMPOUNDED_HOME / "logs"
DB_PATH = COMPOUNDED_HOME / "trust.db"
CONFIG_PATH = COMPOUNDED_HOME / "config.json"

# Trust state subdirectories under SKILLS_DIR.
PROPOSED_DIR = SKILLS_DIR / ".proposed"
VERIFIED_DIR = SKILLS_DIR / ".verified"
TRUSTED_DIR = SKILLS_DIR / ".trusted"
AUTONOMOUS_DIR = SKILLS_DIR / ".autonomous"
REJECTED_DIR = SKILLS_DIR / ".rejected"
PINNED_FILE = SKILLS_DIR / ".pinned"

# -----------------------------------------------------------------------------
# Trust states
# -----------------------------------------------------------------------------

PROPOSED = "proposed"
VERIFIED = "verified"
TRUSTED = "trusted"
AUTONOMOUS = "autonomous"
REJECTED = "rejected"

ALL_STATES = (PROPOSED, VERIFIED, TRUSTED, AUTONOMOUS, REJECTED)
ACTIVE_STATES = (VERIFIED, TRUSTED, AUTONOMOUS)

STATE_DIRS = {
    PROPOSED: PROPOSED_DIR,
    VERIFIED: VERIFIED_DIR,
    TRUSTED: TRUSTED_DIR,
    AUTONOMOUS: AUTONOMOUS_DIR,
    REJECTED: REJECTED_DIR,
}

# Promotion thresholds.
PROMOTION_VERIFIED_TO_TRUSTED_USES = 3
PROMOTION_TRUSTED_TO_AUTONOMOUS_USES = 10
PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN = 5

# Demotion thresholds.
DEMOTION_CORRECTIONS_FOR_PROPOSED = 3
DEMOTION_WINDOW_DAYS = 30

# Auto-rejection of stale proposals.
PROPOSAL_TTL_DAYS = 30

# Char limits.
USER_MD_CHAR_LIMIT = 1500


# -----------------------------------------------------------------------------
# Filesystem setup
# -----------------------------------------------------------------------------

def ensure_layout() -> None:
    """Create all required directories and files. Idempotent."""
    COMPOUNDED_HOME.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    for d in STATE_DIRS.values():
        d.mkdir(parents=True, exist_ok=True)
    if not USER_MD.exists():
        USER_MD.write_text("", encoding="utf-8")
    if not PINNED_FILE.exists():
        PINNED_FILE.write_text("", encoding="utf-8")
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")


DEFAULT_CONFIG = {
    "memory": {
        "user_char_limit": USER_MD_CHAR_LIMIT,
    },
    "skills": {
        "proposal_ttl_days": PROPOSAL_TTL_DAYS,
        "verifier_model": "claude-haiku-4-5-20251001",
    },
    "privacy": {
        "log_token_usage": False,
    },
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return DEFAULT_CONFIG
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG


# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);

CREATE TABLE IF NOT EXISTS skills (
    name TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    proposed_at INTEGER NOT NULL,
    verified_at INTEGER,
    last_used_at INTEGER,
    last_promoted_at INTEGER,
    last_demoted_at INTEGER,
    use_count INTEGER NOT NULL DEFAULT 0,
    correction_count INTEGER NOT NULL DEFAULT 0,
    clean_uses_since_correction INTEGER NOT NULL DEFAULT 0,
    verification_hint TEXT,
    pinned INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_skill ON events (skill_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type, timestamp DESC);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    project_path TEXT,
    last_user_message TEXT,
    last_assistant_summary TEXT
);
"""

EVENT_PROPOSED = "proposed"
EVENT_VERIFIED = "verified"
EVENT_REJECTED = "rejected"
EVENT_USED = "used"
EVENT_CORRECTED = "corrected"
EVENT_PROMOTED = "promoted"
EVENT_DEMOTED = "demoted"
EVENT_PINNED = "pinned"
EVENT_UNPINNED = "unpinned"


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Context manager for a SQLite connection in WAL mode."""
    ensure_layout()
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        with conn:  # transaction
            _init_schema(conn)
            yield conn
    finally:
        conn.close()


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))


# -----------------------------------------------------------------------------
# Skill record helpers
# -----------------------------------------------------------------------------

def now_ts() -> int:
    return int(time.time())


def get_skill(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM skills WHERE name = ?", (name,))
    return cur.fetchone()


def upsert_skill(
    conn: sqlite3.Connection,
    name: str,
    state: str,
    verification_hint: Optional[str] = None,
) -> None:
    existing = get_skill(conn, name)
    ts = now_ts()
    if existing is None:
        conn.execute(
            """
            INSERT INTO skills (
                name, state, proposed_at, verification_hint
            ) VALUES (?, ?, ?, ?)
            """,
            (name, state, ts, verification_hint),
        )
    else:
        conn.execute("UPDATE skills SET state = ? WHERE name = ?", (state, name))


def log_event(
    conn: sqlite3.Connection,
    skill_name: str,
    event_type: str,
    detail: Optional[dict] = None,
) -> None:
    conn.execute(
        "INSERT INTO events (skill_name, event_type, timestamp, detail) VALUES (?, ?, ?, ?)",
        (skill_name, event_type, now_ts(), json.dumps(detail) if detail else None),
    )


# -----------------------------------------------------------------------------
# Skill files on disk
# -----------------------------------------------------------------------------

KEBAB_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def is_valid_skill_name(name: str) -> bool:
    return bool(KEBAB_RE.fullmatch(name))


def find_skill_dir(name: str) -> Optional[tuple[str, Path]]:
    """Return (state, path) for a skill if it exists in any state, else None."""
    for state, base in STATE_DIRS.items():
        candidate = base / name
        if candidate.is_dir() and (candidate / "SKILL.md").exists():
            return state, candidate
    return None


def move_skill(name: str, from_state: str, to_state: str) -> Path:
    """Move a skill directory between trust states. Returns the new path."""
    src = STATE_DIRS[from_state] / name
    dst = STATE_DIRS[to_state] / name
    if not src.is_dir():
        raise FileNotFoundError(f"skill {name!r} not found in {from_state}")
    if dst.exists():
        raise FileExistsError(f"skill {name!r} already exists in {to_state}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return dst


def is_pinned(name: str) -> bool:
    if not PINNED_FILE.exists():
        return False
    pinned = {line.strip() for line in PINNED_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    return name in pinned


def set_pinned(name: str, pinned: bool) -> None:
    current = set()
    if PINNED_FILE.exists():
        current = {line.strip() for line in PINNED_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    if pinned:
        current.add(name)
    else:
        current.discard(name)
    PINNED_FILE.write_text("\n".join(sorted(current)) + ("\n" if current else ""), encoding="utf-8")


# -----------------------------------------------------------------------------
# Frontmatter parsing
# -----------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[Optional[dict], str]:
    """Parse YAML-style frontmatter. Returns (fields_dict_or_None, body_text)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    raw = match.group(1)
    body = text[match.end():]
    fields = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


# -----------------------------------------------------------------------------
# Security scan
# -----------------------------------------------------------------------------

DANGEROUS_PATTERNS = [
    re.compile(r"<\s*system\b", re.IGNORECASE),
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+all\s+(prior|previous)", re.IGNORECASE),
    re.compile(r"rm\s+-rf\s+/(?!\w)"),
    re.compile(r"curl\s+[^\s]*\s*\|\s*(bash|sh)\b"),
    re.compile(r"\\u200[bcdef]"),  # invisible Unicode
]


def scan_for_threats(text: str) -> Optional[str]:
    """Return a reason string if threat detected, else None."""
    for pat in DANGEROUS_PATTERNS:
        if pat.search(text):
            return f"matches threat pattern: {pat.pattern}"
    if any(ord(c) in (0x202E, 0x202D, 0x202B, 0x202A) for c in text):
        return "contains bidi control characters"
    return None


# -----------------------------------------------------------------------------
# Lightweight logging
# -----------------------------------------------------------------------------

def jsonl_log(filename: str, obj: dict) -> None:
    """Append a JSON line to LOGS_DIR/<filename>."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# -----------------------------------------------------------------------------
# JSON I/O for hook scripts
# -----------------------------------------------------------------------------

def read_hook_input() -> dict:
    """Read JSON from stdin. Hook scripts get input on stdin from Claude Code."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def write_hook_output(obj: dict) -> None:
    """Write JSON to stdout for Claude Code to parse."""
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


__all__ = [
    "ACTIVE_STATES", "ALL_STATES", "AUTONOMOUS", "AUTONOMOUS_DIR",
    "CONFIG_PATH", "DB_PATH", "DEFAULT_CONFIG", "DEMOTION_CORRECTIONS_FOR_PROPOSED",
    "DEMOTION_WINDOW_DAYS", "EVENT_CORRECTED", "EVENT_DEMOTED", "EVENT_PINNED",
    "EVENT_PROMOTED", "EVENT_PROPOSED", "EVENT_REJECTED", "EVENT_UNPINNED",
    "EVENT_USED", "EVENT_VERIFIED", "LOGS_DIR", "COMPOUNDED_HOME",
    "PINNED_FILE", "PROMOTION_TRUSTED_TO_AUTONOMOUS_CLEAN_RUN",
    "PROMOTION_TRUSTED_TO_AUTONOMOUS_USES", "PROMOTION_VERIFIED_TO_TRUSTED_USES",
    "PROPOSAL_TTL_DAYS", "PROPOSED", "PROPOSED_DIR", "REJECTED", "REJECTED_DIR",
    "SKILLS_DIR", "STATE_DIRS", "TRUSTED", "TRUSTED_DIR", "USER_MD",
    "USER_MD_CHAR_LIMIT", "VERIFIED", "VERIFIED_DIR",
    "db", "ensure_layout", "find_skill_dir", "get_skill", "is_pinned",
    "is_valid_skill_name", "jsonl_log", "load_config", "log_event",
    "move_skill", "now_ts", "parse_frontmatter", "read_hook_input",
    "scan_for_threats", "set_pinned", "upsert_skill", "write_hook_output",
]
