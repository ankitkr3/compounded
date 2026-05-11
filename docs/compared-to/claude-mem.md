# compounded vs. claude-mem

[claude-mem](https://github.com/thedotmack/claude-mem) is a popular Claude Code memory plugin. Built on a Bun worker daemon, observation-heavy, web UI on port 37777, vector index, multi-IDE support. ~72K stars at time of writing.

This doc explains the design philosophy difference and when to choose each.

## Different designs, same goal

Both tools want the same thing: an agent that gets better at the user's specific work over time. They make the opposite tradeoff on **how**.

| Dimension | claude-mem | compounded |
|---|---|---|
| Architecture | Daemon (Bun worker) | Hooks + scripts only |
| State capture | Aggressive observation of every action | Just the agent's intentional skill proposals |
| Storage | SQLite + vector embeddings | SQLite + plain text |
| Cleanup mechanism | Compression worker | Bounded files + skill graduation |
| Setup time | Worker setup, port config | Single `/plugin install` |
| Cross-IDE | Claude Code, OpenClaw, Codex, Gemini, etc. | Claude Code only |
| UI | Web viewer at localhost:37777 | CLI only |
| Memory model | Continuous capture + retrieval | Discrete skills with trust state |
| Vector search | Yes | No |

## When claude-mem is the right choice

- You want exhaustive observation capture. Every tool call, every file read, every decision.
- You're working across multiple AI tools (Codex, Gemini, OpenClaw) and want a unified memory layer.
- You want a web UI for exploring your accumulated context.
- You're comfortable running a daemon and managing its lifecycle.
- You want vector-based retrieval over your past sessions.

## When compounded is the right choice

- You want zero operational overhead. Install the plugin, restart Claude Code, done.
- You want skills you can read, audit, and trust — with a clear gradient from "untrusted" to "autonomous."
- You want cross-project preferences (USER.md) without per-IDE configuration.
- You're privacy-sensitive about background observation.
- You want every state change to be auditable and recoverable.

## Why not both?

You can run both simultaneously. They don't share state, don't share paths, don't compete for ports.

- claude-mem: `~/.claude-mem/`, port 37777
- compounded: `~/.claude/compounded/`, no port

The combination gives you claude-mem's observation richness *and* compounded's verification + trust gradient. We use this combination ourselves on real work.

The only practical concern: at session start, both will inject context. Together that's a few hundred more tokens than either alone. Still negligible against a 200K context window.

## What we learned from claude-mem

claude-mem was already at 70K stars when we started designing compounded. Studying their docs taught us several things we incorporated directly:

- **Modes are good.** claude-mem's `code`, `chill`, `investigation` modes for different workflows are a clean idea. We don't have them in v1.0 but they're on the v1.5 roadmap.
- **A web UI is sticky.** Their `localhost:37777` interface is one of the things power users specifically mention. We chose not to build one in v1, but we acknowledge the appeal.
- **Cross-IDE is valuable.** We chose Claude Code only for v1.0 because we wanted to ship; expanding is on the table.

claude-mem demonstrated that the memory niche is broad enough to support multiple plugins with different philosophies. We're grateful for the trail they blazed.

## A note on respect

If you're choosing between memory plugins and you read this doc as "compounded beats claude-mem," that's not the message. claude-mem is a serious project by serious people that has helped tens of thousands of developers. Different tradeoffs, different shapes.

Use what fits your workflow. Or use both.
