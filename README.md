<div align="center">

<br />

# `compounded`

### Your AI agent gets better at *you* the longer you use it.

Skills earn autonomy through demonstrated reliability — they start `.proposed`, prove themselves to become `.verified`, build a track record to reach `.trusted`, and finally graduate to `.autonomous`. **No daemon. No cloud. No re-explaining.**

<br />

[![Tests](https://github.com/ankitkr3/compounded/actions/workflows/tests.yml/badge.svg)](https://github.com/ankitkr3/compounded/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code Plugin](https://img.shields.io/badge/claude%20code-plugin-D97757?logo=anthropic&logoColor=white)](https://docs.claude.com/en/docs/claude-code/plugins)
[![Stars](https://img.shields.io/github/stars/ankitkr3/compounded?style=flat&color=yellow)](https://github.com/ankitkr3/compounded/stargazers)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)

<br />

**[Install](#install)** · **[How it works](#the-trust-ladder)** · **[Manifesto](MANIFESTO.md)** · **[Philosophy](PHILOSOPHY.md)** · **[Docs](docs/)** · **[Compare](#how-compounded-composes)**

<br />

</div>

---

## Why compounded?

> Claude Code's **AutoMemory** writes notes. **AutoDream** cleans them.
> **compounded verifies them — and lets them earn the right to act.**

When your agent saves a skill from a successful task, compounded holds it in `.proposed/`. The next time a similar task comes up, a verifier subagent replays the procedure. Pass → `.verified`. Three clean uses → `.trusted`. Ten uses with no recent corrections → `.autonomous`. One correction sends it back a step.

**It's how you train a junior. It's how you should train your agent.**

<br />

## Install

```sh
# In Claude Code:
/plugin marketplace add ankitkr3/compounded-marketplace
/plugin install compounded@compounded-marketplace
```

Restart Claude Code. That's it.

<table>
<tr>
<td>✅ No daemon to run</td>
<td>✅ No cloud account</td>
<td>✅ No telemetry</td>
<td>✅ 100% local</td>
</tr>
<tr>
<td>✅ Python stdlib only</td>
<td>✅ SQLite + flat files</td>
<td>✅ Portable archive</td>
<td>✅ MIT licensed</td>
</tr>
</table>

<br />

## The trust ladder

```
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │  .proposed   │───▶│  .verified   │───▶│   .trusted   │───▶│ .autonomous  │
   │              │    │              │    │              │    │              │
   │ awaiting     │    │  1 verifier  │    │  3 clean     │    │  10+ uses,   │
   │ verification │    │   PASS       │    │  uses        │    │  5+ clean    │
   └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
         ▲                    ▲                    ▲                    │
         │                    │                    │                    │
         └────────── correction = one tier down ───┴────────────────────┘
```

| Tier | Behavior | Activation |
|---|---|---|
| `.proposed` | Authored by the agent, awaiting verification | Never auto-loads |
| `.verified` | Replayed once successfully on a real task | Loads only when invoked by name |
| `.trusted` | 3+ clean uses on real follow-ups | Auto-loads, asks before applying |
| `.autonomous` | 10+ uses, last 5 clean, no recent corrections | Runs without asking |

Demotions happen automatically: **one correction = one tier down**. Three corrections in 30 days = back to `.proposed`. Pin a skill with `/compounded:pin <skill>` to lock it at its current tier.

Run `/compounded:trust-status` to see where every skill sits and what's about to promote or demote.

<br />

## What compounded actually does

Three things. That's the whole pitch.

<table>
<tr>
<td width="33%" valign="top">

### 🧠 Cross-project memory

A user-global `USER.md` (~/.claude/compounded/USER.md) gets injected into every session, on every project, on every machine.

AutoMemory writes per-project notes — compounded writes the **preferences and facts that follow you** across all of them. Hard-bounded at 1500 characters by design, so it stays readable and useful.

</td>
<td width="33%" valign="top">

### ✓ Verified skills

When the agent proposes a skill, it's a **hypothesis until proven**. The verifier subagent replays the procedure against a real follow-up task and decides PASS or FAIL with a logged reason.

Skills that pass start at `.verified` and graduate by demonstrating reliability over real use. Skills that fail go to `.rejected/` (recoverable, not deleted) with the reason on disk.

</td>
<td width="33%" valign="top">

### 📦 Portable archive

`/compounded:export ~/Desktop/compounded.tar.gz` produces a single archive: USER.md + every active skill + the trust state.

`/compounded:import` merges it on a new machine. **Your earned skills aren't trapped** on the laptop you're typing on right now.

</td>
</tr>
</table>

<br />

## Demo

Run the included lifecycle demo to see propose → verify → use × 3 → trust → use × 7 → autonomous → correction → demote in 30 seconds:

```sh
bash docs/demo.sh
```

```text
[1/8] proposing skill 'typo-fixer' ......................... .proposed/
[2/8] running verifier subagent (claude-haiku-4-5) ......... PASS
[3/8] moved to .verified/, ready for use
[4/8] used 3× on real follow-ups ........................... promoted → .trusted
[5/8] used 7× more, last 5 clean ........................... promoted → .autonomous
[6/8] one correction on use #11 ............................ demoted → .trusted
[7/8] exported archive ..................................... compounded.tar.gz (12KB)
[8/8] imported on a fresh install .......................... ✓ same state
```

<br />

## How compounded composes

compounded does not replace anything. It is the **verification + portability layer** of a stack:

| Tool | What it does | What compounded adds |
|---|---|---|
| **AutoMemory** (native) | Per-project notes, MEMORY.md | Cross-project USER.md |
| **AutoDream** (native) | Consolidates project memory between sessions | Verifies skills, not notes |
| **skill-creator** (native) | Eval-based testing of hand-authored skills | Replay-based verification of agent-authored skills |
| **[superpowers](https://github.com/obra/superpowers)** | TDD / brainstorm / plan methodology | Memory + earned trust gradient |
| **[claude-mem](https://github.com/thedotmack/claude-mem)** | Daemon-based observation capture | No daemon, different model |
| **Karpathy CLAUDE.md** | Behavioral principles | Composable — drop both into your project |

Each layer does one thing well. None of them does what compounded does.

<br />

## Commands

| Command | What it does |
|---|---|
| `/compounded:status` | USER.md size, skill counts by tier, recent transitions |
| `/compounded:trust-status` | The full trust ladder, with promotion/demotion candidates highlighted |
| `/compounded:export <path>` | Bundle USER.md + verified skills into a portable archive |
| `/compounded:import <path>` | Merge an archive on this machine |
| `/compounded:verify <skill>` | Manually run the verifier on a `.proposed/` skill |
| `/compounded:trust <skill> --to <tier>` | Manual promotion (skip the gradient) |
| `/compounded:demote <skill>` | Drop a skill one tier |
| `/compounded:pin <skill>` | Lock a skill at its current tier (no auto-demotion) |
| `/compounded:unpin <skill>` | Remove a pin |

<br />

## What's stored where

```
~/.claude/compounded/
├── USER.md                   ← user-global preferences (loaded every session)
├── trust.db                  ← SQLite: skill state, events, sessions
├── config.json               ← per-user config
├── skills/
│   ├── .proposed/<name>/     ← awaiting verification
│   ├── .verified/<name>/     ← passed verification
│   ├── .trusted/<name>/      ← 3+ clean uses
│   ├── .autonomous/<name>/   ← 10+ uses, recent run clean
│   ├── .rejected/<name>/     ← failed verification (recoverable)
│   └── .pinned               ← list of pinned skill names
└── logs/
    └── verifier_dispatches.jsonl
```

**All local. All inspectable. All editable** if something goes wrong.

<br />

## What it doesn't do

| Won't do | Why |
|---|---|
| ❌ No daemon | Zero install friction. Hooks fire when Claude Code fires them. |
| ❌ No cloud / telemetry / account | Your skills are yours. |
| ❌ No vector index / embeddings / GPU | Keyword overlap + replay is enough. |
| ❌ No transcript capture | [claude-mem](https://github.com/thedotmack/claude-mem) does that — use both if you want both. |
| ❌ No project memory cleanup | AutoDream does that. |
| ❌ No eval framework | skill-creator does that. |

Every "no" is deliberate. **compounded does three things and stops.**

<br />

## Cost

The verifier subagent runs on **Claude Haiku 4.5** by default. Each verification is roughly 1500 input tokens + a small JSON response.

> **Expected cost at typical usage: under $0.20/month.**

The verifier only runs when a `.proposed/` skill matches the just-finished task, which for most users is a handful of times per week.

To switch to Sonnet for higher-accuracy verification (~5× the cost), edit `~/.claude/compounded/config.json`:

```json
{
  "skills": {
    "verifier_model": "claude-sonnet-4-6"
  }
}
```

<br />

## Tested

22 unit tests covering memory injection, skill proposal, security scanning, trust-ladder transitions in all directions, pin behavior, archive roundtrip, and verdict finalization.

```sh
git clone https://github.com/ankitkr3/compounded
cd compounded
python3 -m unittest discover tests/ -v
```

CI runs the suite on **Linux + macOS** across **Python 3.9–3.12** on every PR.

<br />

## The four principles

[**Read the manifesto.**](MANIFESTO.md) Four principles, one page, copy-pasteable.

1. **Bounded over Unbounded** — memory should be small enough to read in one breath.
2. **Verified over Recalled** — a skill that replayed successfully is a fact; one that was merely saved is a hypothesis.
3. **Earned over Granted** — authority is earned, not assumed.
4. **Composable over Comprehensive** — small tool, sharp wedge, plays well with everything else.

<br />

## Contributing

PRs welcome. New built-in skills, bug fixes, doc improvements.

```sh
python3 -m unittest discover tests/ -v
```

For new built-in skills (skills that ship with compounded itself, not user-authored skills), follow the format of `skills/compounded-typo-fixer/SKILL.md` and include the criteria the skill is meant to demonstrate.

See [CLAUDE.md](CLAUDE.md) for codebase conventions.

<br />

## License

[MIT](LICENSE). Fork, ship, sell. Just include the notice.

<br />

## Why "compounded"

Capability that compounds is the whole point. Every verified skill compounds the agent's toolkit. Every clean use compounds the trust in that skill. Every correction compounds *back* — trust isn't given once, it's earned and re-earned. The trust ladder is compound interest applied to demonstrated reliability: small reliable acts that, over time, become the foundation for larger autonomous ones.

> "The most powerful force in the universe is compound interest."  —  Albert Einstein (apocryphal)

The product is named for what it does to your agent.

---

<div align="center">

<sub>

**[Manifesto](MANIFESTO.md)** · **[Philosophy](PHILOSOPHY.md)** · **[Install Guide](INSTALL.md)** · **[Architecture](docs/architecture.md)** · **[Memory Guide](docs/memory-guide.md)** · **[Skill Authoring](docs/skill-authoring.md)** · **[Privacy](docs/privacy.md)**

</sub>

<br />

<sub>Built for [Claude Code](https://docs.claude.com/en/docs/claude-code) · Made with discipline by [@ankitkr3](https://github.com/ankitkr3)</sub>

</div>
