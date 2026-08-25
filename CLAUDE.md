# jewzaam-reviews

Claude Code plugin bundling the review pipeline skills. Distributed as a marketplace plugin; not symlinked from `~/.claude/skills/`.

## Structure

```
.claude-plugin/
  plugin.json        # Plugin metadata (name, version, license)
  marketplace.json   # Marketplace listing
LICENSE              # Apache-2.0
README.md            # User-facing docs
Makefile             # `make test` and `make check`
pyproject.toml       # pytest configuration (--import-mode=importlib)
schemas/
  findings.schema.json   # Shared cross-skill handoff schema
  examples/              # Valid + invalid fixtures per source
resources/
  handoff-contract.md    # Injected into every producer SKILL.md via print-handoff-contract.sh
orchestrator/
  cli.py               # Review orchestrator entry point (see Orchestrator section)
  backend.py           # Agent seam: run_agent() via headless `claude -p`
  scope.py, lenses.py, prompts.py, pipeline.py, simple_mode.py
  tests/               # pytest tree (no __init__.py)
scripts/
  envelope.py            # Shared plumbing (plugin_version, validate_envelope,
                         #   build_envelope, content_hash, assign_ids_per_bucket,
                         #   load_stage_dir, write_stage_dir,
                         #   load_issues_file, format_validation_error, _line_start)
  bootstrap-tmp.sh       # Wipe + create .tmp-<skill>/ with validated dir-name
  print-handoff-contract.sh  # `!`-injection wrapper — cats handoff-contract.md
                             #   without triggering Claude Code's cross-dir cat block
  version-check.py       # Semver + sources-match + bump-vs-mainline check
tests/
  test_findings_schema.py, test_envelope.py, test_bootstrap_tmp.py,
  test_version_check.py  # Plugin-root tests (no __init__.py — see Test layout)
skills/
  <skill-name>/
    SKILL.md         # Required entry point
    scripts/         # Render scripts, helper scripts
    schemas/         # Skill-internal JSON schemas (NOT the shared handoff)
    references/, docs/  # Optional supporting files
    tests/           # pytest tree for this skill's scripts (no __init__.py)
```

## Plugin Path Resolution

**Critical**: When skills run inside a plugin, they are NOT at `~/.claude/skills/<name>/`. They live under the plugin install cache. Skill content must use `${CLAUDE_PLUGIN_ROOT}` to reference its own files, not absolute `~/.claude/skills/...` paths.

- Wrong: `python ~/.claude/skills/review/scripts/validate-findings.py`
- Right: `python ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/validate-findings.py`

When editing any `SKILL.md`, grep for `~/.claude/skills/` references and convert them.

## Script Execution Environment

