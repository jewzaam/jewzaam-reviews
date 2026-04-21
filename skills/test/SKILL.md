---
name: test
description: Permission canary — exercises every !-injection pattern used by real skills to verify allowed-tools coverage
allowed-tools:
  # A: !-injection coverage (load-bearing — without these, pre-fetch breaks)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/**)
  # B: Main-agent tools
  - Bash(git remote -v)
  - Bash(pwd)
  # C: Skill file access
  - Read(${CLAUDE_SKILL_DIR}/**)
  - Glob(${CLAUDE_SKILL_DIR}/**)
  - Grep(${CLAUDE_SKILL_DIR}/**)
---

# Permission Canary

This skill exercises every `!` injection pattern used by the real producer skills. If any section below shows an error instead of output, the `allowed-tools` pattern is broken.

## Auto-injected env vars

CLAUDE_PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT}
CLAUDE_PLUGIN_DATA=${CLAUDE_PLUGIN_DATA}
CLAUDE_SKILL_DIR=${CLAUDE_SKILL_DIR}

## Plugin Home (print-plugin-home.sh)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-plugin-home.sh ${CLAUDE_PLUGIN_ROOT}`

## Project Root (pwd)

!`pwd`

## Remotes (git remote -v)

!`git remote -v || true`

## Workspace Bootstrap (bootstrap-tmp.sh)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh .tmp-test`

## Handoff Contract (print-handoff-contract.sh)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-handoff-contract.sh`

# Instructions

Print every section heading above and its injected output.  Add a specific output for the plugin and marketplace versions derrived from the auto-injected env var paths. If any section shows "Shell command permission check failed" or similar error, report which section failed and the exact error message. Otherwise confirm all injections succeeded.
