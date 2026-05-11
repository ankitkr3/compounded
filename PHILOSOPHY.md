# Philosophy

> Why does compounded exist when AutoMemory and AutoDream and skill-creator and superpowers are already a thing?

This is a fair question, and the honest answer is the heart of the project.

## The complete agent learning loop

After several months of using Claude Code on real production work, you start to notice that an agent's improvement over time has four distinct layers:

1. **Capture** — the agent takes notes during sessions about what it learned.
2. **Consolidate** — those notes get cleaned up so they don't bloat or contradict themselves.
3. **Verify** — what was learned is actually tested against fresh problems.
4. **Earn autonomy** — verified skills graduate to higher levels of trust based on demonstrated reliability.

Anthropic and the community have built excellent tools for the first two layers:

- **AutoMemory** writes per-project notes automatically.
- **AutoDream** consolidates them between sessions, pruning stale entries and merging duplicates.
- **claude-mem** captures observations more aggressively, with a daemon and a vector index.
- **skill-creator** lets you eval-test a hand-authored skill against test cases you write.

These are all good. None of them ships layers 3 and 4.

That's the gap. compounded is what fills it.

## The trainable-employee metaphor

Jason Crawford, on the recursive self-improvement wave that hit GitHub in early 2026:

> "Having Claude Code write its own skills is not far from having a highly trainable employee: you give it some feedback and it learns."

The metaphor matters because it implies a question: **how do you train a junior?**

You don't read them a manual and then immediately let them ship to production. You give them a defined task with clear success criteria. They do it under supervision. If it goes well, you give them similar tasks. If those go well, you reduce supervision. Eventually, you trust them to do certain kinds of work without your involvement.

That's a gradient. It isn't binary. And the transitions through it are governed by demonstrated reliability, not by the junior's own opinion of themselves.

compounded is a gradient for agents.

- A skill the agent saved is a hypothesis. (`.proposed`)
- A skill that worked once on a fresh task is a credible procedure. (`.verified`)
- A skill that worked three times without correction is a habit. (`.trusted`)
- A skill that worked ten times with a clean recent run is part of the agent's standard repertoire. (`.autonomous`)

One correction sends a skill back a step, just like one bad PR can shake your trust in a junior. Three corrections in a month sends it back to square one — start over, prove it again.

## Why "earned" and not "granted"

A counterargument: the user could just promote skills manually. Inspect them, decide they're good, mark them trusted. Why automate it?

Because **promotion based on inspection alone is fragile**. The agent shows you a skill. You read it. It looks reasonable. You promote it. Three weeks later you discover it has a subtle failure mode you didn't catch. Or worse: you forgot to inspect, promoted on instinct, and the failure mode hits you in production.

Earned promotion makes the trust gradient an *empirical* signal rather than an *opinion* one. The skill ran, it produced an outcome, you didn't correct it. Repeat enough times and the skill earns its position. The signal is reliable because it's measured against real work.

This also matters for the inverse case: the **rejection log**. When a verifier subagent rejects a skill, it logs a specific reason — `step-would-have-failed`, `not-abstracted`, `vague-procedure`. Those reasons are visible in `~/.claude/compounded/skills/.rejected/`. You can read them. You can argue with them. The trust system is auditable.

## Why no daemon

There is a real tradeoff here. claude-mem runs a Bun worker that observes everything, summarizes aggressively, and exposes a web UI on port 37777. That's genuinely powerful for some workflows.

compounded chose the other side of the tradeoff for these reasons:

1. **Setup friction.** A daemon means another service to install, run, and remember to restart. Plugins that work after `/plugin install` and a Claude Code restart get used; ones that need additional setup get abandoned.
2. **Surface area.** A daemon listens on a port, holds a process, and represents a vector for things to go wrong. Hook scripts that run for under a second and exit do not.
3. **Privacy.** A daemon that observes everything is harder to reason about than scripts that fire on specific events with specific inputs. compounded can tell you exactly when it runs and what it touches.
4. **Composability.** No daemon means no port conflicts. You can run compounded and claude-mem and AutoMemory and AutoDream all at the same time without operational concerns. They each do their thing in different windows of the lifecycle.

The cost of "no daemon" is that compounded cannot capture session-level observations the way claude-mem does. We accept that. claude-mem exists. Use both if you want both.

## Why no cloud

Same logic, sharper edge.

Cloud means surrendering data, accepting a ToS, depending on someone else's uptime, and trusting their security practices. For a memory layer that contains your professional preferences and learned skills — the most personal thing you put into an agent — these are non-trivial costs.

compounded's data lives at `~/.claude/compounded/`. It's plain text and SQLite. You can `cat` your USER.md. You can grep your skills. You can `tar` the whole thing up and move it. If compounded disappears tomorrow, your data is still on your disk in a format you can read.

The portability story (`/compounded:export`, `/compounded:import`) gives you cross-machine without cloud. That tradeoff feels right at this layer.

## Why bound USER.md at 1500 characters

Two reasons.

The functional reason: the file is loaded into every session. A 200KB USER.md would burn context budget catastrophically. The bound keeps it cheap.

The deeper reason: **forced consolidation is good design**. When you have unlimited space, you accumulate. Every preference, every fact, every quirk. After a year you have a 50KB pile of stuff, half of which is contradicted by the other half, all of which is impossible to scan.

A 1500-char limit forces you to ask: which of these matters? It's a Twitter-scale interface for your own preferences. The constraint is the feature.

(For project-specific notes, AutoMemory's MEMORY.md is the right home. It's per-project and bounds itself differently. compounded doesn't compete there.)

## The asymmetric error model

When a verifier decides on a proposed skill, two errors are possible:

- **False positive**: a bad skill graduates to `.verified`.
- **False negative**: a good skill gets rejected.

These are not equal. A false positive means the next user-correction event demotes the skill back. The cost is one bad invocation. A false negative means the user loses a skill they would have benefited from. The cost is invisible — they never know what they missed.

So the verifier is calibrated to lean inclusive. PASS-low-confidence is a valid verdict. The trust gradient downstream handles quality control through real-world demotion. This is the same tradeoff a thoughtful manager makes: trust by default, demote on evidence, rather than gate-keep up front.

## Why this matters even if you don't use compounded

There is a wider point about how AI tools relate to humans.

The default mode of most AI products is "the system has full authority by default; you're hoping it doesn't make a mistake." compounded's mode is "the system has zero authority by default; it earns scope as it proves itself."

The first mode optimizes for impressive demos. The second optimizes for long-term reliability and human dignity. We think the second is the better long-term posture for any tool that is going to make decisions on a person's behalf.

compounded is one small instance of that pattern. The pattern is broader than compounded.

## What we are not claiming

- compounded does not solve recursive self-improvement. It's a trust gradient over agent-authored procedures. The agent does not rewrite its own meta-learning algorithm.
- compounded does not make Claude better at coding. It makes Claude better at *you*.
- compounded is not a memory replacement. AutoMemory, MEMORY.md, and your CLAUDE.md still do their jobs. compounded adds the user-global layer and the verification + earned-autonomy layer on top.
- compounded is not future-proof against Anthropic shipping the same primitives natively. If they do, our value becomes the cross-tool wrapper / composition layer / quality benchmark, not the source.

## What we are claiming

That memory which compounds is more valuable than memory that accumulates.
That a skill which has been verified is more valuable than a skill which has been recalled.
That authority earned through demonstrated reliability is more valuable than authority granted by default.
That a small tool which does one thing right is more valuable than a hundred tools that do everything ambivalently.

If those four sentences make sense to you, compounded may be the tool you wanted.

If they don't, you should probably use something else. There is no shortage of options.
