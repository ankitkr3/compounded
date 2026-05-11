---
description: Import a compounded archive (.tar.gz produced by `/compounded:export`). Pass the input path as $ARGUMENTS. Add `--overwrite` to replace any colliding local skills.
---

Run the archive import with the user-supplied arguments:

!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/archive.py import --input $ARGUMENTS`

If the user did not supply a path, ask them which archive to import before retrying.
