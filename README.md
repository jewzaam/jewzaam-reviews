# jewzaam-reviews

A Claude Code plugin bundling a connected pipeline of review skills. Producer skills emit `Findings-<skill-name>[-<scope>].json` (validated against `schemas/findings.schema.json`) plus a script-rendered `.md` companion; `apply-review` consumes the JSON, applies each finding as an isolated commit, and emits `Report-apply-review.json` summarizing what happened.

## Skills

| Skill | Output files | Description |
|-------|--------------|-------------|
| `jewzaam-reviews:review` | `Findings-review[-<scope>].{json,md,-supplementary.md}` | Multi-agent codebase review across parallel dimensions |
| `jewzaam-reviews:review-supplementary` | Updates `Findings-review[-<scope>].*` | Validate supplementary findings from a prior `/review` run |
| `jewzaam-reviews:standards` | `Findings-standards.{json,md,-supplementary.md}` | Audit repos against `~/source/standards/` personal standards library |
| `jewzaam-reviews:update-pr` | `Findings-update-pr-<number>.{json,md}` | Fetch GitHub PR review comments and supplementary feedback |
| `jewzaam-reviews:c4-reverse-engineer` | `Findings-c4-reverse-engineer.{json,md}` | Reverse-engineer C4 architecture diagrams and behavioral spec from a codebase |
| `jewzaam-reviews:apply-review` | `Report-apply-review.json` | Consume any `Findings-*.json`, apply as one-commit-per-finding, emit an action report |

## Installation

```bash
/plugin marketplace add jewzaam/jewzaam-reviews
/plugin install jewzaam-reviews@jewzaam-reviews-marketplace
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

## Pipeline Overview

```mermaid
graph LR
    review["/review"] -->|Findings JSON| apply["/apply-review"]
    review -->|supplementary| reviewsupp["/review-supplementary"]
    reviewsupp -->|updated Findings JSON| apply
    standards["/standards"] -->|Findings JSON| apply
    updatepr["/update-pr"] -->|Findings JSON| apply
    c4["/c4-reverse-engineer"] -->|Findings JSON| apply
    apply -->|Report JSON| done((done))
```

## Review Skill Architecture

The review skill is the largest skill in the plugin. It runs a multi-phase pipeline with parallel agents, automated validation, and red/green test checking.

### Top-Level Flow

```mermaid
graph TD
    A["/review PR# guidance"] --> B[Pre-Fetch]
    B --> C[Orchestrator Agent<br/>Sonnet]
    C --> D[Scope & Decompose]
    D --> E[Agent Matrix<br/>1 + 7×N agents]
    E --> F[Consolidate]
    F --> G[Validate]
    G --> H[Apply Verdicts]
    H --> I[Red/Green Test Check]
    I --> J[Render]
    J --> K[Summary]

    style C fill:#4a9,stroke:#333
    style E fill:#49a,stroke:#333
    style I fill:#a94,stroke:#333
```

### Agent Matrix Detail

The orchestrator decomposes the scope into N dimensions, then dispatches agents in parallel:

```mermaid
graph TD
    subgraph "Dispatched in single parallel message"
        BC[Build & Checks<br/>Haiku]
        subgraph "Per Dimension ×N"
            A1[Architecture<br/>Sonnet]
            A2[Implementation<br/>Sonnet]
            A3[Test Quality<br/>Sonnet]
            A4[Maintainability<br/>Sonnet]
            A5[Security<br/>Sonnet]
            A6[Documentation<br/>Haiku]
            A7[Observability<br/>Haiku]
        end
    end

    BC --> raw[".tmp-review/00-raw/"]
    A1 --> raw
    A2 --> raw
    A3 --> raw
    A4 --> raw
    A5 --> raw
    A6 --> raw
    A7 --> raw
```

### Validation & Rendering Pipeline

```mermaid
graph LR
    raw["00-raw/<br/>per-agent JSON"] -->|consolidate-findings.py| merged["10-merged/<br/>deduplicated"]
    merged -->|batch-findings.py<br/>--only-buckets critical,important| batches["15-validation/<br/>batches"]
    batches -->|Validator agents<br/>Sonnet| verdicts["15-validation/<br/>verdicts"]
    merged --> apply["apply-verdicts.py"]
    verdicts --> apply
    apply --> findings["20-findings/"]
    findings -->|redgreen-validate.py| findings
    findings -->|render-review.py| output["Findings-review.json<br/>.md<br/>-supplementary.md"]
