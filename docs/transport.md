# Verification transport

A verifier judges what it can see. When an agent's execution is compacted,
delegated to a subagent, or imported through a tracing vendor, the verifier sees
a **summary** of the execution, not the execution. Judgments do not always
survive that abstraction.

Assaystone records which view it judged and can refuse to let an abstracted view
decide a pass.

## The view

Every trace carries a `view`:

```json
{"kind": "native", "adapter": "claude-code", "truncated": false}
```

| kind | meaning | risk |
|---|---|---|
| `native` | the verifier read the execution or the working tree directly | low |
| `restored` | provenance was restored from the original events | low |
| `imported` | the trace came through a vendor export | medium |
| `compacted` | the transcript preserved a summary, not the events | high |
| `delegated` | the work happened in a subagent and only its report remains | high |
| unknown | no view was recorded | medium |

Sources set this automatically:

- a git worktree episode is `native` / `git-worktree`;
- a runtime guard is `native` / `runtime`;
- a Claude Code transcript with a compaction marker is `compacted`;
- LangSmith / Langfuse / OpenTelemetry imports are `imported`.

## In the certificate

`subject.view` records the raw view. `assurance.transport` records the judgment:

```json
{"view": "compacted", "adapter": "claude-code", "risk": "high",
 "truncated": true,
 "reason": "the verifier judged an abstracted view; evidence may not transport"}
```

`certificate show` prints one line:

```
transport     compacted (risk high), adapter claude-code
```

## Make it a gate

```json
{"name": "strict", "require_native_view": true, "verifiers": [...]}
```

A pass that rests on a compacted, delegated, imported, or unknown view escalates
with `transport required: verifier saw a <kind> view`. A native or restored view
stands. This is the same shape as `require_measured`: a property the decision
must have, not a warning in a footnote.

## Limits

- Detection is honest but shallow. It sees explicit compaction markers and the
  adapter's own provenance; it cannot prove that an imported transcript is
  complete.
- `restored` is a declaration by the adapter. It is only as good as the
  provenance it restored.
- The gate is opt-in. Most contracts should start with `report`, look at the
  transport line, and turn the gate on where it matters.
- This does not recover lost evidence. It tells you the evidence is thin.
