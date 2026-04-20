This section is shared across every producer skill in this plugin. It is
maintained in one place (`resources/handoff-contract.md`) and injected via
`!cat` so the rules stay consistent. Skill-specific details (pre-render
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
