# compounded vs. superpowers

[superpowers](https://github.com/obra/superpowers) by Jesse Vincent ships TDD/brainstorm/plan methodology for Claude Code. ~176K stars. Different layer, complementary purpose.

## Different layers

superpowers shapes **how Claude works**. It bundles skills that train the agent into a senior engineer: pressure-tested skill compliance, brainstorm-before-code, RED/GREEN TDD, code review subagents, plan-first workflows.

compounded shapes **what Claude remembers**. The trust gradient, USER.md, verified skills with an audit trail.

You want both. They don't overlap.

## Concrete composition

Imagine a real workflow:

1. You ask Claude to add a feature.
2. **superpowers' brainstorm skill** kicks in. Claude asks clarifying questions before any code.
3. **superpowers' plan skill** writes a plan with explicit success criteria.
4. **superpowers' TDD skill** runs RED/GREEN. Failing test → implementation → green test.
5. The work completes. The procedure was non-trivial.
6. **compounded' compounded-author skill** decides whether to propose a new skill capturing the methodology applied.
7. **compounded' Stop hook** dispatches the verifier subagent on the next similar task.
8. Three clean uses later, that skill is `.trusted`. Ten uses later, `.autonomous`.

superpowers built the muscle. compounded remembered the move.

## What superpowers does that compounded doesn't

- A bundled methodology for software engineering specifically (TDD, brainstorm, plan, code review)
- Pressure-test scenarios that ensure the agent actually uses the skills under stress
- A fork-and-PR workflow for sharing skills back to the community
- Memory ideas (the `remembering-conversations` skill is partially-built in their repo, per Jesse's launch post)

## What compounded does that superpowers doesn't

- A formal trust gradient with empirically-driven promotions and demotions
- A user-global USER.md for cross-project preferences
- Verified-by-replay skill graduation
- Portable archive (`/compounded:export`)
- A rejection log with specific machine-readable reasons

## Why we don't try to merge

Two reasons:

1. **Different shapes.** superpowers is a methodology bundle (skills as habits). compounded is an infrastructure primitive (skills as graduating procedures). Merging would dilute both.
2. **Different rhythms.** superpowers ships skills that codify *how* to think about a class of problem. compounded ships infrastructure that lets *any* skill earn autonomy through use. They're orthogonal.

The clean composition is: install both, use both, don't try to make one of them subsume the other.

## Lessons we took from superpowers' launch

Jesse's [launch post](https://blog.fsck.com/2025/10/09/superpowers/) was the most influential piece of writing in the Claude Code plugin ecosystem to date. We borrowed:

- **Be opinionated.** superpowers tells you to use TDD. Period. compounded tells you skills must earn autonomy. Period. Vague tools don't get evangelized.
- **Storytelling matters.** "I discovered Claude was quizzing the subagents like a gameshow" was the most-quoted line from the launch. Demos that show the system catching its own failures are more memorable than feature lists.
- **Cialdini-style pressure on the agent works.** superpowers uses scarcity, authority, and commitment to make the agent actually use the installed skills. compounded's `using-compounded` SKILL.md uses similar techniques (explicit "you have skills" framing, concrete state names).

## When to start with one and add the other

- **Start with superpowers** if you're early in your Claude Code journey and want better workflow habits. You'll add compounded later when you start wanting to capture and graduate the procedures you use.
- **Start with compounded** if you already have good engineering habits and want infrastructure for cross-project memory and skill verification. You'll add superpowers later when you decide your team needs shared methodology.

There is no wrong order. Both are MIT-licensed. Both are ~few minutes to install.
