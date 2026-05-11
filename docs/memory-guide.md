# Memory Guide

When you install compounded, your Claude Code session has *several* memory layers
in play. They serve different purposes, live in different places, and load at
different times. This document explains the full picture so you can use each
layer for what it's good at.

## The four layers, summarized

| Layer | What it is | Where it lives | Who writes it |
|---|---|---|---|
| **CLAUDE.md** | Project instructions you wrote | `<project>/CLAUDE.md` | You |
| **AutoMemory** | Per-project notes Claude Code wrote | `~/.claude/projects/<proj>/memory/` | Claude Code (native) |
| **USER.md** (compounded) | User-global preferences | `~/.claude/compounded/USER.md` | You (mostly) |
| **Skills** (compounded + native) | Reusable procedures | various | Claude Code + you |

## CLAUDE.md (project layer, you-authored)

Per-project file you write yourself. Stays in the project directory, version-controlled with the project. Use this for:

- Project-specific instructions ("we use pnpm, not npm")
- Domain conventions ("this module's exports go through src/index.ts")
- Constraints the agent needs every session ("don't run formatters across the whole codebase, only on edited files")

Authoritative. Loaded at the start of every Claude Code session in the project. Survives because it's in your repo.

## AutoMemory / MEMORY.md (project layer, agent-authored)

Anthropic's native feature, available in Claude Code 2.1.59+. The agent writes notes about *this project* automatically based on corrections you make and patterns it discovers.

- Path: `~/.claude/projects/<project-hash>/memory/MEMORY.md` and topic files
- Loaded: first 200 lines / 25KB injected per session, topic files loaded on demand
- Cleaned up: by AutoDream, between sessions

Use it for: things the agent can't be expected to know about the project unless told. AutoMemory captures these as it learns them. You don't write to MEMORY.md directly — let AutoDream maintain it.

compounded does not touch this layer. It is Anthropic's territory.

## USER.md (compounded, user-global)

The cross-project layer. Lives at `~/.claude/compounded/USER.md`, loaded into every session on every project on this machine.

Use it for: facts about *you*, not your projects.

**Good entries:**

```
User prefers tabs over spaces in Python.
User is in the Asia/Kolkata timezone.
User runs Linux on Ubuntu 24.04 with bash.
User uses pnpm by default for Node projects.
User prefers terse, direct technical responses without preamble.
```

**Bad entries (these belong in CLAUDE.md or AutoMemory):**

```
The auth module uses Sanctum.        ← project-specific, MEMORY.md
The deploy command is `make ship`.   ← project-specific, CLAUDE.md
We are migrating to TypeScript.      ← project-specific, CLAUDE.md
```

**Hard limit: 1500 characters.** When you hit the limit, compounded truncates with a marker rather than silently dropping content. The constraint is the feature — it forces consolidation. If your USER.md gets noisy, prune.

To edit USER.md, just open it:

```bash
$EDITOR ~/.claude/compounded/USER.md
```

There is no "/compounded:edit" command — the file is plain text and you own it.

## Skills (procedures the agent reuses)

This is where compounded's core innovation lives. Skills are SKILL.md files that the agent loads when relevant. Two flavors:

### Native skills (skill-creator)

Hand-authored skills that you've eval-tested with skill-creator. They live in the project's `.claude/skills/` or globally at `~/.claude/skills/`. Loaded by name.

compounded does not touch these. They're skill-creator's territory.

### compounded skills (agent-authored, trust-graduated)

The agent proposes them based on successful task completion. They start in `.proposed/`, graduate through `.verified/` → `.trusted/` → `.autonomous/` based on real use without correction. They live at `~/.claude/compounded/skills/<state>/<name>/SKILL.md`.

This is where the "trainable employee" metaphor is concrete. Each tier has different activation behavior:

- `.verified`: load only when invoked by name
- `.trusted`: auto-load when relevant, ask before applying
- `.autonomous`: run without asking

See [PHILOSOPHY.md](../PHILOSOPHY.md) for the why and the [README.md](../README.md) for the trust ladder rules.

## How they all interact at session start

```
Session start
   │
   ├─ CLAUDE.md (your project file)            ← always loaded
   ├─ MEMORY.md (AutoMemory, first 200 lines)  ← always loaded (per-project)
   ├─ USER.md (compounded, ≤1500 chars)            ← always loaded (machine-global)
   └─ Skill index (names + descriptions only)  ← always loaded
       └─ Full skill content loaded on demand when relevant
```

Everything else is loaded lazily.

## Where to put what

When you have a fact you want the agent to know, ask:

1. **Is it about the project?** → goes in CLAUDE.md (you write) or AutoMemory will capture it (you correct, AutoMemory writes)
2. **Is it about you, across all projects?** → USER.md (you write, ≤1500 chars)
3. **Is it a procedure (multiple steps, repeatable)?** → a skill. If you wrote it, register with skill-creator. If the agent figured it out, let it propose via compounded.

## Composition with claude-mem

[claude-mem](https://github.com/thedotmack/claude-mem) is another memory plugin with a different design philosophy: a daemon, observation capture, vector search, web UI. It does what compounded explicitly chose not to do.

You can run both. They don't overlap on disk:

- compounded: `~/.claude/compounded/`
- claude-mem: `~/.claude-mem/`

compounded handles the verified-skills + cross-project preferences layer. claude-mem handles aggressive observation capture + retrieval. The combination is fine. We use it ourselves.

## Privacy

compounded's data is all on your local disk:

- `~/.claude/compounded/USER.md` — plain text
- `~/.claude/compounded/trust.db` — SQLite
- `~/.claude/compounded/skills/<state>/...` — markdown
- `~/.claude/compounded/logs/*.jsonl` — small JSON-line logs (dispatches and events; no transcript content)

No telemetry. No cloud. No network calls except the verifier subagent (which runs through your own Claude Code auth, just like any agent). You can `cat`, `grep`, `tar`, or `rm -rf` any of it at any time.

## When something goes wrong

- **A skill graduated that shouldn't have:** `/compounded:demote <skill>` to drop it one tier, or `/compounded:trust <skill> --to verified` to reset.
- **A skill got rejected that should have passed:** the original SKILL.md is in `.rejected/<name>/`. Move it back to `.proposed/<name>/` and run `/compounded:verify <name>`.
- **You want to start over:** `rm -rf ~/.claude/compounded`. compounded rebuilds from defaults on next session.
- **You moved machines:** `/compounded:export <archive.tar.gz>` on the old machine, `/compounded:import <archive.tar.gz>` on the new.
