# compounded vs. native AutoMemory + AutoDream

[AutoMemory](https://docs.claude.com) and [AutoDream](https://docs.claude.com) are Anthropic's native memory features for Claude Code, available in v2.1.59+. They are excellent. They occupy the *project memory + cleanup* layer.

compounded occupies a different layer. This doc is the explicit comparison.

## What each one does

| Concern | AutoMemory | AutoDream | compounded |
|---|---|---|---|
| Per-project notes | ✅ writes them | ❌ | ❌ |
| Note consolidation | ❌ | ✅ runs between sessions | ❌ |
| Cross-project preferences | ❌ | ❌ | ✅ USER.md |
| Skill verification | ❌ | ❌ | ✅ replay-based |
| Earned autonomy | ❌ | ❌ | ✅ trust gradient |
| Portable archive | ❌ | ❌ | ✅ .tar.gz export |

## Why use them together

You want all of this. They don't conflict.

- **AutoMemory** captures project-specific facts as the agent learns them. No effort from you.
- **AutoDream** keeps that captured pile from rotting. No effort from you.
- **compounded USER.md** holds your cross-project preferences. You write it.
- **compounded skills** earn autonomy as they prove themselves. The agent proposes, the verifier judges, the gradient promotes.

These layers compound. The end-state is an agent that knows your projects (AutoMemory), keeps that knowledge clean (AutoDream), knows you (USER.md), and has a portfolio of trusted procedures with a clear audit trail (the trust ladder).

## What if Anthropic ships verified skills natively?

It's likely they will, eventually. Anthropic shipped AutoMemory in v2.1.59 and AutoDream within two months. The verification primitive is the obvious next step.

If they do:

- **Best case:** compounded becomes the cross-tool wrapper. The trust gradient (the UX primitive) is what users will continue to want; the verification engine underneath can be ours, or theirs, or both.
- **Realistic case:** Anthropic ships their own version, compounded becomes a slightly redundant layer for those features specifically, but the cross-project USER.md and the portable archive remain unique.
- **Worst case:** Anthropic ships a strictly better version of everything compounded does. We retire to PHILOSOPHY.md as a doc, and users move on.

This doesn't bother us. The point of compounded was always to demonstrate that the verification + earned-autonomy pattern was worth shipping. If Anthropic adopting it is the outcome, that's a good outcome.

## Where compounded explicitly does NOT compete

- We do not write to `~/.claude/projects/<project>/memory/MEMORY.md`. AutoMemory's path. Don't touch.
- We do not run a memory consolidation pass. AutoDream's job. The compounded USER.md is bounded at 1500 chars and you maintain it manually.
- We do not extract notes from sessions. AutoMemory captures these. We stay above the note layer.

If you find yourself wondering whether compounded and AutoMemory will fight, they won't. They write to different paths and operate at different lifecycle phases.
