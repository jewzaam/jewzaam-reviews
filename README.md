# jewzaam-reviews

A Claude Code plugin bundling a connected pipeline of review skills. Producer skills emit `Findings-<skill-name>[-<scope>].json` (validated against `schemas/findings.schema.json`) plus a script-rendered `.md` companion; `apply-review` consumes the JSON, applies each finding as an isolated commit, and emits `Report-apply-review.json` summarizing what happened.

## Skills

| Skill | Output files | Description |
|-------|--------------|-------------|
| `jewzaam-reviews:review` | `Findings-review[-<scope>].{json,md,-supplementary.md}` | Scope-aware multi-agent review via the script orchestrator |
| `jewzaam-reviews:standards` | `Findings-standards.{json,md,-supplementary.md}` | Audit repos against `~/source/standards/` personal standards library |
| `jewzaam-reviews:update-pr` | `Findings-update-pr-<number>.{json,md}` | Fetch GitHub PR review comments and supplementary feedback |
| `jewzaam-reviews:c4-reverse-engineer` | `Findings-c4-reverse-engineer.{json,md}` | Reverse-engineer C4 architecture diagrams and behavioral spec from a codebase |
| `jewzaam-reviews:apply-review` | `Report-apply-review.json` | Consume any `Findings-*.json`, apply as one-commit-per-finding, emit an action report |

## Installation

```bash
/plugin marketplace add jewzaam/jewzaam-reviews
/plugin install jewzaam-reviews@jewzaam-reviews-marketplace
```

For Codex:

```bash
codex plugin marketplace add jewzaam/jewzaam-reviews
codex plugin add jewzaam-reviews@jewzaam-reviews-marketplace
```

To update a published plugin:

```bash
codex plugin marketplace upgrade jewzaam-reviews-marketplace
codex plugin remove jewzaam-reviews@jewzaam-reviews-marketplace
codex plugin add jewzaam-reviews@jewzaam-reviews-marketplace
```

From the repository, update both harnesses when installed:

```bash
make update-plugins
```

If the marketplace was added from a local checkout (`codex plugin marketplace add .`),
it does not pull Git changes. After pushing updates, replace it with the Git marketplace:

```bash
codex plugin marketplace remove jewzaam-reviews-marketplace
codex plugin marketplace add jewzaam/jewzaam-reviews
codex plugin add jewzaam-reviews@jewzaam-reviews-marketplace
```

## Permissions

Skills invoke Python and Bash scripts from the plugin cache. To avoid repeated permission prompts, add these to your global (`~/.claude/settings.json`) or project (`.claude/settings.json`) allowlist:

```json
{
  "permissions": {
    "allow": [
      "Bash(bash ~/.claude/plugins/cache/jewzaam-reviews-marketplace/**)",
      "Bash(python ~/.claude/plugins/cache/jewzaam-reviews-marketplace/**)",
      "Bash(python3 ~/.claude/plugins/cache/jewzaam-reviews-marketplace/**)",
      "Bash(~/.claude/plugins/cache/jewzaam-reviews-marketplace/**)",
      "Read(~/.claude/plugins/cache/jewzaam-reviews-marketplace/**)",
      "Bash(bash ~/.claude/plugins/marketplaces/jewzaam-reviews-marketplace/**)",
      "Bash(python ~/.claude/plugins/marketplaces/jewzaam-reviews-marketplace/**)",
      "Bash(python3 ~/.claude/plugins/marketplaces/jewzaam-reviews-marketplace/**)",
      "Bash(~/.claude/plugins/marketplaces/jewzaam-reviews-marketplace/**)",
      "Read(~/.claude/plugins/marketplaces/jewzaam-reviews-marketplace/**)"
    ]
  }
}
```

The review orchestrator invokes the configured agent harness headlessly. Claude Code uses `claude -p`; Codex uses `codex exec`. Each harness uses its existing authentication. Under OpenShell, Codex uses `danger-full-access` inside the outer sandbox because nested read-only namespaces are blocked; set `REVIEW_ORCHESTRATOR_CODEX_SANDBOX=read-only` only where nested namespaces are available.

## Pipeline Overview

```mermaid
graph LR
    review["/review"] -->|Findings JSON| apply["/apply-review"]
    standards["/standards"] -->|Findings JSON| apply
    updatepr["/update-pr"] -->|Findings JSON| apply
    c4["/c4-reverse-engineer"] -->|Findings JSON| apply
    apply -->|Report JSON| done((done))
```

## Review Skill Architecture

