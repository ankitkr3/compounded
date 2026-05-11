#!/usr/bin/env bash
# Demo script for recording the compounded lifecycle GIF for the README.
#
# Recommended capture: asciinema rec demo.cast, then convert to GIF
# with agg or asciinema-gif-generator.
#
#   asciinema rec --title "compounded lifecycle" demo.cast
#   <run this script>
#   <Ctrl+D to stop recording>
#   agg --theme monokai --speed 1.5 demo.cast demo.gif
#
# The script uses sleeps to make the demo readable. Total duration ~30s.

set -e
export COMPOUNDED_HOME=$(mktemp -d -t compounded-demo-XXXX)
SCRIPTS="${SCRIPTS:-$(cd "$(dirname "$0")/../scripts" && pwd)}"

cls() { printf "\033[2J\033[H"; }
say() { printf "\033[36m# %s\033[0m\n" "$1"; sleep 1.2; }
type_cmd() {
  printf "\033[33m$\033[0m "
  for ((i=0; i<${#1}; i++)); do
    printf "%s" "${1:$i:1}"
    sleep 0.02
  done
  printf "\n"
  sleep 0.4
}

cls
say "compounded turns your agent into a trainable employee."
say "Skills earn autonomy through demonstrated reliability."
sleep 1

say "Step 1: agent proposes a skill after a successful task"
type_cmd "python3 \$COMPOUNDED/skill_propose.py --name fastify-migration ..."
python3 "$SCRIPTS/skill_propose.py" \
  --name "fastify-migration" \
  --verification-hint "next time the user migrates an Express server to Fastify this should reproduce" <<'EOF'
---
name: fastify-migration
description: Migrate Express.js server to Fastify, preserving routes and middleware.
---
# Fastify Migration
## When to use
- package.json has Express
- User asks to migrate to Fastify
## Procedure
1. Update dependencies
2. Convert app initialization
3. Convert routes
4. Run tests
## Verification
- Tests pass
EOF
sleep 1.5

say "Step 2: status shows it pending verification"
type_cmd "/compounded:status"
python3 "$SCRIPTS/status.py" | head -10
sleep 2

say "Step 3: verifier subagent passes it on a similar task"
type_cmd "/compounded:verify fastify-migration"
python3 "$SCRIPTS/finalize_verification.py" \
  --name fastify-migration \
  --verdict-json '{"verdict":"PASS","reason_code":"ok","reason_text":"replays correctly","step_or_field":null,"confidence":0.9}'
sleep 1.5

say "Step 4: trust ladder shows it at .verified"
type_cmd "/compounded:trust-status"
python3 "$SCRIPTS/status.py" --trust-ladder | head -12
sleep 2.5

say "Step 5: 3 clean uses → graduates to .trusted"
for i in 1 2 3; do
  type_cmd "(used: clean run #$i)"
  python3 "$SCRIPTS/trust_ladder.py" --record-use fastify-migration > /dev/null
  sleep 0.4
done
python3 "$SCRIPTS/status.py" --trust-ladder | head -10
sleep 2

say "Step 6: 7 more uses → graduates to .autonomous"
for i in 1 2 3 4 5 6 7; do
  python3 "$SCRIPTS/trust_ladder.py" --record-use fastify-migration > /dev/null
done
python3 "$SCRIPTS/status.py" --trust-ladder | head -10
sleep 2.5

say "Step 7: one correction demotes it back to .trusted"
type_cmd "(user corrected the skill's output)"
python3 "$SCRIPTS/trust_ladder.py" --record-use fastify-migration --corrected > /dev/null
python3 "$SCRIPTS/status.py" --trust-ladder | head -10
sleep 2.5

say "That's compounded. Skills earn autonomy. Corrections cost it."
say "No daemon. No cloud. Just earned trust."
sleep 2

# Cleanup
rm -rf "$COMPOUNDED_HOME"
