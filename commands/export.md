---
description: Export compounded state (USER.md + verified skills) to a portable .tar.gz archive. Pass the output path as $ARGUMENTS, e.g. `/compounded:export ~/Desktop/compounded.tar.gz`. Add `--include-pending` to also include .proposed/ and .rejected/.
---

Run the archive export with the user-supplied arguments:

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/archive.py export --output $ARGUMENTS`

If the user did not supply a path, ask them where to write the archive before retrying.
