---
description: Manually run the verifier subagent against a proposed skill. Pass the skill name as $ARGUMENTS. Use this when you want to verify a proposal immediately rather than waiting for an applicable task to come up naturally.
---

Manually verify a proposed skill named **$ARGUMENTS**.

Steps:

1. Confirm the skill exists in `.proposed/`:

   !`ls ~/.claude/compounded/skills/.proposed/$ARGUMENTS/SKILL.md 2>/dev/null && echo "found" || echo "not found"`

2. If it exists, read the proposed SKILL.md and the verification hint:

   - SKILL.md: `~/.claude/compounded/skills/.proposed/$ARGUMENTS/SKILL.md`
   - Hint: `~/.claude/compounded/skills/.proposed/$ARGUMENTS/.verification_hint`

3. Use the **skill-verifier** subagent to evaluate the proposal. Pass it the SKILL.md content, the hint, a summary of any recent task that the user identifies as relevant, and the list of existing active skills (`.verified/`, `.trusted/`, `.autonomous/`).

4. The subagent returns a JSON verdict. Apply it via:

   !`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/finalize_verification.py --name $ARGUMENTS --verdict-json '<paste-json-here>'`

5. Report the result to the user (graduated to `.verified` or rejected with reason).

If $ARGUMENTS is empty, ask the user which proposed skill to verify, then list the available proposals via `ls ~/.claude/compounded/skills/.proposed/`.
