---
name: review
description: Perform a multi-agent codebase review by spinning up parallel review agents across multiple dimensions (1 + 7×N agents per run). Use when the user asks to review, assess, audit, or evaluate a codebase or project. Accepts an optional PR number and/or free-form guidance text to focus the review.
disable-model-invocation: true
argument-hint: "[PR-number] [guidance text...]"
allowed-tools:
  # A: !-injection coverage (load-bearing)
  - Bash(bash ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python ${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/**)
  # B: Main-agent tools (also covered by global settings)
  - Bash(git remote -v)
  - Bash(make -n *)
  - Bash(make format)
  - Bash(make format-check)
  - Bash(make lint)
  - Bash(make typecheck)
  - Bash(make test)
  - Bash(make test-unit)
  - Bash(make coverage)
  - Bash(make complexity)
  - Bash(ls *)
  - Bash(test -f *)
  - Bash(test -d *)
  # C: Skill file access (also covered by global settings)
  - Read(${CLAUDE_SKILL_DIR}/**)
  - Glob(${CLAUDE_SKILL_DIR}/**)
  - Grep(${CLAUDE_SKILL_DIR}/**)
  # D: Sub-agent output workspace (for writing Workflow results to disk)
  - Write(./.tmp-review/00-raw/**)
  - Write(**/.tmp-review/00-raw/**)
  # E: Validator verdict output
  - Write(./.tmp-review/15-validation/**)
  - Write(**/.tmp-review/15-validation/**)
---

# Review Skill

## Purpose

Perform a multi-agent review of a codebase by spinning up parallel review agents across multiple dimensions. Produce a single consolidated review document, then validate it with an independent agent.

## Constraints

- **Script paths use `~`:** Use the **Plugin Home** path from the Pre-Fetch section (starts with `~`) when constructing Bash commands for plugin scripts. Do not use absolute `/home/...` paths. Do not use `&&` or `||` chaining — each script call must be a standalone Bash invocation.
- **Read-only analysis of source code.** Never modify the user's source code or tests.
- **No program execution.** Never install dependencies, run the program, or execute language runtimes directly (no `python -c`, `node`, `go run`, etc.) against the user's code.
- **No package management.** Never run `pip`, `npm`, `cargo`, etc.
- **Output is two markdown files plus one JSON file** at the project root: `Findings-review.md` (actionable findings), `Findings-review-supplementary.md` (detailed analysis, strengths, decomposition), and `Findings-review.json` (structured findings for downstream skills). Filenames follow the plugin-wide pattern `Findings-<skill-name>[-<scope-slug>].{json,md}` for producer skills (apply-review is a consumer and emits `Report-apply-review.json`) — the skill name identifies the producer; project identity lives in the JSON envelope's `project.name`. If the user provides constrained context (a PR number, specific area, topic), append a scope slug (max 12 chars, lowercase, hyphens): `Findings-review-<slug>.{json,md,-supplementary.md}`.
- **Intermediate workspace is `./.tmp-review/` at the project root** — created by the bootstrap pre-fetch, contains a `.gitignore` of `*` so it is never committed. Contains numbered stage directories: `00-raw/` (per-agent output), `10-merged/` (consolidated per-finding files), `15-validation/` (batch I/O), `20-findings/` (post-validation per-finding files).
- **If a check requires a tool not present**, note it in the review as a recommendation — do not attempt to install or build it.

## Pre-Fetch

### Git Context Guard (auto-executed)

Verifies this is a git repo with a determinable default branch. Exits non-zero on failure, aborting skill loading.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/check-git-context.sh`

### Plugin Home (auto-detected)

Plugin root with `~` prefix. Use this path in all Bash commands that invoke plugin scripts.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-plugin-home.sh ${CLAUDE_PLUGIN_ROOT}`

### Project Root (auto-detected)

Absolute path of the project root. Used for absolute path construction when writing Workflow results to disk.

!`pwd`

### Remotes (auto-executed)

!`git remote -v || true`

### Standards Applicability (auto-executed)

Runs `scripts/standards-check.sh`. For user-owned repos (origin owner matches `gh` login and `~/source/standards/` exists), injects the external standards CLAUDE.md with all relative links rewritten to absolute paths (e.g., `common/naming.md` becomes `~/source/standards/common/naming.md`). For non-owned repos, outputs nothing — project standards are already in context via Claude Code.

!`bash ${CLAUDE_SKILL_DIR}/scripts/standards-check.sh`

### Findings Workspace Bootstrap (auto-executed)

Wipes and recreates `./.tmp-review/` at the project root with `00-raw/`, `10-merged/`, `15-validation/`, `20-findings/`, and a `.gitignore` of `*`. Each `/review` invocation starts from a clean slate so stale findings from a prior run cannot leak into consolidation. Sub-agents and the main agent both write JSON into this tree.

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap-tmp.sh .tmp-review 00-raw 10-merged 15-validation 20-findings`

### Shared Handoff Contract (auto-injected)

!`bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-handoff-contract.sh`

### PR Scope (auto-executed)

If the first argument is numeric, computes the changed files against the default branch merge base. Output is injected as PR scope context for diff-scoped reviews. Any non-numeric trailing arguments are handled by the User Guidance step below. Outputs nothing if no numeric leading argument is given.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/pr-scope.sh "$ARGUMENTS"`

### User Guidance (auto-executed)

Extracts free-form guidance text from the arguments (everything after a leading PR number, or all arguments if none is numeric) and emits it as a "User Guidance" section. The main agent interprets the guidance and decides how it affects the review. Outputs nothing if no guidance is supplied.

!`bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/guidance.sh "$ARGUMENTS"`

## Process

Execute all steps sequentially. Schema enforcement on concern agents and validators uses the Workflow tool's `agent(schema:)` option, which validates output at the harness level.

### 1. Determine Scope & Context

- If the pre-fetch injected a "PR Scope" section, note it for passing to concern agents.
- If the pre-fetch injected a "User Guidance" section, note it for passing to concern agents. Interpret the guidance — it may be a focus hint, a narrowing filter, a specific question, or arbitrary context.
- Use Glob and Read to understand the project structure.
- Identify the language, framework, build system, and test framework.

**Standards detection:** Discover local project standards by reading `CLAUDE.md` and `AGENTS.md` at the project root, if they exist. These files define project conventions, coding rules, and behavioral instructions that the review should check against.

Follow explicit file path references found in rules or instructions sections (e.g., "see `docs/contributing.md`", "follow the style guide at `STYLE_GUIDE.md`"). Only follow paths that are clearly pointed to as standards, conventions, or guidelines — ignore casual mentions of source files, config paths, or directories referenced as examples. Follow references up to 2 levels deep (a standards file may reference another, but stop there). Collect all discovered standards into a local standards context and pass relevant portions to each agent — summarize or select sections pertinent to each agent's review area rather than dumping everything.

**External standards:** For user-owned repos, the pre-fetch injects the external standards index with absolute paths directly into context. Pass this content to each agent as part of their prompt — agents can Read any referenced file directly using the absolute paths. For non-owned repos, the pre-fetch outputs nothing and agents rely solely on the project's own CLAUDE.md (already loaded by Claude Code).

**Allowlist:** The allowed commands were provided in this prompt. Include them in each agent's prompt so agents know what they can run without blocking on user approval.

### 2. Decompose Scope into Dimensions

A **dimension** is a coherent slice of the review scope handed to a set of review agents. Decomposition decides how the work is sliced before any agent is dispatched.

**What can count as a dimension** (these are examples — pick whatever shape best matches the scope; do not feel obligated to use any specific one):
- A directory or sub-tree
- A package or module
- A logical theme (e.g., "auth", "data ingestion", "config layer")
- A cross-cutting concern (e.g., "security across all routes", "all CLI entry points")
- A single file *only when the entire scope is 1–2 files*; do not split a larger scope into one-dimension-per-file (that explodes agent counts without value)

**Decomposition rules:**
- **Default to decomposing.** For any meaningful scope, identify multiple dimensions. The only exception: when the scope is 1–2 files (a tiny PR or a single-file review), a single dimension covering them is acceptable — do not artificially split.
- **No cap on dimension count.** Large repos may produce 10+ dimensions and dozens of agents. Token cost is the explicit trade-off; the user has opted in.
- **Overlap is allowed.** Dimensions may overlap (e.g., a per-package dim plus a cross-cutting "security" dim). Consolidation deduplicates findings.
- **PR-scoped reviews:** derive dimensions from the changed file set. **Full-repo reviews:** derive from the project structure.
- **PR-scoped shared infrastructure:** When a PR changes files in shared infrastructure (e.g., `core/utils/`, `core/models/`, `lib/`) alongside feature-specific files, group the shared files into their own dimension and mark it as `"shared_infrastructure": true` in the `dimension_scope`. Include this flag verbatim in each agent's prompt for that dimension, along with: *"This dimension covers shared infrastructure files that were modified in the PR. Only report findings that are **introduced or exposed by this PR's changes** — not pre-existing issues. If the code worked correctly before the PR and the PR does not change its behavior, it is not a finding for this review."*
- For each dimension produce: a short human-readable name (e.g., `"auth subsystem"`), a filesystem-safe slug (lowercase, hyphens, ≤30 chars), and a `dimension_scope` object describing what the agent will review (e.g., `{"paths": ["src/auth/"]}` or `{"theme": "all CLI entry points", "paths": ["src/cli/"]}`).
- Record the full dimension list — you will write it into the supplementary review file at the render step.

### 3. Dispatch the Review Agent Matrix

After decomposition produces N dimensions:

1. Read the Workflow script from `${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/review-workflow.js`.
2. Find the line `// --- INJECT CONSTS HERE ---` in the script and insert the following const declarations immediately after it (the Workflow tool's `args` global is broken — all dynamic data must be embedded as const literals in the script):
   ```javascript
   const DIMENSIONS = <JSON array from Step 2, each with {name, slug, scope}>
   const PROJECT_ROOT = "<Project Root from Pre-Fetch>"
   const PROJECT_CONTEXT = {language: "<detected>", buildSystem: "<detected>", testFramework: "<detected>"}
   const STANDARDS = `<discovered local standards text, or empty string>`
   const PR_SCOPE = `<PR Scope output from pre-fetch, or empty string>`
   const USER_GUIDANCE = `<User Guidance output from pre-fetch, or empty string>`
   const ALLOWLIST = `<allowed commands text, or empty string>`
   const BUILD_PROMPT = `<prompt for the build-checks agent — see below>`
   ```
3. Invoke the Workflow tool with `script` set to the modified script contents. Do NOT pass `args` — all data is in the script.

The Workflow dispatches 1 build agent + 7×N concern agents with `agent(schema:)` enforcement and returns the results. The `agent(schema:)` option validates output at the harness level via Ajv — the model must produce conformant output via the StructuredOutput tool call before the agent can complete.

#### Build & Checks Agent

- `model: "haiku"`, default subagent_type
- Before running checks, probe for installed dependencies (`test -d node_modules`, `test -d .venv`, or equivalent for the detected language). If dependencies are not installed and a dependency-install target exists (`make install`, `make deps`), run it first. This is the **only** install target the build agent may run — it is a prerequisite for checks, not a deployment action.
- Runs available `make` check targets sequentially via Bash and reports pass/fail. Prefer commands from the provided allowlist.
- Safe targets to attempt (skip if missing): `make format-check` (or `make format` in check mode), `make lint`, `make typecheck`, `make test` or `make test-unit`, `make coverage`, `make complexity`.
- **The Build & Checks agent is the only agent that runs anything against the user's project.** Concern agents must not invoke complexity tools (radon, xenon), test runners, or any other analysis tools directly — if a check is worth running, it belongs in a `make` target the Build & Checks agent invokes.
- Do **not** run `build`, `run`, `deploy`, or any target that builds artifacts or executes the program.
- **Output guidelines:** summarize failures concisely — error type and affected files, not full stack traces. For missing-dependency failures, state which dependency is missing and move on.

#### Concern Axes (per dimension)

| # | Concern (`concern`) | `concern_slug` | Model | Scope |
|---|---|---|---|---|
| 1 | Architecture and Design | `architecture` | sonnet | Project structure, module boundaries, coupling, data model, configuration management, design pattern consistency. |
| 2 | Implementation Quality | `implementation` | sonnet | Logic correctness, error handling, type safety, resource management, edge cases, concurrency. **Security excluded — see dedicated axis.** |
| 3 | Test Quality and Coverage | `test` | sonnet | Test plan alignment, isolation, assertion quality, edge case coverage, mock usage, missing scenarios, fixture design. |
| 4 | Maintainability and Standards | `maintainability` | sonnet | Naming, duplication, import organization, function complexity, internal consistency, build system. **Documentation excluded — see dedicated axis.** |
| 5 | Security | `security` | sonnet | Authn/authz, input validation, injection vectors, credential/secret handling, path traversal, deserialization, supply chain (deps), TLS/crypto, auth-related error leakage. **Auth chain rule:** before reporting filter-level or data-level access control issues (IDOR, horizontal privilege escalation), verify the full auth chain — endpoint-level guards (dependencies, decorators, middleware) may already prevent the attack. If endpoint auth restricts access to privileged roles only, filter-level IDOR is not possible and must not be reported. |
| 6 | Documentation | `documentation` | haiku | README accuracy and completeness, docstrings, inline comments where non-obvious, examples, ADRs, changelog, public API docs, install/usage instructions. |
| 7 | Observability | `observability` | haiku | Log quality (levels, structured fields, sensitive data), error context (do exceptions carry enough info?), metrics, traces, debug affordances, alerting hooks. |

### 4. Write Raw Agent Output

After the Workflow returns, write each agent output to disk as `./.tmp-review/00-raw/<concern_slug>-<dimension_slug>.json`:

For each entry in `result.agentOutputs`:
- Write `entry.output` as JSON to `./.tmp-review/00-raw/<entry.filename>` (the Workflow returns filenames in `<concern_slug>-<dimension_slug>.json` format)

If `result.failedCount > 0`, collect issues for later inclusion:
- For each failed agent (null result), record a `subagent_failure` issue

Write `result.buildResult` to `./.tmp-review/00-raw/build-checks.json` (for reference; the consolidator will skip it due to schema mismatch — this is expected).

#### Methodology (per concern agent)

Each concern agent operates in two phases within its dimension scope:
1. **Establish baseline patterns:** read enough code in scope to understand the project's existing conventions for this concern. This grounds the review in the project's own patterns, not abstract ideals.
2. **Assess against baseline:** flag deviations and gaps. Classify each finding using the dimensional rubric below.

#### Dimensions (per finding)

Each finding is classified on five categorical dimensions. Names match the JSON schema fields exactly. Each dimension requires both a value and a `_justification` string explaining why the agent chose that value.

- `runtime_scope` — where the affected code executes: `documentation` | `tooling` | `ci` | `service-internal` | `service-external`. Determine from file paths and project structure. Justification cites the file/module and its role. **Test coverage gaps use `ci`** — a missing test would execute in CI, not in production. Do not use `service-internal` or `service-external` for a finding about a missing test; those scopes describe production runtime code with a demonstrated or inferred defect.
- `failure_mode` — concrete consequence if the issue manifests: `unclear` | `confusion` | `build-break` | `degraded-behavior` | `crash-or-outage` | `data-loss-or-security`. Justification describes the specific failure scenario. The failure must be **current**, not hypothetical — "if a future regression occurs" is not a failure mode, it is the absence of one. Use `unclear` when the system currently works correctly and the finding is about coverage or observability gaps.
- `evidence_quality` — how strongly grounded in observable code evidence: `speculative` | `inferred` | `demonstrated`. Justification summarizes the evidence chain. **`demonstrated` requires demonstrating a failure**, not demonstrating the absence of a test. "I can prove no test exists" is not demonstrated evidence of a bug — use `inferred` if you can identify a plausible failure scenario the test would catch, or `speculative` if you cannot.
- `trace_origin` — where the agent started tracing from: `local` | `component` | `entry-point`. For `entry-point`, the justification MUST name the entry point and trace the path. For `component`, identify the module boundary. For `local`, explain why no caller trace was performed. **Tracing to working code and noting "but there's no test" is not an entry-point trace** — the trace must lead to a problematic outcome. For test coverage gaps, use `local`.
- `effort_to_fix` — remediation cost (not used in criticality): `trivial` | `small` | `moderate` | `large`. Justification describes the fix approach.

**Split test gaps from production defects.** When reviewing code, you may notice both a potential defect in production code AND a missing test that would catch it. These are two separate findings:

1. **The defect** — scored with the production code's dimensions (`runtime_scope=service-*`, failure mode of the actual bug, evidence quality based on whether you can demonstrate the bug from the code). This finding reaches important or critical on its own merits.
2. **The test gap** — scored as `runtime_scope=ci`, `failure_mode=unclear` (the system currently works), `evidence_quality=demonstrated` (the absence of the test is observable). This finding lands at suggestion, which is appropriate for coverage gaps.

If you cannot demonstrate or infer the defect from the code — you just think a test should exist — report only the test gap. Do not inflate it with the production code's dimensions.

**Sub-agents do not drop low-evidence findings.** Every finding the agent identifies enters the pipeline. Validators may re-classify dimensions later; the render step maps dimension values to severity buckets via deterministic rules.

The `agent-output` schema does not include `severity` or `id` fields — the schema rejects either. Severity buckets and IDs are computed at the render step from the dimensional values; sub-agents do not need to think about them.

#### Hard Exclusions — Do Not Report

- Style issues already enforced by project linters or formatters (check for `.flake8`, `pyproject.toml [tool.ruff]`, `.eslintrc`, etc.)
- Missing tests for trivial code (getters, setters, simple data classes, constants)
- Architecture concerns in `scripts/`, one-off utilities, or exploratory code
- Suggestions that repeat what a make target already checks
- Missing docstrings on internal/private functions
- Generic best-practice advice not grounded in a specific code location
- **Positive observations or praise.** Every finding in `findings[]` must describe a *problem* — something that should change. If `suggested_fix` would say "no action needed", "continue doing this", or "maintain the practice", it is not a finding. Positive patterns belong in `cross_cutting_observations`, not `findings[]`.

### 5. Re-Validate Per-Agent JSON

After every concern agent returns, re-run the validator as defense-in-depth:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py ./.tmp-review/00-raw/<concern_slug>-<dimension_slug>.json
```

For any file that fails this re-validation, exclude it from consolidation and log a warning in the supplementary "Decomposition" preamble (you will write that preamble at render time). Do not re-dispatch — sub-agents already had three attempts.

### 6. Consolidate

Run the consolidator script — it applies the merge rules deterministically and writes per-finding files plus a stage envelope into `10-merged/`:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/consolidate-findings.py \
  --raw-dir ./.tmp-review/00-raw/ \
  --output-dir ./.tmp-review/10-merged/ \
  --project-name <project name> \
  --scope-slug <slug if PR-number or guidance constrained scope, else omit> \
  --cross-concern-threshold 0.4
```

The script writes `_envelope.json` (project metadata, decomposition, and any `schema_rejected_input` issues for skipped raw files) plus one `<content_hash>.json` per merged finding into the output directory.

What the script does (you do **not** re-implement this in your reasoning):

- **Pass 1: group by `(concern_slug, primary location)`.** Primary location is the first entry in `finding.locations` whose `role` is `primary` (or absent — defaulted to primary). Within each group: union `locations` (dedup by `path` + `line`), keep the longest non-trivial `suggested_fix` (tie-break by `dimension_slug`), take **max** ordinal of `runtime_scope`/`failure_mode`/`evidence_quality`/`trace_origin`, **min** ordinal of `effort_to_fix`, justifications from the winning contributor per dimension, sorted union of `dimension_slug` → `source_dimensions`.
- **Pass 2: cross-cutting merge within concern.** Within the same `concern_slug`, group remaining findings by title similarity (Jaccard over lowercased alphanumeric tokens, default threshold `--similarity-threshold 0.7`) and merge near-duplicates using the same categorical aggregation.
- **Pass 3: cross-concern merge at same location.** Across different `concern_slug` values, findings whose primary location is identical are grouped and sub-clustered by title similarity at a (typically lower) threshold of `--cross-concern-threshold` (default 0.4). The merged finding's `concern_slug` is taken from the highest-priority contributor (dimensional ordinal tuple, alphabetical tie-break). Same categorical aggregation rules as Pass 1.
- **Content hash.** Each merged finding gets a 16-char hex SHA-256 prefix over `(concern_slug, dimension_slug of first contributor, primary location path:line, title)`.
- **Decomposition.** Built from the per-agent `dimension_name`/`dimension_slug`/`dimension_scope`, deduplicated by `dimension_slug`.
- **No IDs. No severity buckets.** Both are assigned only at render time.
- Each finding file is validated against `merged-finding.schema.json` and the envelope against `stage-envelope.schema.json` before writing; the script exits non-zero on any validation error.

If a `00-raw/*.json` file fails its agent-output schema validation, the consolidator skips it with a warning on stderr and records a `schema_rejected_input` issue in the envelope. Note any skipped files in the supplementary "Decomposition" preamble at render time.

### 7. Validate Findings

Run the batcher script — it reads per-finding files from `10-merged/`, predicts severity buckets, and slices **only Critical and Important findings** into validation-input batches. Suggestion and Needs-review findings skip validation (they pass through `apply-verdicts.py` unchanged):

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/batch-findings.py \
  --input-dir ./.tmp-review/10-merged/ \
  --output-dir ./.tmp-review/15-validation/ \
  --only-buckets critical,important
```

What the script does (you do **not** re-implement this in your reasoning):

- Reads all per-finding files from `--input-dir` (excluding `_envelope.json`).
- Sorts findings by dimensional priority (ordinal tuple of `runtime_scope`, `failure_mode`, `evidence_quality`, `trace_origin`) descending; deterministic tie-break on `content_hash`.
- Slices into batches of at most **8** findings each (the spec's hard cap; `--batch-size` overrides but cannot exceed 8).
- Writes `batch-<N>-input.json` per batch containing `{batch_number, total_batches, findings: [...]}`.
- Findings are identified by `content_hash` (the sole cross-stage key). No `index` field is used.
- Strips fields not in the validation-input schema (e.g. `source_dimensions`).
- Validates every batch against `validation-input.schema.json` before writing; exits non-zero on any failure.

If zero batches are produced (all findings predicted as suggestion/needs-review), skip the validator dispatch and proceed to Apply Verdicts.

Read the batch input files from `./.tmp-review/15-validation/batch-*-input.json`.

Read the Workflow script from `${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-workflow.js`. Find the line `// --- INJECT CONSTS HERE ---` and insert const declarations immediately after it:

```javascript
const BATCHES = <JSON array of batch objects read from the batch input files>
const PROJECT_ROOT = "<Project Root from Pre-Fetch>"
```

Invoke the Workflow tool with `script` set to the modified script contents. Do NOT pass `args`.

The Workflow dispatches `total_batches` validator agents with `agent(schema:)` enforcement. Each validator:

- Opens the cited `finding.locations`, challenges accuracy and the five categorical dimensions.
- **Challenges the premise, not just the symptom.** A finding may cite real code and describe a technically accurate gap, yet be wrong because its premise is invalid. Examples: (1) an IDOR finding against a filter parameter when endpoint-level RBAC already restricts access to privileged roles — the filter cannot be reached by unprivileged users; (2) a "missing test" finding when the behavior is already tested indirectly through a higher-level test; (3) a security concern about input validation when the framework (FastAPI/Pydantic) validates before the code runs. Validators must verify assumptions, not just locations.
- **Removes positive observations.** If a finding's `issue` describes something working correctly and `suggested_fix` says "no action needed", "continue", or "maintain", remove it — it is praise, not a finding.
- Each verdict is one of:
  - `"action": "confirm"` — finding stands as-is.
  - `"action": "rescore"` — provide `new_dimensions` with any subset of the five dimension fields (value + justification pairs). Validators may upgrade `evidence_quality` or `trace_origin` if they find stronger evidence.
  - `"action": "remove"` — finding is wrong (e.g., cited line does not exist, issue is not real).
- Each verdict carries `finding_ref: {content_hash}` — **copy the `content_hash` verbatim from the input batch finding**. Do NOT recompute the hash. The `content_hash` is both the filename and the integrity key across pipeline stages.

After the Workflow returns, write each validator output to disk:

For each entry in `result.validatorOutputs`:
- Write `entry.output` as JSON to `./.tmp-review/15-validation/<entry.filename>`

### 8. Apply Verdicts

Run the verdict application script — it reads verdicts from `15-validation/` and findings from `10-merged/`, applies them deterministically, and writes the surviving findings to `20-findings/`:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/apply-verdicts.py \
  --input-dir ./.tmp-review/10-merged/ \
  --verdicts-dir ./.tmp-review/15-validation/ \
  --output-dir ./.tmp-review/20-findings/
```

What the script does (you do **not** re-implement this in your reasoning):

- Reads all `batch-*-output.json` from `--verdicts-dir`, validates each against `validation-output.schema.json`.
- Builds a `content_hash → verdict` map.
- For each finding in `--input-dir`:
  - `"confirm"`: copy unchanged to `--output-dir`.
  - `"rescore"`: shallow-merge `new_dimensions` into the finding, validate the result against `merged-finding.schema.json`, write to `--output-dir`.
  - `"remove"`: skip (finding absent from `--output-dir`).
  - No verdict (e.g., failed validator batch): pass through unchanged.
- Copies `_envelope.json` to `--output-dir`, merging any verdict-parsing issues into `issues[]`.
- Findings with `speculative` evidence quality are kept; the renderer segregates them into `needs-review`.

### 9. Red/Green Test Validation

Run the red/green validator. The script computes the merge base internally and skips automatically for non-PR reviews. Synthetic findings land in `20-findings/` alongside review findings.

Before invoking, read the project's `Makefile` to understand how the venv is built and how tests run. If a venv build target exists (e.g., `make install`, `make deps`), run it, then activate the venv. Pass the activation and test command to the script:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/redgreen-validate.py \
  --findings-dir ./.tmp-review/20-findings/ \
  --project-root <project root> \
  --setup-command '<cd + activate venv, e.g. "cd backend && source .venv/bin/activate">' \
  --test-command '<how the project runs a single test file, with {file} placeholder>' \
  --strip-prefix '<subdirectory prefix if tests run from a subdir, e.g. "backend/">'
```

### 10. Render

Run the renderer:

```
python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/render-review.py \
  --input-dir ./.tmp-review/20-findings/ \
  --out-dir <project root> \
  --project-name <project name> \
  --scope-slug <slug if PR-number or guidance constrained scope, else empty>
```

Skill-specific renderer behavior (on top of the shared contract):
- Maps each finding to a severity bucket (`critical | important | suggestion | needs-review`) using deterministic rules over the categorical dimensions.
- Assigns IDs in stable per-bucket order: `C0..`, `I0..`, `S0..`, `N0..`.
- Writes three files: `Findings-review[-<slug>].json`, `.md`, `-supplementary.md`.

The slug derivation from `/review` arguments matches today's behavior (max 12 chars, lowercase, hyphens; appended when scope is constrained by PR number or guidance text). Pre-existing PR-scope and user-guidance pre-fetch outputs supply the source material.

- **No writes outside `./.tmp-review/` and the three final output files.** The only permitted Write targets for the main agent are `Findings-review[-<slug>].json`, `Findings-review[-<slug>].md`, and `Findings-review[-<slug>]-supplementary.md`. Any other Write — to `${CLAUDE_PLUGIN_ROOT}/...`, to `docs/`, to `scripts/`, to `/tmp/`, anywhere — is a violation.

### 11. Present Summary

After rendering, read the counts from the rendered JSON (`findings[]` grouped by `severity`) and output a terse summary:

```
X critical, Y important, Z suggestion, W needs-review (unvalidated).

Files:
- Findings-review[-<slug>].json
- Findings-review[-<slug>].md
- Findings-review[-<slug>]-supplementary.md
```

If suggestion + needs-review > 0, append:

```
To validate supplementary findings, run: /review-supplementary
```

No inline findings, no commentary. The files have everything.

## Critical Rules

- **NEVER execute anything against the user's code or environment.** Static analysis only. This single rule subsumes:
  - No running the user's program (`python -m <module>`, `node`, `go run`, etc.)
  - No installing or upgrading packages (`pip`, `npm`, `cargo`, etc.)
  - No piping code to a runtime (`echo "..." | python`, `python -c "..."`, equivalents in any language)
  - No writing or running ad-hoc test files to "verify" a finding. The presence of a missing test is itself a finding — file it as one. **Anything that would otherwise need a runtime check is a missing test, not a script you write.**
  - No `make install`, `make build`, `make run`, `make deploy`, or any target that installs or executes the program.
  - The Build & Checks agent is the only agent allowed to run anything (`make` check targets only — `format`, `lint`, `typecheck`, `test`, `coverage`).
- **Writes are restricted by tool boundary, not just intent:**
  - **Concern agents and validation agents** do not Write or Bash — their output is returned via `agent(schema:)` and written to disk by the main agent in Steps 5 and 6.
  - **Main agent** writes only to `./.tmp-review/00-raw/` (Workflow results), `./.tmp-review/15-validation/` (validator results), and the three output files at the project root (`Findings-review[-<slug>].json|.md|-supplementary.md`). No edits anywhere else. In particular: **never Write, Edit, or `mv` anything into `${CLAUDE_PLUGIN_ROOT}/`** — the plugin tree is read-only from inside a skill run. The `apply-verdicts.py` script handles the `10-merged/ → 20-findings/` transition; the main agent does not write to `20-findings/` directly.
- **Bash is restricted:** main agent Bash limited to the skill's allowlisted scripts (bootstrap, schema cleaner, validators, consolidator, batcher, verdict applicator, red/green validator, renderer, pre-fetch helpers).
- **Prefer allowlisted commands** — agents receive the allowlist as context. Stick to pre-approved commands to avoid blocking the review on user approval prompts.
- **All findings need `finding.locations[]` entries** — the schema enforces this; the validator rejects missing locations.
- **Acknowledge strengths** — a good review recognizes what works well; the supplementary file has a Strengths section. Sub-agents may note positive patterns in their `cross_cutting_observations` field if they wish to call them out.
- **Review is observation, not action** — the review identifies findings and gaps for other agents or the user to act on later. If something needs runtime verification, recommend it as a next step in the review.
