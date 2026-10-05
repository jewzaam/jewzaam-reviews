# Review skill

Use this guide for everyday reviews with `jewzaam-reviews:review`. For
installation and pipeline internals, see the [repository README](../../README.md).

## Invoke a review

Run the skill from the repository you want reviewed:

- Codex: `$jewzaam-reviews:review`
- Claude Code: `/jewzaam-reviews:review`

Without a PR number, it reviews the whole repository. A PR number scopes
findings to files changed since the PR's merge base with the default branch.
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
model names, costs when available, and normalized-token counts. Codex does not
report dollar cost through this orchestrator.

## Harness and model settings

The review skill launches the harness CLI as a separate process. The model
selected for the current Codex or Claude Code conversation does not configure
these review agents.

### Codex

The orchestrator invokes `codex exec`. All review agents use one Codex model.
The review roster's `sonnet` and `haiku` tiers are mapped to it.

| Environment variable | Default | Effect |
| --- | --- | --- |
| `REVIEW_ORCHESTRATOR_CODEX_MODEL` | `gpt-5.6-luna` | Model for the selector, lens agents, and validators. |
| `REVIEW_ORCHESTRATOR_CODEX_EFFORT` | `high` | Codex `model_reasoning_effort` setting for all agents. |

Set these in the environment that launches Codex, before starting the Codex
host. A later shell export will not change an already-running Codex process.
The detached review inherits the host's environment. For example, to run the
orchestrator directly for one review:

```bash
REVIEW_ORCHESTRATOR_CODEX_MODEL=gpt-5.6-sol \
  python /path/to/jewzaam-reviews/orchestrator/cli.py --harness codex --detach --pr 42
python /path/to/jewzaam-reviews/orchestrator/cli.py --harness codex --wait --wait-timeout-s 3600
```

Set `REVIEW_ORCHESTRATOR_CODEX_MODEL` to an empty string to omit `--model` and
let the Codex CLI use its configured default. This setting applies to every
agent. There is no per-lens model override.

### Claude Code

The orchestrator invokes `claude -p` with an explicit model. Most lenses and
validators use `sonnet`. The selector and documentation/observability lenses
use `haiku`. The plugin has no environment variable for overriding these
models at runtime.

The selected harness follows the host running the skill: Codex uses `codex`
and Claude Code uses `claude`. When running the CLI directly, select it with
`--harness codex` or `--harness claude`.
