---
description: Manually promote a skill (skip the trust gradient). Usage `/compounded:trust <skill> --to verified|trusted|autonomous`. Use sparingly — manual overrides defeat the verification system.
---

Manually set the trust tier for the requested skill:

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pin_skill.py trust $ARGUMENTS`

The `$ARGUMENTS` should be of the form `<skill-name> --to <state>`, where `<state>` is `verified`, `trusted`, or `autonomous`. If the user did not supply both, prompt them for the missing piece before running.

Note: this bypasses the trust gradient. Reserved for cases where the user is certain a skill should be at a particular tier (e.g., promoting a hand-authored skill to verified, or recovering after a misverification).