```

### Red/Green Test Validation

Runs after verdict application, before rendering. PR-scoped reviews only.

```mermaid
graph TD
    diff["git diff: test files in PR"] --> check{Test files<br/>exist?}
    check -->|No| critical["Critical finding:<br/>untested changes"]
    check -->|Yes| skip{Skip pattern<br/>match?}
    skip -->|Skipped| info["Skipped<br/>(integration/e2e)"]
    skip -->|Runnable| checkout["git checkout merge-base"]
    checkout --> restore["Restore test files<br/>from HEAD"]
    restore --> red["Run tests<br/>expect FAIL"]
    red --> head["git checkout branch"]
    head --> green["Run tests<br/>expect PASS"]
    green --> eval{Evaluate}
    eval -->|"fail → pass"| valid["Validated ✓<br/>no finding"]
    eval -->|"pass → pass"| nored["Critical finding:<br/>test doesn't prove bug"]
    eval -->|"fail → fail"| unrun["Critical finding:<br/>tests unrunnable"]
    eval -->|"pass → fail"| nogreen["Important finding:<br/>fix incomplete"]
```

### Supplementary Validation Flow

The main review skips validation for suggestion/needs-review findings. Run `/review-supplementary` to validate them:

```mermaid
graph LR
    merged["10-merged/<br/>from prior /review"] -->|batch-findings.py<br/>--only-buckets suggestion,needs-review<br/>--batch-offset N| batches["15-validation/<br/>new batches"]
    batches -->|Validator agents| verdicts["15-validation/<br/>new verdicts"]
    merged --> apply["apply-verdicts.py<br/>all verdicts"]
    verdicts --> apply
    apply --> findings["20-findings/"]
    findings -->|render-review.py| output["Updated output files"]
```

## Severity Mapping

Findings carry five categorical dimensions. The renderer maps them deterministically to severity buckets:

| Bucket | ID Prefix | Criteria |
|--------|-----------|----------|
| Critical | C | `demonstrated` + `entry-point` + `service-external` + `data-loss-or-security`/`crash-or-outage` |
| Important | I | `demonstrated`/`inferred` + `component`/`entry-point` + service scope + severe failure modes |
| Suggestion | S | Everything else that isn't speculative |
| Needs-review | N | `evidence_quality = speculative` (unvalidated by default) |

## Usage

From any project repo:

```
/jewzaam-reviews:review                 # Full review (5 concern axes + build checks)
/jewzaam-reviews:review 42              # PR-scoped review (PR #42)
/jewzaam-reviews:review focus on auth   # Guided review
/jewzaam-reviews:review-supplementary   # Validate supplementary findings
/jewzaam-reviews:standards              # Audit against ~/source/standards/
/jewzaam-reviews:update-pr              # Pull PR review comments
/jewzaam-reviews:c4-reverse-engineer    # Generate C4 diagrams + spec
/jewzaam-reviews:apply-review           # Apply any Findings-*.json
```

## Filename convention

Two document types, two prefixes:

- **`Findings-<skill-name>[-<scope>].{json,md[,-supplementary.md]}`** — produced by the four producer skills. "Findings" because these are things the reviewer found in the user's code.
- **`Report-apply-review.json`** — produced by apply-review. "Report" because it summarizes actions taken, not findings. No markdown (no user-facing review document).

Filenames carry the skill name, not the project name. Project identity lives inside the JSON envelope's `project.name` field (the working directory is the project, so repeating it in every filename was redundant). Scope suffixes are used when a skill supports multiple scoped runs (e.g., PR numbers for `update-pr`, scope slugs for `review`).

## Development

```
make help               # Show all targets
make check              # Run all checks (test + version-check)
make test               # Run pytest across plugin + skills
make version-check      # Validate semver consistency
make version-bump-patch # Bump patch (e.g. 0.2.8 → 0.2.9)
make version-bump-minor # Bump minor (e.g. 0.2.8 → 0.3.0)
make version-bump-major # Bump major (e.g. 0.2.8 → 1.0.0)
```

## Shared handoff schema

All producer and consumer skills validate their JSON against `schemas/findings.schema.json`. The schema discriminates on a top-level `source` field (`review` / `standards` / `c4-reverse-engineer` / `apply-review`) and carries a uniform `issues[]` array for meta-issues from the run. `update-pr` is absent from the enum by design — it emits review-shaped findings with optional `pr_comment` fields, under `source: "review"`. See `CLAUDE.md` for the invariants and `resources/handoff-contract.md` for the full contract.

## License

Apache-2.0
