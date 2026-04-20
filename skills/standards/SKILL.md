---
name: standards
description: Audit a repository for conformance with the user's personal coding standards at ~/source/standards/. Spawns one agent per standards subdomain, reports applicability and gaps as a Findings-standards.json handoff consumable by /apply-review. Use when the user asks to check, audit, or validate a codebase against their standards library.
disable-model-invocation: true
allowed-tools:
  # A: !-injection coverage (load-bearing)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/**)
  # B: Main-agent tools (also covered by global settings)
  - Bash(git remote -v)
  - Bash(pwd)
---

# Standards Skill

## Purpose

Audit a repository against the user's personal standards library at `~/source/standards/`. For each standards subdomain (derived deterministically from the `## ` section headers of `~/source/standards/CLAUDE.md`) spawn a parallel agent that reads every standards file in its subdomain, decides whether each standard applies to this project, and — for applicable standards — reports gaps. Consolidate into a single review document, then validate with independent subagents. Output is consumable by `/apply-review`.

## Constraints

- **Script paths use `~`:** Use the **Plugin Home** path from the Pre-Fetch section (starts with `~`) when constructing Bash commands for plugin scripts. Do not use absolute `/home/...` paths. Do not use `&&` or `||` chaining — each script call must be a standalone Bash invocation.
- **Read-only analysis.** Never modify source code, tests, or config.
- **No program execution.** Never run the target project, install dependencies, or invoke language runtimes (`python`, `node`, `go run`, etc.).
- **No package management.** Never run `pip`, `npm`, `cargo`, etc.
- **User-owned repos only.** If the pre-fetch emits `NOT_APPLICABLE`, print the reason and stop — do not write any review files.
- **Output is three files** at the project root, always with the `-standards` slug:
  - `Findings-standards.json` — authoritative structured findings, validated against `${CLAUDE_PLUGIN_ROOT}/schemas/findings.schema.json` with `source: "standards"`. Consumed by `/apply-review`.
  - `Findings-standards.md` — human-readable actionable findings. **Rendered from the JSON — never hand-authored.**
  - `Findings-standards-supplementary.md` — per-subdomain detail, strengths, non-applicable standards. **Rendered from the JSON — never hand-authored.**
- **All three files are produced by `render-standards.py`.** The main agent writes an intermediate pre-render JSON; the script validates, then emits all three outputs atomically. If validation fails, no files are written — investigate and fix the pre-render JSON.
- **If review files already exist, overwrite them.**

## Pre-Fetch

### Plugin Home (auto-detected)

Plugin root with `~` prefix. Use this path in all Bash commands that invoke plugin scripts.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-plugin-home.sh ${CLAUDE_PLUGIN_ROOT}`

### Project Root (auto-detected)

Absolute path of the project root. The main agent MUST substitute this value for any `./.tmp-standards/...` path it passes to a dispatched sub-agent, so the sub-agent has an unambiguous absolute Write target and cannot drift to `/tmp/` or any other directory.

!`pwd`

### Remotes (auto-executed)

!`git remote -v || true`

### Applicability & Subdomain List (auto-executed)

Runs `scripts/applicability.sh`. Validates origin owner (`jewzaam` / `nmalik`) and `~/source/standards/CLAUDE.md` presence. On success emits one `SUBDOMAIN: <name>` line followed by `FILE: <absolute path>` lines for each standards file. On failure emits `NOT_APPLICABLE: <reason>`.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/standards/scripts/applicability.sh`

### Workspace Bootstrap (auto-executed)

Wipes and recreates `./.tmp-standards/` at the project root with a `.gitignore` of `*`. Each run starts from a clean slate.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh .tmp-standards`

### Shared Handoff Contract (auto-injected)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-handoff-contract.sh`

## Process

### 1. Handle Applicability

If the pre-fetch output begins with `NOT_APPLICABLE:`, print the full reason to the user and stop. Do not write any review files. Do not proceed to the agent dispatch.

Otherwise parse the subdomain blocks. Each `SUBDOMAIN:` line starts a new group; subsequent `FILE:` lines belong to it until the next `SUBDOMAIN:` line.

### 2. Determine Project Context

