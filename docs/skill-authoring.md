# Skill Authoring Guide

This document is for **users who want to hand-author a skill for compounded**, not for the agent. The agent has its own guidance in [`skills/compounded-author/SKILL.md`](../skills/compounded-author/SKILL.md).

If the agent proposes a skill on its own, compounded handles the lifecycle automatically. This guide is for the case where you've identified a procedure you want compounded to know about and want to inject it into the trust ladder yourself.

## When to hand-author

Most of the time, **don't**. Let the agent propose skills naturally as it discovers procedures during real work. Hand-authoring is appropriate when:

- The procedure is something you do constantly and want available immediately
- You want fine-grained control over the wording
- The agent isn't proposing it on its own and you've waited

## The shape of a SKILL.md

```markdown
---
name: kebab-case-name
description: One sentence describing when this skill should activate, written so a verifier can decide if a future task matches.
---

# Title Case Name

## When to use

- Specific bullet describing trigger condition 1
- Specific bullet describing trigger condition 2

## Inputs

- `<input-name>`: a short description of what this input is and how to find it

## Procedure

1. Step one (a single concrete action with explicit file paths in `<placeholders>`)
2. Step two
3. ...

## Pitfalls

- Specific failure mode → how to recognize/fix it

## Verification

- A concrete check that says "this worked" or "this didn't"
```

## Frontmatter rules

- `name` must be kebab-case: `^[a-z][a-z0-9-]{0,63}$`
- `description` must be a single sentence written from the agent's perspective. The verifier reads this when deciding match against a future task.
- No other fields are required, but you can add any keys you want — they'll be preserved.

## Writing a good `description`

The description is read by Claude when deciding whether to load this skill on a given task. Make it concrete enough that a future Claude session knows when to reach for it.

**Good:**

```yaml
description: Migrate an Express.js HTTP server to Fastify, preserving routes and middleware semantics. Use when package.json has Express as a dependency and the user asks to convert or migrate.
```

**Bad:**

```yaml
description: Helps with backend code. Use whenever you're working on a server.
```

The first version names a specific scenario the verifier can match. The second is too broad to trigger usefully and too vague to verify.

## Writing good steps

Each step should be **a single concrete action**. Numbered. With explicit placeholders for inputs.

**Good:**

```
1. Run `grep -rn "from express" <project-root>/src/ --include="*.ts"` to find all Express imports.
2. For each file in the result, replace `import express from "express"` with `import Fastify from "fastify"`.
3. Update the app initialization: `const app = express()` becomes `const app = Fastify()`.
```

**Bad:**

```
1. Look at the Express imports.
2. Replace them.
3. Update everything that needs updating.
```

The first version can be replayed step-by-step. The second is wishful thinking.

## Adding a hand-authored skill

You have two options.

### Option 1: through compounded (recommended)

Use the `skill_propose.py` script directly:

```bash
python3 ~/.claude/plugins/cache/compounded/scripts/skill_propose.py \
  --name "express-to-fastify" \
  --verification-hint "next time the user asks to migrate an Express app to Fastify, this procedure should reproduce successfully" \
  < my-skill.md
```

It enters `.proposed/` and goes through the normal verification flow on the next applicable task.

### Option 2: jump to verified manually

If you want to skip verification and put the skill straight into `.verified/`:

```bash
# Propose first
python3 ~/.claude/plugins/cache/compounded/scripts/skill_propose.py \
  --name "express-to-fastify" \
  --verification-hint "next time the user asks to migrate an Express app to Fastify, this procedure should reproduce successfully" \
  < my-skill.md

# Then promote
/compounded:trust express-to-fastify --to verified
```

You can also promote straight to `.trusted` or `.autonomous` if you've used the procedure manually for a long time and trust it. **Use this sparingly.** The trust gradient's value is that it's empirical; manual overrides defeat the purpose if used reflexively.

## Verification hints

The hint is the criterion the verifier uses to decide if a future task matches. Same rules as for the agent (see [skills/compounded-author/SKILL.md](../skills/compounded-author/SKILL.md) for the full discussion):

- Concrete enough to match: name the trigger condition, the input shape
- Not so narrow it never triggers: avoid hardcoded paths or session-specific values
- Not so broad it triggers on everything: avoid "any time the user does anything"

A good hint is roughly the same length as a tweet and contains 3-6 distinctive content words.

## Iterating

Skills aren't write-once. If you author a skill and the verifier rejects it (or the agent corrects you when using it), the rejection reason is logged. Read it, fix the SKILL.md, and re-propose:

```bash
# Get the rejection reason
cat ~/.claude/compounded/skills/.rejected/express-to-fastify/.rejection_reason

# Fix the issues, then re-propose with --force to overwrite
python3 ~/.claude/plugins/cache/compounded/scripts/skill_propose.py \
  --name "express-to-fastify" --force \
  --verification-hint "..." \
  < fixed-skill.md
```

## Patterns that work

After a few months of dogfooding, these patterns produce skills that pass verification reliably:

- **Migration skills**: "convert X to Y" with concrete before/after examples
- **Audit skills**: "find all instances of pattern P in the codebase and report them"
- **Refactor skills**: "transform pattern A into pattern B everywhere it appears, with appropriate test updates"
- **Setup skills**: "scaffold a new <thing> with our team's conventions"

## Patterns that don't work

These tend to fail verification or get demoted quickly:

- **"Smart" skills** that rely on judgment ("decide if the user wants X or Y") — judgment doesn't replay reliably
- **One-shot skills** with hardcoded values from a specific session
- **Catch-all skills** with descriptions like "general code improvements"
- **Notes pretending to be skills** ("remember that we use TypeScript") — these belong in MEMORY.md or USER.md
