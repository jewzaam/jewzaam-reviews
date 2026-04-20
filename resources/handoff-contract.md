This section is shared across every producer skill in this plugin. It is
maintained in one place (`resources/handoff-contract.md`) and injected via
`scripts/print-handoff-contract.sh` so the rules stay consistent.
Skill-specific details (pre-render
shape, render script path, output filenames) live in each skill's own
sections below.

The injecting skill provides the heading (`### Shared Handoff Contract
(auto-injected)`) — the content here starts at heading level 4 to nest
cleanly under it.

#### Invariants — non-negotiable

1. **Validate before writing.** Every render script builds the envelope in
   memory, validates it against `${CLAUDE_PLUGIN_ROOT}/schemas/findings.schema.json`,
   and exits non-zero without writing anything on failure. Never write a
   `Findings-*.json` or `Report-*.json` directly; always go through the skill's render script.
2. **Markdown is rendered from JSON.** The `.md` and `-supplementary.md`
   companion files are views over the authoritative JSON. Never
   hand-author them, never `Write(...)` them from the main agent.
3. **`schema_version` tracks the plugin version.** The render script reads
   the current plugin version at runtime and emits it as `schema_version`.
   Bumping the plugin version (in `.claude-plugin/plugin.json`) implicitly
   bumps the schema version. `make version-check` enforces that example
   fixtures stay aligned.
4. **Every envelope carries `issues[]`** (may be empty, never absent). It
   is the uniform cross-skill place for meta-issues from the run.

#### Sub-agent failure handling

Skills that dispatch sub-agents follow a consistent pattern:

1. Each sub-agent retries its work up to **3 attempts** (1 initial + 2 retries)
   when it can self-detect a problem (e.g., its own output fails schema
   validation).
2. After 3 attempts the sub-agent bails and returns a structured failure in
   its final response: `{"status": "failure", "reason": "<short cause>"}`.
3. The main agent receives that response and must emit one `issues[]` entry
   per failed sub-agent — `kind: "subagent_failure"`, the sub-agent's
   `reason` in `message`, and the sub-agent identifier (e.g., `security/auth`)
   in `source_component`. The main agent does **not** re-dispatch — the cap
   is final.
4. Sub-agents cannot request permissions the way the main agent can — if a
   tool call is denied, the sub-agent treats it as an unrecoverable error
   for that attempt. The main agent emits `kind: "permission_denied"` in
   `issues[]` with the denied tool in `context` so the user can audit after
   the run.

Failed sub-agents do not block the run: other sub-agents' outputs still
flow into consolidation, and the final envelope ships with the failure
recorded in `issues[]`.

#### Issues: what goes there

`issues[]` entries describe **problems the skill ran into**, not findings
about the user's code. Examples: a sub-agent returned malformed JSON after
the retry cap, a required tool is unavailable, a permission prompt was
denied, the render script rejected a partial input. Each entry:

```json
{
  "severity": "error" | "warning",
  "kind": "permission_denied" | "subagent_failure" | "validation_failed"
        | "tool_unavailable" | "schema_rejected_input" | "other",
  "message": "<human-readable>",
  "source_component": "<optional: which sub-agent or script>",
  "context": { "...optional structured data..." }
}
```

Collect issues into `.tmp-<skill-name>/issues.json` (a JSON array of the
objects above). Pass the path to the render script via `--issues`. Omit
`--issues` only when there were zero issues.

#### Workspace

The pre-fetch at the top of every producer skill injects a shared bootstrap
that creates `.tmp-<skill-name>/` at the project root with a `.gitignore`
of `*` and wipes any prior contents. Write the pre-render JSON, the issues
JSON, and any other intermediate artifacts inside this directory — nothing
there is ever committed.
