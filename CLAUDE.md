# CLAUDE.md (compounded repository)

This file is read by Claude Code when working *inside this repo*. It describes the codebase, conventions, and what to do (and not do) when proposing changes.

## What this repo is

compounded is a Claude Code plugin that adds a trust gradient and verified skills on top of Claude's native memory primitives. The plugin layout follows the Claude Code plugin spec:

- `.claude-plugin/plugin.json` — manifest
- `skills/<name>/SKILL.md` — built-in skills (5 of them)
- `commands/<name>.md` — slash commands (9 of them)
- `agents/<name>.md` — subagent definitions (1)
- `hooks/hooks.json` — lifecycle hooks (SessionStart, Stop, SessionEnd)
- `scripts/*.py` — Python implementation (no runtime deps; stdlib only)
- `tests/` — unittest suite

## Conventions

- **Python is stdlib-only.** No third-party imports. compounded must not pull in dependencies for its core path. We pay this cost gladly to keep install friction at zero.
- **Hooks must never fail loudly.** A SessionStart or Stop hook that crashes the user's session is a P0 bug. Wrap in try/except and emit `{"continue": true, "suppressOutput": true}` on any unexpected failure. See the bottom of `scripts/memory_inject.py` for the pattern.
- **All paths go through `_lib.py`.** Don't hardcode paths in individual scripts. Add them to `_lib.py` so they respect `COMPOUNDED_HOME`.
- **All trust state changes log an event.** Every promotion, demotion, verification, rejection, and use must call `log_event()`. The event log is how the user audits the system.
- **No LLM calls from scripts.** The scripts are deterministic Python. The only LLM call is the verifier subagent, which is dispatched through Claude Code's native agent system (not a direct API call).

## How the lifecycle works

1. **SessionStart hook** (`memory_inject.py`) — reads USER.md, injects it as `additionalContext`. Runs in <100ms typically.

2. **During the session** — the agent may invoke `skill_propose.py` (via Bash) when it wants to save a procedure. The script validates frontmatter, runs a security scan, writes to `.proposed/<name>/`, and records to the trust DB.

3. **Stop hook** (`skill_verify.py`) — fires when the agent finishes a turn. Sweeps stale proposals (auto-rejects after 30 days), checks remaining proposals against the just-finished task via keyword overlap, and emits an `additionalContext` block asking Claude to dispatch the `skill-verifier` subagent if a match is found.

4. **Verifier subagent runs** — defined in `agents/skill-verifier.md`, runs on Haiku by default. Returns a JSON verdict.

5. **`finalize_verification.py`** — applies the verdict. PASS → move to `.verified/`. FAIL → move to `.rejected/`.

6. **Subsequent uses** trigger `trust_ladder.py --record-use <name>` (TODO: this needs a hook integration that's planned for v1.1; for now the user invokes it manually or through the demo flow). Promotions and demotions happen automatically based on the rules in `_lib.py` constants.

7. **SessionEnd hook** (`trust_ladder.py --process-session`) — runs the cascade-demote check for skills that have hit the correction-window threshold.

## What you can change

- Bug fixes in any script
- New tests
- New built-in skills (under `skills/`)
- New slash commands (under `commands/`)
- Doc improvements (README, INSTALL, PHILOSOPHY, MANIFESTO, docs/)

## What you should not change without discussion

- The trust ladder thresholds (3 clean for trusted, 10 + 5 for autonomous, 30-day demotion window). These are calibrated empirically and changing them affects every user's experience.
- The `_lib.py` constants section. Adding new constants is fine; renaming or repurposing existing ones is a breaking change.
- Hook timing or lifecycle. The hook script names appear in `hooks/hooks.json` and changing them silently breaks installs.
- The MANIFESTO.md. It's the viral artifact; it has been word-engineered. Tweaks need a reason.

## Testing

```bash
python3 -m unittest discover tests/ -v
```

All 22 tests should pass. CI runs them on every PR (when CI is set up). Adding new functionality requires adding new tests.

## Style

- Type hints on all function signatures
- Docstrings on every public function
- 4-space indentation, ~100-column soft limit
- snake_case for variables, PascalCase for classes
- Imports: stdlib first, blank line, local imports

## Common tasks

**Add a new built-in skill:**

1. Create `skills/<new-name>/SKILL.md` with valid frontmatter.
2. Add a test fixture if applicable.
3. Update README's "What compounded actually does" section if the skill is user-facing.

**Add a new slash command:**

1. Create `commands/<new-name>.md`. The frontmatter `description:` shows up in `/plugin` UI.
2. The command body is what Claude executes.
3. Add a row to README's commands table.

**Add a new lifecycle hook:**

1. Add to `hooks/hooks.json`.
2. Create the corresponding script in `scripts/`.
3. Wrap in try/except with safe-default exit. Hooks must never break sessions.
4. Add tests.

## What to ignore

- Anything in `~/.claude/compounded/` (user data, never in repo)
- The `*.pyc` and `__pycache__/` (gitignored)
- Anything in `.proposed/`, `.verified/`, etc. — those are user runtime state, not source

## Don't accumulate

This is a small repo. Keep it small. Every new file should justify itself. If a feature can be punted to v1.1 in favor of fixing what's already here, punt it.