The review skill is a thin wrapper around a standalone Python orchestrator (`orchestrator/cli.py`). The orchestrator owns the whole pipeline deterministically; models are invoked only for reasoning through the selected harness with harness-enforced JSON schemas.

```mermaid
graph TD
    A["/review [PR#] [--scoring MODE] [guidance]"] --> B["orchestrator/cli.py"]
    B --> C["Scope compute<br/>(git, deterministic)"]
    C --> D["Selector agent<br/>(haiku) picks lenses"]
    D --> E["Lens agents × selected<br/>(parallel)"]
    E --> F["Consolidate + diff-scope filter<br/>(scripts)"]
    F --> G["Validator agents<br/>(critical/important only)"]
    G --> H["Apply verdicts + render<br/>(scripts)"]
    H --> I["Findings files + measured cost report"]
```

Key properties:

- **Scope-aware sizing.** A cheap selector agent reads the diff (or repo shape) and picks applicable lenses from a roster with `runs_when` descriptions. The `implementation` lens always runs; a broken selector falls back to all lenses rather than silently narrowing the review. A small PR typically runs 1 selector + 2–4 lens agents + a validator, instead of a fixed matrix.

### Lenses

The roster lives in `orchestrator/lenses.py`; the selector picks the subset whose `runs_when` matches the scope.

| Lens (`concern_slug`) | Model | Selector picks it when |
|---|---|---|
| `implementation` | sonnet | Always — general correctness runs on every review |
| `architecture` | sonnet | Module structure, interfaces, configuration, or new files/packages change |
| `test` | sonnet | Functional code changed that should have tests, or test files changed |
| `maintainability` | sonnet | More than a trivial fix; build files; duplicated/complex logic |
| `security` | sonnet | Auth, crypto, secrets, input parsing, subprocess/network/file I/O, dependencies |
| `compatibility` | sonnet | Public interfaces (API/CLI/exports), URL or UI route paths, schemas or wire/file formats, DB migrations, config keys or defaults, metric/log/trace names, deployment manifests, runtime behavior consumers depend on |
| `documentation` | haiku | Docs files, public API surfaces, or user-facing behavior described in the README |
| `observability` | haiku | Logging, error paths, metrics, long-running/operational code |

The `compatibility` lens carries a self-contained breaking-change rubric — nothing external is read, so it behaves identically in any checkout. It classifies the deliverable first (batch tool / library vs long-running vs HA service) from repo evidence and assesses only the facets that can exist there: interface contracts (API, CLI including parsed stdout, schemas, behavioral semantics), persisted-state safety in both directions (upgrade and rollback), mixed-version coexistence and in-flight work during rolling updates (deployed services only), operational contracts (metric/log/trace names, config keys and defaults), URL and UI route paths, and third-party integrations.

Four rules in the rubric exist to suppress false positives as much as to find breaks: the **directionality rule** (narrowing what you accept and widening what you produce are breaking; the reverse is safe), the **well-behaved-consumer assumption** (a new optional field or enum value is additive, not a break), an explicit **not-breaking list** (new endpoints, bug fixes nobody could rely on, human-readable text changes), and **scope exclusions** (experimental features, unsupported configurations, interfaces with no outside consumer — though internal interfaces stay in scope for mixed-version coexistence on an HA service). Beyond detection, the lens reports a breaking change shipped without its version signal as a finding in its own right, and sizes the remedy per surface in `suggested_fix` — a deprecation cycle for an API break, a release-note entry and a word with the consuming team for a metric rename.
- **Deterministic everything else.** Consolidation, diff-scope filtering, batching, verdict application, severity mapping, and rendering are tested Python scripts. The orchestrator sequences them; no model reasoning is involved.
- **Measured cost and normalized tokens.** Claude results carry `total_cost_usd`; Codex dollar cost is unavailable through this CLI adapter. The orchestrator also records token usage and prints normalized token units when cost is unavailable. Normalization uses input = 1x, cache-read input = 0.1x, cache-write input = 1.25x, and output = 6x. These are comparison units, not a price estimate. Both measures are written to the per-stage/model ledger at `.tmp-review/costs.json`.
- **Validator pass.** Critical and important findings get an adversarial validator agent (premise check, dimensional/severity check, and PR-attribution check against the merge base for PR reviews). Verdicts are confirm / rescore / remove with an auditable removal trail in `issues[]`.

### Scoring modes

`--scoring` selects how findings are rated:

| Mode | Rating | Trade-off |
|------|--------|-----------|
| `categorical` (default) | Five categorical dimensions (`runtime_scope`, `failure_mode`, `evidence_quality`, `trace_origin`, `effort_to_fix`), each with a justification; severity buckets derived deterministically | More output tokens per finding; strongest noise filtering |
| `simple` | Direct `severity` (critical/important/suggestion) + `confidence` (high/medium/low); low confidence renders as needs-review | Cheaper and lighter; relies on the agent's direct judgment |