- Use Glob and Read to understand the project structure.
- Identify the language, framework, build system, and test framework from top-level files (`pyproject.toml`, `package.json`, `go.mod`, `Makefile`, etc.).
- Call `mcp__allowlist__get_allowed_permissions` once to discover pre-approved commands. Pass the list to every agent so they know what can run without prompting.
- **Template files are reference material, not prescriptive content.** Some standards files live in a `templates/` subdirectory (e.g. `~/source/standards/python/templates/Makefile`, `~/source/standards/python/templates/pyproject.toml`). For these, the subdomain agent must compare the project's equivalent file against the template's *structure and approach* — never line-for-line content. Applicability is whether the project uses the relevant language/tool, regardless of how closely its file resembles the template's wording. This mirrors the explicit guidance in the Agent Prompt Template below, and must be echoed here so agents receive it before they start reading.

### 3. Launch Subdomain Agents in Parallel

Launch one `Agent` call per subdomain from step 1, all in a single message using the Agent tool. Each agent:

- `model: "sonnet"`
- `subagent_type: "feature-dev:code-reviewer"` — structurally removes Bash/Write/Edit, enforcing read-only analysis
- Prompt built from the template below, parameterized with the subdomain name and its file list

Each agent produces, for every standards file in its subdomain, one of:

- `NOT_APPLICABLE` — with a one-line reason (e.g., "project is Go, not Python")
- `APPLICABLE` — with a structured list of gaps, each tagged with severity, confidence, `file:line`, description, why it matters, suggested fix

### 4. Consolidate Findings into Pre-Render JSON

After all subdomain agents complete, synthesize findings into a single pre-render JSON file at `./.tmp-standards/pre-render.json`. The workspace bootstrap pre-fetch already created the dir with its `.gitignore`.

**Deduplication rules:**
- When two agents flag the same `file:line + standard`, keep the finding from the subdomain whose standard is the better fit. Preserve the most specific reference and the most actionable fix.
- When agents disagree on severity, take the higher severity.

**Pre-render JSON shape:**

```json
{
  "project": {"name": "<project-name>"},
  "findings": [
    {
      "subdomain": "<subdomain>",
      "severity": "critical|important|suggestion",
      "title": "<short title, ≤120 chars>",
      "locations": [{"path": "<file>", "line": "<N>"}],
      "issue": "<what is wrong>",
      "why_it_matters": "<grounded in the standard>",
      "suggested_fix": "<recommended change>"
    }
  ],
  "supplementary": {
    "tldr": "<executive summary>",
    "applicability": [
      {"subdomain": "...", "standard": "...", "applies": true, "gap_count": 2}
    ],
    "not_applicable": [
      {"standard": "...", "reason": "..."}
    ],
    "strengths": ["<standard the project follows well>"],
    "subdomain_notes": {"<subdomain>": "<notes>"}
  }
}
```

Do **not** assign `id` or `content_hash` — the render script computes those. Do **not** compose the markdown — the script renders it.

### 5. Validate Review (pre-render)

For each severity tier (`Critical`, `Important`, `Suggestions`) that has **at least one finding**, spawn one validator (`model: "sonnet"`, `subagent_type: "feature-dev:code-reviewer"`) in parallel. **Skip validation entirely for any tier with zero findings** and note it in `supplementary.subdomain_notes` or as an entry in the shared `issues[]` array if relevant.

Each validator:
- Receives the subset of findings in its assigned tier from the pre-render JSON
- For every finding, reads the referenced source file at the referenced line
- Challenges: is the issue real, is the severity justified, is `file:line` accurate, is the cited standard actually violated
- Returns findings that survived, plus those to remove or downgrade with reasoning

After validators complete:
- Remove failed findings from the pre-render JSON
- Adjust severity for downgraded findings (the script will assign fresh IDs)
- Collect any operational problems (sub-agent errors, permission denials, missing standards files) into a separate `issues.json` file with entries matching the shared schema's `issue` shape

### 6. Render Outputs

Invoke the render script:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/standards/scripts/render-standards.py \
  --input ./.tmp-standards/pre-render.json \
  --issues ./.tmp-standards/issues.json \
  --out-dir <project root> \
  --project-name <project name>
