---
description: Pin a skill at its current trust state, preventing automatic demotion. Pass the skill name as $ARGUMENTS. Pinning is reversed by `/compounded:unpin`.
---

Pin the skill **$ARGUMENTS** at its current trust state:

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pin_skill.py pin $ARGUMENTS`

If $ARGUMENTS is empty, list active skills via `/compounded:trust-status` and ask which to pin.