Each run's cost table shows what the chosen mode actually cost, so the trade-off can be compared with real numbers across runs.

> Migrating from ≤0.7.x: the `review-supplementary` skill and red/green test validation were removed. Suggestion and needs-review findings still land in the `-supplementary.md` file; validators now run inside `/review` itself.

## Severity Mapping (categorical mode)

Findings carry five categorical dimensions. The renderer maps them deterministically to severity buckets:

| Bucket | ID Prefix | Criteria |
|--------|-----------|----------|
| Critical | C | `demonstrated` + `entry-point` + `service-external` + `data-loss-or-security`/`crash-or-outage` |
| Important | I | `demonstrated`/`inferred` + `component`/`entry-point` + service scope + severe failure modes |
| Suggestion | S | Everything else that isn't speculative |
| Needs-review | N | `evidence_quality = speculative` (unvalidated by default) |

In simple mode, severity comes directly from the agents (validated for critical/important), and `confidence = low` maps to Needs-review.

## Usage

From any project repo:

```
/jewzaam-reviews:review                          # Full-repo review, scope-aware lens selection
/jewzaam-reviews:review 42                       # PR-scoped review (PR #42)
/jewzaam-reviews:review focus on auth            # Guided review
/jewzaam-reviews:review 42 --scoring simple      # PR review with simple scoring
/jewzaam-reviews:standards                       # Audit against ~/source/standards/
/jewzaam-reviews:update-pr                       # Pull PR review comments
/jewzaam-reviews:c4-reverse-engineer             # Generate C4 diagrams + spec
/jewzaam-reviews:apply-review                    # Apply any Findings-*.json
```

The orchestrator also runs standalone (useful outside Claude Code or from other agent frontends):

```
python <plugin-root>/orchestrator/cli.py --pr 42 --scoring simple
python <plugin-root>/orchestrator/cli.py --dry-run     # scope + selector prompt, no agents
python <plugin-root>/orchestrator/cli.py --detach ...  # long runs: start detached, survives the caller
python <plugin-root>/orchestrator/cli.py --wait --wait-timeout-s 3600  # block until done; exit 3 = timed out, rerun
```

The orchestrator needs either `claude` or `codex` on PATH with working auth. Select explicitly with `--harness claude|codex`, or leave the default `--harness auto` to use Codex when running under Codex and Claude otherwise.

For example:

```
python <plugin-root>/orchestrator/cli.py --harness codex --pr 42 --scoring simple
```

## Filename convention

Two document types, two prefixes (`<scope>` is `pr-<N>` for PR reviews or a slug derived from guidance text):

- **`Findings-<skill-name>[-<scope>].{json,md[,-supplementary.md]}`** — produced by the four producer skills. "Findings" because these are things the reviewer found in the user's code.
- **`Report-apply-review.json`** — produced by apply-review. "Report" because it summarizes actions taken, not findings. No markdown (no user-facing review document).

Filenames carry the skill name, not the project name. Project identity lives inside the JSON envelope's `project.name` field (the working directory is the project, so repeating it in every filename was redundant). Scope suffixes are used when a skill supports multiple scoped runs (e.g., PR numbers for `update-pr`, `pr-N` or a guidance slug for `review`).

## Development

```
make help               # Show all targets
make install-dev        # Create .venv and install test dependencies (auto-run by check/test)
make check              # Run all checks (test + version-check + resolved schemas)
make test               # Run pytest across plugin + skills + orchestrator
make version-check      # Validate semver consistency
make version-bump-patch # Bump patch (e.g. 0.2.8 → 0.2.9)
make version-bump-minor # Bump minor (e.g. 0.2.8 → 0.3.0)
make version-bump-major # Bump major (e.g. 0.2.8 → 1.0.0)
```

## Shared handoff schema

All producer and consumer skills validate their JSON against `schemas/findings.schema.json`. The schema discriminates on a top-level `source` field (`review` / `standards` / `c4-reverse-engineer` / `apply-review`) and carries a uniform `issues[]` array for meta-issues from the run. Review envelopes may carry a `scoring` field (`categorical` when absent, or `simple`) that selects which finding shape applies. `update-pr` is absent from the enum by design — it emits review-shaped findings with optional `pr_comment` fields, under `source: "review"`. See `CLAUDE.md` for the invariants and `resources/handoff-contract.md` for the full contract.

## License

Apache-2.0
