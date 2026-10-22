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

The review roster chooses a review level based on the kind of analysis each
agent performs. Both harnesses use the same levels; only the translation to a
concrete provider model differs.

| Review level | Review work | Why |
| --- | --- | --- |
| `deep` | Implementation, architecture, tests, maintainability, security, backwards compatibility, and validation | These reviews trace behavior and assess interactions, edge cases, and risk. |
| `focused` | Lens selection, documentation, and observability | These are narrower classification or targeted review tasks. |

### Codex

The orchestrator invokes `codex exec` and maps review levels to Codex models:
`deep` to `gpt-5.6-terra` and `focused` to `gpt-6-luna`. Each agent uses the
model assigned to its review level; there is no global model override.

The `effort` supplied by a review stage is sent as Codex's
`model_reasoning_effort` setting. If a stage does not supply effort, Codex uses
its configured default.

### Claude Code

The orchestrator invokes `claude -p`, mapping `deep` to `sonnet` and `focused`
to `haiku`. The per-lens assignments and rationale are listed above. The
plugin has no environment variable for overriding Claude models at runtime.

For both harnesses, a stage's explicit effort is used when provided. Codex
receives it as `model_reasoning_effort`; otherwise Codex uses its configured
default. Claude receives explicit effort with `--effort`; otherwise Claude
uses its configured default.

The selected harness follows the host running the skill: Codex uses `codex`
and Claude Code uses `claude`. When running the CLI directly, select it with
`--harness codex` or `--harness claude`.
