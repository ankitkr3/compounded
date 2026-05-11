---
name: compounded-author
description: Use this skill when you have just completed a non-trivial task (more than 3 tool calls, novel approach, recovery from a dead end, or a correction-driven solution) and are considering whether to save the procedure as a reusable skill via compounded. Also use when the user explicitly asks you to "save this as a skill", "remember how to do this", or similar.
---

# Authoring a Skill (compounded)

You have just finished a task. You are deciding whether to propose a new skill.

**Default to NOT proposing.** Skills you propose pollute the `.proposed/` queue, cost the user a verifier inference call on the next applicable task, and dilute the trust signal if they fail. Propose only when the procedure clears the bar in section 1.

## 1. The qualifying bar

Propose only when **all five** are true:

1. **More than 3 tool calls.** Trivial tasks do not become skills.
2. **A non-obvious step.** If a competent agent would do this without a skill, do not write one. Skills exist for things that are easy to get wrong.
3. **The procedure abstracted to inputs.** If your steps are tied to specific paths, file names, or values from this session, you are writing notes, not a skill. Notes belong in MEMORY.md or USER.md.
4. **You actually finished.** A skill that captures a half-solution is worse than no skill — it teaches the wrong thing.
5. **It is not redundant.** Search existing skills first via `/compounded:status`. If there is overlap, consider extending an existing skill (via the user) rather than authoring a new one.

If any of these fail, stop. Do not propose.

## 2. The shape of a good proposed SKILL.md

Use this exact shape. The verifier subagent reads this file later and replays it; ambiguity causes false rejections.

```markdown
---
name: <kebab-case-name>
description: <one sentence describing when this skill should activate, written so a verifier can decide if a future task matches>
---

# <Title Case Name>

## When to use

<2-3 bullet points describing the trigger conditions. Concrete, not abstract.>

## Inputs

<List of inputs the skill expects, in plain English. e.g.: "the path to a Node.js project", "a function name to refactor".>

## Procedure

<Numbered steps. Each step is a single concrete action. Use file paths in angle brackets like `<project-root>/package.json`. Avoid pronouns like "it" or "this" — be explicit about what you mean.>

1. ...
2. ...
3. ...

## Pitfalls

<Failure modes you encountered or anticipate. Each pitfall pairs a symptom with a fix.>

## Verification

<How a future invocation can confirm it worked. Concrete check: tests pass, file exists, value matches, etc.>
```

## 3. Calling skill_propose

Once you have the SKILL.md content, invoke the compounded proposal mechanism via the `Bash` tool:

```bash
python3 ~/.claude/plugins/cache/compounded/scripts/skill_propose.py \
  --name "<kebab-case-name>" \
  --verification-hint "<one-sentence description of when a future task qualifies for replay verification>"
```

When you run that command, write the SKILL.md content to stdin via a heredoc so it is captured exactly. Example invocation:

```bash
python3 ~/.claude/plugins/cache/compounded/scripts/skill_propose.py \
  --name "express-to-fastify" \
  --verification-hint "next time the user asks to migrate an Express server to Fastify, this procedure should reproduce successfully" <<'EOF'
---
name: express-to-fastify
description: Migrate an Express.js HTTP server to Fastify, preserving routes and middleware semantics.
---

# Express to Fastify Migration

## When to use

- The user asks to migrate or convert an Express app to Fastify
- The project has an Express dependency in package.json
- Routes are defined via `app.get`, `app.post`, etc.

[... rest of SKILL.md ...]
EOF
```

The script will:

1. Validate the frontmatter and structure
2. Run a security scan against the content (rejects prompt injection patterns)
3. Write to `~/.claude/compounded/skills/.proposed/<name>/SKILL.md`
4. Record a verification hint to the trust database
5. Return a one-line confirmation, or an error explaining why the proposal was rejected

## 4. The verification hint

The hint is critical. It is the criterion that the verifier subagent uses to decide whether a future task qualifies for replay.

**Good hints:**

- "next time the user asks to migrate an Express server to Fastify, this procedure should reproduce successfully"
- "next time the user asks to add a new resolver to this Apollo GraphQL schema, this procedure should produce the resolver, type definition, and test in one pass"
- "next time the user asks to convert a class component to a functional component with hooks, this procedure should preserve all state and side effects"

**Bad hints:**

- "use this for refactoring" (too vague — what kind of refactoring?)
- "any time the user asks for help" (matches every task; will trigger spurious verifications)
- "see procedure" (gives the verifier nothing to check against)

## 5. After proposing

After `skill_propose.py` returns success:

1. Tell the user briefly: "I've proposed a skill called `<name>`. It will be verified the next time a similar task comes up. If verification passes, it graduates to `.verified` and becomes available."
2. Do NOT load or use the proposed skill in this session. It is unverified.
3. Do NOT propose another related skill in the same session unless the procedures are genuinely orthogonal. Multiple proposals in one session usually indicate the procedure should have been one larger skill.

## 6. Pitfalls

- **Proposing notes as skills.** "Remember that user prefers tabs" is a note (USER.md). "How to convert tabs to spaces in this codebase" is a skill. The line: skills are *procedures*, notes are *facts*.
- **Hint too narrow.** "Next time the user runs `npm test` on this exact repo" — the verifier will never trigger because the next session is on a different repo.
- **Hint too broad.** "Next time the user does anything with TypeScript" — the verifier will trigger on every TS task and waste tokens on irrelevant verifications.
- **Forgetting to abstract.** If your SKILL.md says "edit `~/projects/myapp/src/server.ts` line 47", it cannot be replayed elsewhere. Use placeholders like `<server-file>` and explain how to find them.
- **Authoring during the same task you would test against.** The first verification must be a *fresh* applicable task, not a retrospective check on the task that produced the skill. The hook respects this.

## 7. What success looks like

A skill you propose today shows up in `.proposed/`. Days or weeks later, a similar task arrives, the verifier runs, the skill graduates to `.verified`, and now Claude can invoke it by name. After 3 successful uses, it auto-loads on relevant tasks. After 10, it runs without asking. **You are training your replacement, one verified skill at a time.**