```

Skill-specific renderer behavior (on top of the shared handoff contract):
- Assigns IDs per bucket: `C0..`, `I0..`, `S0..` (sorted deterministically by subdomain + location + title).
- Computes `content_hash` per finding.
- Writes three files: `Findings-standards.json`, `.md`, and `-supplementary.md` at `--out-dir`.

### 7. Present Summary

Print the `supplementary.tldr`, the applicability matrix row counts (`N/M standards applicable`), and the count of Critical + Important findings. Tell the user: "Run `/apply-review Findings-standards.json` to fix findings iteratively." — note the `.json` extension; apply-review consumes the JSON directly.

## Agent Prompt Template

Each subdomain agent receives a prompt structured as:

```
Audit the project at <project-root> for conformance with the "<subdomain>" standards.

Standards files to evaluate (read ALL of them using these absolute paths):
- <absolute path 1>
- <absolute path 2>
- ...

Project context:
- Language: <detected>
- Build system: <detected>
- Test framework: <detected>
- Allowed commands: <allowlist from mcp__allowlist__get_allowed_permissions>

METHODOLOGY — work in two phases:

Phase 1 — Per-standard applicability:
For EACH standards file above, read the file and decide whether the standard applies to
this project. A standard applies if the project uses the relevant language/tool/framework
OR if the standard is language-agnostic. Record the applicability decision with a one-line
reason. Treat files in `templates/` as reference material — check whether the project's
equivalent file resembles the template, not whether it matches line-for-line.

Phase 2 — Per-standard gap assessment:
For every standard you marked APPLICABLE in Phase 1, identify specific gaps between the
standard and the project. Cite file:line. Do not flag gaps for NOT_APPLICABLE standards.

Maximize parallel tool calls — issue all independent Read/Glob/Grep calls in the same message.
Do NOT run any commands. Do NOT modify any files. Read-only analysis only.

CONFIDENCE SCORING — self-score every gap:
- High (>80%): Clear violation with concrete evidence. Report it.
- Medium (60-80%): Plausible violation but requires assumptions. Report only if critical/important.
- Low (<60%): Speculative. Drop it entirely.

SEVERITY CLASSIFICATION:
- Critical: security, data loss, breaks runtime behavior, or standard explicitly marked mandatory
- Important: affects maintainability or correctness, toolchain-enforceable, or has runtime impact
- Suggestion: metadata/style gaps with no runtime impact and not enforced by the project's toolchain

HARD EXCLUSIONS — never report these:
- Style issues already enforced by the project's own linters/formatters
- Missing tests for trivial code (getters, setters, constants)
- Generic best-practice advice not grounded in a specific file:line
- Gaps that duplicate what a project make target already checks

PROHIBITED ACTIONS:
- Do NOT write or execute ad hoc tests
- Do NOT pipe code to a runtime
- Do NOT attempt to verify findings by executing code — static analysis only

Output format — one block per standards file:

STANDARD: <filename>
APPLICABILITY: APPLICABLE | NOT_APPLICABLE
REASON: <one line>
<if APPLICABLE, followed by zero or more gaps:>
GAP:
  severity: critical|important|suggestion
  confidence: high|medium
  location: <file:line>
  description: <what is wrong>
  why: <why it matters, grounded in the standard>
  fix: <suggested change>
```

## Critical Rules

- **NEVER modify source code, tests, or config** — this is an audit, not a fix
- **NEVER install dependencies or run the program** — static analysis only
- **NEVER run package managers** — no pip, npm, cargo, etc.
- **NEVER write or execute ad hoc tests** — if a test is missing, report it as a finding
- **NEVER pipe code to a runtime** — no `echo "..." | python`, `python -c`, etc.
- **Subdomain agents and validators use `subagent_type: "feature-dev:code-reviewer"`** — Write, Edit, and Bash are structurally unavailable, not just prompted against
- **All gaps need file:line references** — no vague complaints
- **Severity must be justified** — explain why something is critical vs. suggestion
- **Acknowledge strengths** — a good audit recognizes what the project already does right
- **Only write `./.tmp-standards/` intermediate files and let `render-standards.py` produce the final outputs** (shared handoff contract applies)
- **Skip empty validation tiers** — do not spawn a validator for a severity with zero findings
- **Audit is observation, not action** — `/apply-review` is the follow-up that applies fixes
