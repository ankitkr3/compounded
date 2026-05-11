# Architecture

This document explains how compounded is wired together at runtime. It is for
contributors and curious users who want to know exactly what happens when.

## The big picture

```
┌────────────────────────────────────────────────────────────────────┐
│  Claude Code (the host)                                            │
│                                                                    │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ SessionStart │    │     Stop     │    │      SessionEnd      │  │
│  │     hook     │    │     hook     │    │         hook         │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │                   │                       │              │
│         ▼                   ▼                       ▼              │
│   memory_inject.py    skill_verify.py    trust_ladder.py           │
│         │                   │                       │              │
│         │                   │                       │              │
│         ▼                   ▼                       ▼              │
└─────────┼───────────────────┼───────────────────────┼──────────────┘
          │                   │                       │
          │              dispatches if                │
          │              proposal matches             │
          │                   │                       │
          │                   ▼                       │
          │         ┌─────────────────────┐           │
          │         │  skill-verifier     │           │
          │         │  subagent (Haiku)   │           │
          │         └──────────┬──────────┘           │
          │                    │ JSON                 │
          │                    ▼                      │
          │       finalize_verification.py            │
          │                    │                      │
          ▼                    ▼                      ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                  ~/.claude/compounded/                           │
   │  ┌──────────┐  ┌────────────┐  ┌─────────────────────────┐   │
   │  │ USER.md  │  │  trust.db  │  │  skills/.{state}/...    │   │
   │  └──────────┘  └────────────┘  └─────────────────────────┘   │
   └──────────────────────────────────────────────────────────────┘
```

Three hooks. One subagent. Five Python scripts. One SQLite database. One markdown file. That's it.

## Components in detail

### `_lib.py` — the shared library

Single source of truth for paths, constants, the trust DB schema, and helpers used by every other script. Pure stdlib. Imported by every other script.

Key responsibilities:

- **Path resolution.** `COMPOUNDED_HOME` defaults to `~/.claude/compounded/` and can be overridden via env var (used heavily in tests).
- **DB schema setup.** `db()` is a context manager that opens SQLite in WAL mode, sets a 5s busy timeout, and ensures the schema exists.
- **Trust state model.** Constants for the four states, the directory mapping, the promotion thresholds, the demotion thresholds.
- **Frontmatter parsing.** Lightweight YAML-style parser that handles the simple `key: value` shape of skill frontmatter without bringing in PyYAML.
- **Security scanning.** A regex-based detector for prompt injection attempts, dangerous commands, and Unicode bidi attacks. Used by `skill_propose.py` to gate untrusted content from agent-authored skills.

### `memory_inject.py` — SessionStart hook