Python scripts under `skills/*/scripts/` import from `scripts.envelope` (the plugin root's shared plumbing). Each script computes the plugin root from its own `__file__` path and inserts it into `sys.path`:

```python
SKILL_ROOT = Path(__file__).resolve().parent.parent   # e.g. skills/review/
PLUGIN_ROOT = SKILL_ROOT.parent.parent                # plugin root
sys.path.insert(0, str(PLUGIN_ROOT))
from scripts.envelope import validate_envelope, ...   # now importable
```

For local development and testing, ensure the working directory is the plugin root or that `sys.path` includes it. `pytest` discovers tests via `pyproject.toml` `testpaths` and runs from the repo root, so imports resolve automatically.

## Skill Sources

These skills were copied from standalone repos (now retired):
- `review` ← `claude-skill-review`
- `standards` ← `claude-skill-standards`
- `update-pr` ← `claude-skill-update-pr`
- `c4-reverse-engineer` ← `claude-skill-c4-reverse-engineer`
- `apply-review` ← `claude-skill-apply-review`

This repo is the new home; do not edit the originals.

## Shared JSON Handoff

All producer skills (review, standards, update-pr, c4 validation) and the apply-review consumer exchange structured findings through `schemas/findings.schema.json` at the plugin root. This is the cross-skill contract — skill-internal schemas (e.g., `skills/review/schemas/consolidated.schema.json`) stay local to their skill.

**Invariants — non-negotiable:**

1. **Every producer validates JSON output against `schemas/findings.schema.json` before writing.** Validation lives in the render script; fail fast, non-zero exit, no half-written artifacts.
2. **Markdown is always rendered from JSON by a script — never hand-authored.** The JSON is the source of truth; `.md` files are scripted views over it. No direct `Write(Findings-*.md)` or `Write(Report-*.md)` anywhere.
3. **Every JSON carries a top-level `issues[]` array** (may be empty) — the uniform place to capture meta-issues from the run (permission denials in sub-agents, sub-agent failures, tool unavailability, schema rejection of partial inputs). Findings describe the user's code; issues describe the skill's own operation.

Render scripts per skill:

| Skill | Render script | Source value |
|---|---|---|
| review | `skills/review/scripts/render-review.py` (with `apply-verdicts.py` for the 10-merged → 20-findings transition) | `review` |
| standards | `skills/standards/scripts/render-standards.py` | `standards` |
| c4-reverse-engineer | `skills/c4-reverse-engineer/scripts/render-c4-reverse-engineer.py` | `c4-reverse-engineer` |
| update-pr | `skills/update-pr/scripts/render-update-pr.py` | `review` (with `pr_comment` on findings) |
| apply-review | `skills/apply-review/scripts/render-apply-report.py` | `apply-review` |

`update-pr` is absent from the schema's `source` enum deliberately — its output is review-shaped with optional `pr_comment` extensions, so the enum value is `review`. The schema's `source.description` field documents this; readers who expect an `update-pr` value find that note there.

### Two-schema trap inside review

`skills/review/schemas/` holds the **review-internal schemas** (agent-output, agent-output-simple, selector-output, consolidated, merged-finding, stage-envelope, validation-input, validation-output, validation-output-simple). These are NOT the cross-skill `schemas/findings.schema.json`. The orchestrator's lens agents return **agent-output**-shaped JSON (written by the orchestrator into `.tmp-review/00-raw/*.json`); the consolidator writes **stage-envelope** + **merged-finding** files into `10-merged/`; `apply-verdicts.py` writes `20-findings/`; the renderer aggregates those into the final envelope validated against the shared schema.

Historical bug to watch for: an agent that mistakes the shared envelope for its own output spec writes envelope-shape keys (`schema_version`, `source`, `project`, `decomposition`, `issues`, ...) instead of agent-output keys (`agent_id`, `concern_slug`, `dimension_slug`, ...). The file is silently dropped from consolidation. `consolidate-findings.py` detects this shape mismatch and records a targeted `schema_rejected_input` issue in the stage envelope's `issues[]` — worth knowing when debugging a low-finding-count review. The orchestrator's `--json-schema` enforcement makes this much less likely than it was under prompt-only enforcement.

## Filename convention

All producer/consumer outputs follow `Findings-<skill-name>[-<scope>].{json,md[,-supplementary.md]}` for producer skills, and `Report-apply-review.json` for the consumer. Examples:

- `Findings-review.json` + `.md` + `-supplementary.md`
- `Findings-review-pr-42.json` (review with scope slug)
- `Findings-standards.json` + companions
- `Findings-c4-reverse-engineer.json` + `.md`
- `Findings-update-pr-1234.json` + `.md`
- `Report-apply-review.json` (no markdown — apply-review is a consumer)

The **skill name** identifies the producer in the filename; the user's **project identity** lives in the JSON envelope's `project.name` field (the working directory is the project, so repeating it in every filename was redundant). Scope suffixes are used when a skill supports multiple scoped runs (PR number for update-pr, scope slug for review).

## Shared helpers & injections

**`scripts/envelope.py`** holds all cross-skill plumbing. Render scripts import from here — do NOT duplicate. Exported: `plugin_version()`, `load_shared_schema()`, `validate_envelope()`, `build_envelope()`, `load_issues_file()`, `format_validation_error()`, `content_hash()`, `assign_ids_per_bucket()`, `_line_start()`.

**`resources/handoff-contract.md`** is injected into every producer SKILL.md's Pre-Fetch section via `!bash ${CLAUDE_PLUGIN_ROOT}/scripts/print-handoff-contract.sh` — except `review`, whose orchestrator enforces the contract in scripts rather than in the main agent's context. Edit once, apply to all skills. It defines the validate-before-write invariant, the markdown-rendered-from-JSON invariant, the `issues[]` shape, and the sub-agent failure pattern. Heading level inside the file is `####` — the injecting SKILL.md wraps it under a `### Shared Handoff Contract (auto-injected)` heading, which itself sits inside `## Pre-Fetch`. Keep the wrapper level consistent across skills.

The wrapper script exists because Claude Code's session-level `cat` permission blocks reads of paths outside the consuming project's working dirs, and the plugin root is always outside. A script invocation is permission-checked by its own path (predictable, easy to allowlist) rather than by the path argument to `cat` (unpredictable across projects).

**`.tmp-<skill-name>/`** is every producer skill's workspace, wiped/recreated on every invocation by `scripts/bootstrap-tmp.sh`. The bootstrap script validates the dir-name pattern (`^\.tmp-[A-Za-z0-9_-]+$`) before any `rm -rf` to prevent destructive mis-invocations. Sub-directories are passed as additional args. The review skill uses numbered stage directories for pipeline ordering:

```
.tmp-review/
  00-raw/            # per-agent output (one file per concern×dimension cell)
  10-merged/         # consolidation output: _envelope.json + per-finding <content_hash>.json
  15-validation/     # ephemeral batch I/O for validator dispatch
  20-findings/       # post-validation: _envelope.json + per-finding files (render input)
  agent-trace.jsonl  # one line per agent attempt: prompt, params, raw CLI result
  costs.json         # measured per-stage cost ledger
```

Each numbered stage directory follows a **stage contract**: `_envelope.json` carries metadata (project, decomposition, issues) and individual `<content_hash>.json` files carry findings. The `content_hash` is the stable cross-stage key — findings are identified by hash, not array position.

## Review orchestrator

The review skill is a thin wrapper; `orchestrator/cli.py` owns the pipeline. Modules:

- `backend.py` — **the agent seam**. `run_agent(prompt, *, schema, model, allowed_tools, cwd, effort, timeout_s) -> AgentResult` shells out to headless `claude -p --output-format json --json-schema ...`. Every model invocation goes through this one function; a future backend (e.g. codex) reimplements only this signature. `AgentResult` carries `output` (validated `structured_output`), the **measured** `cost_usd` (`total_cost_usd` from the CLI result), `model_usage`, `permission_denials`, and `error`. Child env is scrubbed of `CLAUDE*` vars so a nested session cannot leak in. `--bare` is never used (it refuses OAuth).
- `scope.py` — deterministic git/project context: git guard, PR merge base + scope block, guidance, standards gathering, project probe.
- `lenses.py` — the seven-lens roster (1:1 with the `concern_slug` enum) with `runs_when` selector guidance; selection fallback (all lenses) and dimension capping (`lenses × dimensions ≤ --max-agents`).
- `prompts.py` — selector / lens / validator prompt builders. Conditional blocks (standards, PR scope, guidance) are omitted entirely when empty.
- `pipeline.py` — stage sequencing. Deterministic stages are the existing tested stage CLIs run via subprocess; agents run in a ThreadPoolExecutor with per-agent timeout and **2 code-level retries** (retry on process error or local jsonschema failure). Cost from every attempt lands in the ledger; `.tmp-review/costs.json` plus a stdout table report real spend per stage. Every backend invocation also appends a line to `.tmp-review/agent-trace.jsonl` (prompt, invocation params, raw CLI result) — with `--no-session-persistence` this trace is the only record of what each sub-agent was asked and answered; it is the debugging trail after a review. Agent failures become `kind: "subagent_failure"` and denials `kind: "permission_denied"` in `issues[]`, merged into the stage envelope after consolidation.
- `simple_mode.py` — the `--scoring simple` path: Python dedup/batch/verdict application instead of the categorical stage CLIs (whose ordinal aggregation IS the categorical rubric); reuses `diff-scope-filter.py` and `render-review.py --scoring simple`.

Failed lens agents never block the run; a failed selector triggers the all-lenses fallback; a failed validator batch means its findings pass through unchanged (existing `apply-verdicts.py` semantics).

**Structured output constraint support** — Tested and confirmed working: `pattern`, `minLength`, `maxLength`, `minimum`, `maximum`, `minProperties`, `if/then/else`, `not`. The only constraint that fails is `allOf`/`anyOf`/`oneOf` at the **schema root level** (400 error). Nested inside properties or array items, all composition keywords work. `scripts/resolve_schema.py` enforces no root composition for agent-facing schemas; the backend strips only the `_generated` marker.

**Concern enum values use "and" not "&"** — `Architecture and Design`, `Test Quality and Coverage`, `Maintainability and Standards`. Changed from `&` because HTML entity encoding (`&amp;`) caused serialization corruption across XML/HTML/JSON boundaries.

## Test layout

Pytest autodiscovers three test trees: `tests/` at the plugin root (cross-skill tests), `skills/<name>/tests/` per skill (skill-internal tests), and `orchestrator/tests/`. **No `__init__.py` in any test dir.** `pyproject.toml` sets `addopts = ["--import-mode=importlib"]` to avoid `conftest.py` module name collisions between the two trees — adding an `__init__.py` silently breaks collection by reintroducing the collision. Run with `make test` (routed through a wrapper that the user's hooks permit).

## Adding a Skill

1. Create `skills/<name>/SKILL.md` with proper frontmatter (`name`, `description`).
2. Add supporting files under the skill directory (`scripts/`, `schemas/`, `tests/`).
3. Reference internal files via `${CLAUDE_PLUGIN_ROOT}/skills/<name>/...`.
4. **If the new skill produces findings or an action report**, write a render script that (a) builds the shared envelope, (b) validates against `schemas/findings.schema.json` before writing, (c) emits both JSON and any markdown view. Markdown must come from the JSON — never hand-authored.
5. Add pytest coverage under `skills/<name>/tests/` (`make test` auto-discovers it).
6. Update `README.md` skill table.
7. Bump `version` with `make version-bump-patch` (or `-minor`/`-major`).

## Versioning

SemVer per `~/source/standards/common/versioning.md`. The two `version` fields in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` must stay in sync.

Enforcement: `make version-check` validates that

1. `plugin.json` version matches official semver
2. `plugin.json` and `marketplace.json` versions match
3. When files in `schemas/` or `skills/` have changed vs mainline, the plugin version has been bumped

The check runs on every PR via `.github/workflows/version-check.yml`. On push to main, the workflow also creates a `vX.Y.Z` git tag if one doesn't exist.

Docs-only changes (CLAUDE.md, README.md, `.claude-plugin/` metadata other than `version`) do not require a bump — the script only looks at `schemas/` and `skills/` for bump-required detection.

Bump targets: `make version-bump-patch`, `make version-bump-minor`, `make version-bump-major`. These update `plugin.json`, `marketplace.json`, and all fixture `schema_version` fields atomically. Run `make help` for the full target list.

## License

Apache-2.0 for everything in this repo.
