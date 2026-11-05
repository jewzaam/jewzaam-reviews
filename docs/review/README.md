# Review skill

Use this guide for everyday reviews with `jewzaam-reviews:review`. For
installation and pipeline internals, see the [repository README](../../README.md).

## Invoke a review

Run the skill from the repository you want reviewed:

- Codex: `$jewzaam-reviews:review`
- Claude Code: `/jewzaam-reviews:review`

Without a PR number, it reviews the whole repository. A PR number scopes
findings to files changed since the PR's merge base with the branch it
merges into: `--base <branch>` when given, else `gh pr view`. When neither
names it, the review refuses rather than guess; the skill asks which base to
use, offering remote branches HEAD sits closer to than the default (a PR cut
from a feature branch) plus the default branch.
Free-form guidance gives the review an additional focus. It does not restrict
findings to particular files.

Examples:

```text
$jewzaam-reviews:review
$jewzaam-reviews:review 42
$jewzaam-reviews:review focus on authentication and session handling
$jewzaam-reviews:review 42 --scoring simple
$jewzaam-reviews:review --profile docs
$jewzaam-reviews:review --interactive
$jewzaam-reviews:review --skip-lenses documentation,observability
$jewzaam-reviews:review --validate-buckets critical,important,suggestion,needs-review
```

Use `--scoring simple` for direct severity and confidence ratings. The default
`categorical` mode scores findings across five dimensions. `--interactive`
asks which scoring mode and lenses to use. Otherwise the selector chooses
lenses and all selected lenses run.

Use `--profile docs` when the documentation is the deliverable, as in an
architecture, standards, or design repository. Without it, documentation
findings cap at suggestion. When every in-scope file is documentation and no
profile was given, the skill asks which profile to use before the review runs.
To re-bucket a finished review without running agents, use
`cli.py --rerender --profile docs`.

The normal validation pass challenges critical and important findings. If the
review has none, it validates suggestions instead. It skips `needs-review` by
default. Use `--validate-buckets` to replace that selection and include other
buckets, including `needs-review`.

Give the review its purpose when that context is available: acceptance
criteria, the PR or issue description, or a short explanation of what the
change is meant to do. The skill passes that intent to the agents. If none is
available, the run records that fact in `Findings-intent[-<scope>].md`.

## Results

The review writes these files in the repository root:

- `Findings-review[-<scope>].json`: structured findings.
- `Findings-review[-<scope>].md`: main report and run status.
- `Findings-review[-<scope>]-supplementary.md`: findings grouped by review
  lens and severity.
- `Findings-intent[-<scope>].md`: the intent supplied to the review, or a note
  that none was available.

The skill runs the review in the background and waits for completion. Check the
run report for degraded or skipped stages, and the final summary for issues,
model names, cost, and normalized-token counts. Claude cost is backend-reported;
Codex cost uses the authenticated per-thread estimate returned by Codex's
app-server usage request. It is an estimate, not an invoice.

## Harness and model settings

The orchestrator names no models. Each agent runs at a review level, and the
user maps levels to models through the environment:

| Review level | Review work |
| --- | --- |
| `deep` | Implementation, architecture, tests, maintainability, security, backwards compatibility, and validation |
| `focused` | Lens selection, documentation, and observability |

| Variable | Effect when set | When unset |
| --- | --- | --- |
| `REVIEW_ORCHESTRATOR_HARNESS` | `claude` or `codex`; any other value stops the CLI with exit 2 | Codex when running under Codex, otherwise Claude |
| `REVIEW_ORCHESTRATOR_MODEL_DEEP` | Model id sent verbatim as `--model` to `deep` agents | No `--model`; the harness's own configuration decides |
| `REVIEW_ORCHESTRATOR_MODEL_FOCUSED` | Same, for `focused` agents | Same |
| `REVIEW_ORCHESTRATOR_BUDGET_USD_DEEP` | Per-agent spend cap in USD for `deep` agents | `6.0` |
| `REVIEW_ORCHESTRATOR_BUDGET_USD_FOCUSED` | Same, for `focused` agents | `2.0` |

Set both model variables to the same id to run every agent on one model. The
cost table names the model that ran, or `<harness>:default` when none was set.

The default caps were measured on Claude `sonnet`/`haiku`; raise them for a
pricier model. Only Claude enforces them (`--max-budget-usd`); Codex has no
spend cap. A budget value that is not a positive number stops the CLI with
exit 2 before any agent runs.

A stage's explicit effort is sent to Claude as `--effort` and to Codex as
`model_reasoning_effort`; otherwise each harness uses its configured default.