Fires on `startup`, `resume`, `clear`, `compact`. Reads stdin (Claude Code's hook input JSON, mostly ignored), reads `~/.claude/compounded/USER.md`, builds a small status summary including skill counts by tier, and emits:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "<formatted block>"
  }
}
```

Hard requirements:

- Must run in <100ms typical, <5s ceiling.
- Must never crash. On any exception, write to stderr and exit 0. A broken hook should not break a session.
- Must respect the 1500-char USER.md limit by truncating with a marker, not by silently chopping.

### `skill_propose.py` — agent-invoked skill proposal

Called via Bash by the agent when it has authored a SKILL.md and wants to stage it. Validates:

1. Skill name is kebab-case, ≤64 chars
2. Verification hint is ≥20 chars (forces useful hints)
3. SKILL.md has YAML frontmatter with `name` and `description`
4. Frontmatter `name` matches the `--name` arg (catches copy-paste errors)
5. Body is non-empty
6. Total size ≤64KB
7. No threat patterns matched by the security scanner
8. No collision with an existing skill (unless `--force` and target is `.proposed/` or `.rejected/`)

If all pass, the script:

- Writes `~/.claude/compounded/skills/.proposed/<name>/SKILL.md`
- Writes the verification hint to `.verification_hint`
- Inserts/updates a row in the `skills` table with state `proposed`
- Logs a `proposed` event

### `skill_verify.py` — Stop hook

Fires after every agent turn. Steps:

1. **Sweep stale proposals.** Anything older than 30 days gets moved to `.rejected/` with reason `stale`.

2. **List remaining proposals** that have a `.verification_hint` file.

3. **Build a task summary.** Reads the last ~50 lines of the session transcript JSONL (capped at 2MB to avoid memory blowup) and any `last_user_message` field on the hook input. Joins everything into a single string of recent dialogue.

4. **Match.** Tokenize the task summary and each hint into keywords (3+ chars, alphanumeric, stopwords filtered). A proposal matches if there's ≥2-keyword overlap AND ≥20% of the hint's keywords are in the task. The match is conservative on purpose — false dispatches cost the user verifier inference tokens.

5. **Emit a context block.** If a match is found, the hook outputs a structured `additionalContext` instructing Claude to dispatch the `skill-verifier` subagent with the proposal contents and the task transcript, and to apply the resulting JSON verdict via `finalize_verification.py`.

This is the only place compounded depends on Claude (the host) doing something semi-intelligent — interpreting an instruction in the additionalContext and acting on it. Everything else is deterministic Python.

### `skill-verifier` subagent

Defined in `agents/skill-verifier.md`. Dispatched in-session by Claude when nudged by the Stop hook. Configured to use `claude-haiku-4-5-20251001` for cost efficiency. Reads the proposed SKILL.md and the task transcript, applies the rubric defined in `skills/compounded-verifier/SKILL.md`, and returns a JSON verdict object with fields:

```json
{
  "verdict": "PASS | PASS-with-notes | PASS-low-confidence | FAIL",
  "reason_code": "ok | malformed-frontmatter | not-abstracted | ...",
  "reason_text": "one-sentence explanation",
  "step_or_field": "step-N or field-name or null",
  "confidence": 0.0
}
```

Calibrated for inclusive PASS bias. Most well-formed proposals graduate. Failures are specific and logged.

### `finalize_verification.py` — apply the verdict

Reads `--name` and `--verdict-json` from CLI. Parses the verdict. If PASS-family, moves the skill from `.proposed/` to `.verified/` and writes the verdict to `.verification_verdict` for audit. If FAIL, moves to `.rejected/` with the reason on disk. Updates the trust DB and logs the event. Returns 0 on either disposition.

### `trust_ladder.py` — the gradient logic

The heart of the autonomy system. Three callable modes:

- `--record-use <skill>` (with optional `--corrected`): records a single use event and applies any triggered transitions.
- `--report-skill <skill>`: prints a skill's current state and counters.
- `--process-session`: runs the cascade-demotion check across all active skills.

Transitions use a compact rule table:

| Current | Next clean uses needed | Demotion trigger |
|---|---|---|
| `.verified` | 3 to `.trusted` | 1 correction → `.proposed` |
| `.trusted` | (10 total + 5 clean run) to `.autonomous` | 1 correction → `.verified` |
| `.autonomous` | — | 1 correction → `.trusted` |
| Any active | — | 3 corrections in 30d → `.proposed` |

Pinned skills are exempt from the auto-demotion path (manual demote still works).

### `archive.py` — export/import

Bundles state into a single `.tar.gz`:

- `compounded-manifest.json` — schema version, timestamp, machine identifier hash, counts
- `USER.md` — verbatim
- `skills.json` — per-skill metadata: name, state, hint, verdict, counters
- `skills/<state>/<name>/SKILL.md` — the actual skill files

Import merges:

- USER.md: appended-with-separator if local file is non-empty (or `--overwrite`)
- Skills: skipped if name collides locally (unless `--overwrite`)
- DB rows: re-created with carried counters; an `imported` event is logged

### `status.py` — human-readable views

Two outputs:

- **Default (`/compounded:status`)** — USER.md size, counts by tier, recent transitions, recent rejections.
- **`--trust-ladder`** — per-skill table grouped by tier, with promotion-candidate and demotion-candidate annotations.

### `pin_skill.py` — manual overrides

Subcommands `pin`, `unpin`, `trust --to <tier>`, `demote`. Used by the corresponding slash commands. Pin state lives in `~/.claude/compounded/skills/.pinned` (one name per line).

## The trust DB

SQLite at `~/.claude/compounded/trust.db`, three tables.

### `skills`

| Column | Type | Notes |
|---|---|---|
| `name` | TEXT PK | kebab-case skill name |
| `state` | TEXT | `proposed` / `verified` / `trusted` / `autonomous` / `rejected` |
| `proposed_at` | INT | unix timestamp |
| `verified_at` | INT | unix timestamp, nullable |
| `last_used_at` | INT | nullable |
| `last_promoted_at` | INT | nullable |
| `last_demoted_at` | INT | nullable |
| `use_count` | INT | total uses since first verification |
| `correction_count` | INT | lifetime correction count |
| `clean_uses_since_correction` | INT | reset to 0 on each correction; reset to 0 on promotion |
| `verification_hint` | TEXT | nullable |
| `pinned` | INT | bool, 0/1 |

### `events`

Append-only log. One row per state-changing action.

| Column | Type | Notes |
|---|---|---|
| `id` | INT PK | autoincrement |
| `skill_name` | TEXT | references skills.name |
| `event_type` | TEXT | `proposed` / `verified` / `rejected` / `used` / `corrected` / `promoted` / `demoted` / `pinned` / `unpinned` |
| `timestamp` | INT | unix |
| `detail` | TEXT | optional JSON-serialized dict |

Indexed on `(skill_name, timestamp DESC)` and `(event_type, timestamp DESC)`.

### `sessions`

Reserved for v1.1+ session-aware analysis. Currently unused.

## Failure modes and recovery

**The trust DB is corrupted or unreadable.** Delete `~/.claude/compounded/trust.db`. compounded rebuilds the schema on next run. Skill files on disk are the source of truth for state; counters reset to 0.

**A SKILL.md was edited by hand to be invalid frontmatter.** The skill stays in its directory but loses its event-log presence. `/compounded:status` will still see the directory; the verifier dispatch logic handles missing hint files gracefully.

**A hook script crashes.** Wrapped in try/except with safe-default exit. Worst case is a missing `additionalContext` injection for that one session; nothing user-visible breaks.

**A verifier subagent returns malformed JSON.** `finalize_verification.py` rejects the input with exit code 2 and a clear error. The proposal stays in `.proposed/` for retry.

**COMPOUNDED_HOME is on a network share that times out.** `db()` uses a 5s busy timeout and WAL mode for tolerance. If the share is fully down, hooks emit warnings to stderr and exit 0.

## What's intentionally not here

- No daemon process
- No port binding
- No vector index, no embeddings
- No transcript capture or summarization
- No project-memory consolidation (AutoDream's job)
- No eval framework (skill-creator's job)
- No metrics export, no dashboard, no UI

The smaller surface area is the design.
