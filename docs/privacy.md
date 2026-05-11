# Privacy

This document is the complete inventory of what compounded stores, where, when it's transmitted, and what it never touches. If you're evaluating whether compounded is appropriate for a sensitive context, this is the doc.

## What compounded stores

All on local disk. None in any cloud.

| Path | Contents |
|---|---|
| `~/.claude/compounded/USER.md` | User-global preferences (you author this) |
| `~/.claude/compounded/trust.db` | SQLite: skill state, event log, sessions table |
| `~/.claude/compounded/config.json` | Local config |
| `~/.claude/compounded/skills/.proposed/<name>/SKILL.md` | Pending proposals |
| `~/.claude/compounded/skills/.verified/<name>/SKILL.md` | Verified skills |
| `~/.claude/compounded/skills/.trusted/<name>/SKILL.md` | Trusted skills |
| `~/.claude/compounded/skills/.autonomous/<name>/SKILL.md` | Autonomous skills |
| `~/.claude/compounded/skills/.rejected/<name>/SKILL.md` | Rejected proposals (recoverable) |
| `~/.claude/compounded/skills/.pinned` | Plain-text list of pinned skill names |
| `~/.claude/compounded/logs/verifier_dispatches.jsonl` | One line per verifier dispatch |

That's the entire inventory. You can `find ~/.claude/compounded -type f` and verify it.

## What's in the event log

The `events` table in `trust.db` records:

- `proposed`, `verified`, `rejected`, `used`, `corrected`, `promoted`, `demoted`, `pinned`, `unpinned`

Each row has skill name, event type, timestamp, and an optional JSON detail blob. The detail blob may include things like `{"reason": "stale"}` or `{"verdict": "PASS", "confidence": 0.85}`. **The detail blob never includes session content, prompts, transcripts, or user input.**

You can read the full event log:

```bash
sqlite3 ~/.claude/compounded/trust.db "SELECT * FROM events ORDER BY timestamp DESC LIMIT 50;"
```

## What gets transmitted, when, and to whom

compounded sends data to one place only: **the verifier subagent**, and only when a `.proposed/` skill matches a just-completed task.

When this happens:

1. The Stop hook decides a match exists locally (no network).
2. It writes an `additionalContext` block telling Claude to dispatch the `skill-verifier` subagent.
3. Claude (the host) dispatches the subagent through normal agent dispatch — the same path used for any subagent in any plugin.
4. The subagent receives: the proposed SKILL.md content (~500 tokens), the verification hint (~50 tokens), and a summary of the just-completed task (~500 tokens).
5. The subagent runs through your existing Claude API auth and returns a JSON verdict.

compounded itself makes **zero network calls**. The verifier dispatch is Claude Code's standard agent path.

## What compounded never sees or stores

- Your full session transcripts (only a ~50-line tail is read at Stop hook time, in-memory, for keyword matching)
- Your prompts or messages in any persistent form
- File contents from your projects
- Your shell history
- Your env vars beyond `COMPOUNDED_HOME` and the env passed to subprocess calls
- Any kind of identifier beyond a hash of `<username>@<hostname>:<platform>` used in archive manifests (visible only inside archive files you create)

## Telemetry

There is none. compounded does not call home, does not register installs, does not phone Anthropic or anyone else. The plugin directory contains no telemetry-emitting code.

To verify, search the codebase:

```bash
grep -rn "requests\|urllib\|http\." ~/.claude/plugins/cache/compounded/scripts/
```

You'll find one match: `urllib` is **not imported anywhere**. The only network surface is the verifier subagent dispatch through Claude Code's normal agent path.

## What's in `verifier_dispatches.jsonl`

This log is created when the Stop hook decides to dispatch the verifier. Each line is:

```json
{"ts": 1715472000, "skill": "express-to-fastify", "hint": "...", "match_detail": {...}}
```

The hint is text you wrote (or the agent wrote on your behalf). The match_detail contains the keyword overlap result. **No user prompts, no transcript content, no project files.**

To inspect:

```bash
cat ~/.claude/compounded/logs/verifier_dispatches.jsonl
```

To clear:

```bash
rm ~/.claude/compounded/logs/verifier_dispatches.jsonl
```

## What's in archive exports

`/compounded:export` produces a `.tar.gz` containing:

- `compounded-manifest.json`: a 16-character hash of `<username>@<hostname>:<platform>` (for collision detection on import), schema version, timestamp, counts. **No raw username, no raw hostname.**
- `USER.md`: verbatim contents
- `skills.json`: per-skill metadata (name, state, hint, verdict, counters)
- `skills/<state>/<name>/SKILL.md`: skill files

Things deliberately excluded by default:

- The event log (the `events` table) — full audit history may contain timing details you don't want to share
- The proposals and rejections (`--include-pending` opts in)
- The raw `trust.db` file (we serialize the relevant rows into JSON for portability)
- The `verifier_dispatches.jsonl` log

If you're sharing an archive with a colleague, inspect it before sending:

```bash
tar -tzf compounded-export.tar.gz       # list contents
tar -xzf compounded-export.tar.gz -C /tmp/check  # extract for inspection
```

## Who can read your compounded data

- **You**, on the machine where compounded runs.
- **Anyone with read access to your home directory.** This is your standard Unix permissions story; compounded doesn't add or remove anything here.
- **Anyone you share an archive with**, on the contents of that archive.

That's the full list.

## Rotating / wiping

To reset compounded completely:

```bash
rm -rf ~/.claude/compounded
```

compounded rebuilds the empty layout on the next session start.

To reset only the event log:

```bash
sqlite3 ~/.claude/compounded/trust.db "DELETE FROM events;"
```

To reset only USER.md:

```bash
> ~/.claude/compounded/USER.md
```

To reset all skills back to empty (keeping USER.md):

```bash
rm -rf ~/.claude/compounded/skills
sqlite3 ~/.claude/compounded/trust.db "DELETE FROM skills; DELETE FROM events;"
```

## License

Privacy posture aside, compounded is MIT-licensed, which means you can audit the code, fork it, modify it, and self-host it however you want. The full source is at `~/.claude/plugins/cache/compounded/` after install.
