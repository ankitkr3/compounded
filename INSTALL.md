# Installation

## Requirements

- **Claude Code 2.0.13 or later** (for plugin system support)
- **Python 3.9+** (the scripts use only the standard library)
- **macOS, Linux, or WSL2** (native Windows is untested in v1.0)

Check your Claude Code version:

```bash
claude --version
```

Check Python:

```bash
python3 --version
```

## Standard install (via marketplace)

In Claude Code:

```
/plugin marketplace add ankitkr3/compounded-marketplace
/plugin install compounded@compounded-marketplace
```

Restart Claude Code:

```bash
# In your terminal
claude
```

When the new session starts, you should see something like this in the session-start context:

```
compounded: USER.md 0/1500 chars · skills: 0 verified, 0 trusted, 0 autonomous, 0 pending
(USER.md is empty. Add user-global preferences via /compounded:status or by editing ~/.claude/compounded/USER.md.)
```

That's it. compounded is installed and active.

## Permission prompts (expected, easy to silence)

**Hooks fire silently — no permission prompt for any of compounded's automatic behavior.** SessionStart memory injection, the Stop hooks (verification + auto-propose), and the SessionEnd cascade all run on lifecycle events without asking.

**Slash commands prompt for approval the first time you run each one.** The first time you run, say, `/compounded:status`, Claude Code shows:

```
Shell command permission check failed for pattern
"!python3 ~/.claude/plugins/cache/compounded-marketplace/compounded/X.Y.Z/scripts/status.py":
This command requires approval.
```

This is normal Claude Code behavior for any plugin that invokes shell scripts. Three ways to handle it:

| Choice | What happens |
|---|---|
| **Click "always allow"** in the prompt | That specific command runs silently from then on. Recommended for casual use — just allow each command the first time it comes up. |
| **Click "allow once"** | Re-prompts every time the same command runs. Annoying. Don't pick this one. |
| **Allowlist all compounded commands up front** (see below) | One-time setup; no prompts ever again for any compounded command. |

### Allowlist all compounded commands (optional, one-time)

Add this to `~/.claude/settings.json` under `permissions.allow`:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 ~/.claude/plugins/cache/compounded-marketplace/compounded/**:*)"
    ]
  }
}
```

This single pattern covers all 9 slash commands plus any future ones. Save the file and reload Claude Code.

> **Why this is safe:** the pattern only allowlists Python scripts inside the compounded plugin's installed location. Anthropic's plugin install flow already required you to trust the source repo; this just removes the per-command prompt for scripts you already trust.

## Verify installation

In Claude Code:

```
/compounded:status
```

You should see:

```
=== compounded status ===

USER.md: 0/1500 chars  (/Users/you/.claude/compounded/USER.md)

skills by tier:
  .autonomous :   0
  .trusted    :   0
  .verified   :   0
  .proposed   :   0  (awaiting verification)
  .rejected   :   0
```

## Manual install (without marketplace)

If you'd prefer to install directly from the repo without going through a marketplace:

```bash
mkdir -p ~/.claude/plugins/cache
git clone https://github.com/ankitkr3/compounded ~/.claude/plugins/cache/compounded
```

Then enable it via Claude Code's `/plugin` UI, or add to `~/.claude/settings.json`:

```json
{
  "plugins": {
    "enabled": ["compounded"]
  }
}
```

## First use

1. **Add a couple of preferences to USER.md.** Open `~/.claude/compounded/USER.md` in any editor and add a few lines:

   ```
   User prefers tabs over spaces in Python.
   User is in the Asia/Kolkata timezone.
   User runs Linux on Ubuntu 24.04.
   ```

   Keep it under 1500 characters. The file is bounded by design — it forces consolidation.

2. **Start a new Claude Code session.** USER.md is now in your session context. Ask Claude:

   ```
   What do you know about my preferences?
   ```

   Claude should reference what you wrote.

3. **Wait for the agent to propose its first skill.** When you finish a task that involved multiple non-trivial tool calls, the agent (following the `compounded-author` skill) may propose to save the procedure. You'll see a message like:

   ```
   I've proposed a skill called `<name>`. It will be verified the next time
   a similar task comes up. If verification passes, it graduates to .verified
   and becomes available.
   ```

4. **Run `/compounded:status` periodically** to see what's pending verification, what's been promoted, and what's been rejected.

## Configuration

Edit `~/.claude/compounded/config.json`:

```json
{
  "memory": {
    "user_char_limit": 1500
  },
  "skills": {
    "proposal_ttl_days": 30,
    "verifier_model": "claude-haiku-4-5-20251001"
  },
  "privacy": {
    "log_token_usage": false
  }
}
```

| Field | Default | What it does |
|---|---|---|
| `memory.user_char_limit` | 1500 | Max chars before USER.md gets truncated on injection |
| `skills.proposal_ttl_days` | 30 | Auto-reject proposals not verified within this window |
| `skills.verifier_model` | `claude-haiku-4-5-20251001` | Model used by the skill-verifier subagent |
| `privacy.log_token_usage` | false | Set true to log per-verification token counts |

## Storage location

compounded uses `~/.claude/compounded/` by default. To change this, set the `COMPOUNDED_HOME` environment variable before starting Claude Code:

```bash
export COMPOUNDED_HOME=/path/to/your/compounded
```

Useful for testing, sandboxes, or running multiple compounded profiles.

## Uninstalling

```
/plugin uninstall compounded
```

This removes the plugin but **leaves your data intact** at `~/.claude/compounded/`. To delete that too:

```bash
rm -rf ~/.claude/compounded
```

Want to keep your skills and USER.md in case you reinstall? Run `/compounded:export ~/Desktop/compounded-backup.tar.gz` first.

## Troubleshooting

**`/compounded:status` returns "command not found"**

The plugin didn't install. Check:

```
/plugin list
```

If `compounded` isn't there, reinstall:

```
/plugin marketplace update compounded-marketplace
/plugin install compounded@compounded-marketplace
```

**SessionStart hook does nothing**

Check the hook is firing:

```bash
cat ~/.claude/logs/hooks/*.log | tail -20
```

If the hook isn't running, your Claude Code version may not support plugins. Update to 2.0.13+.

**`python3: command not found`**

The scripts use `python3`. On systems where Python is installed as `python`, create a symlink:

```bash
sudo ln -s $(which python) /usr/local/bin/python3
```

Or run Claude Code with `python` aliased to `python3` in your shell.

**Verifier subagent isn't being dispatched**

The verifier only fires when a `.proposed/` skill's hint keyword-overlaps with the task that just finished. If you've proposed a skill and it's been weeks with no verification, run it manually:

```
/compounded:verify <skill-name>
```

## Getting help

- **Issues:** [github.com/ankitkr3/compounded/issues](https://github.com/ankitkr3/compounded/issues)
- **Discussions:** [github.com/ankitkr3/compounded/discussions](https://github.com/ankitkr3/compounded/discussions)
- **Manifesto / philosophy:** [MANIFESTO.md](MANIFESTO.md), [PHILOSOPHY.md](PHILOSOPHY.md)
