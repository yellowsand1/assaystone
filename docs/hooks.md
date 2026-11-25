# Claude Code Stop hook

`assaystone hook claude-code` is a Stop hook: when Claude finishes a turn, it audits
the session transcript against the repository. It is the fastest way to put the audit
in a daily workflow.

## Install

```bash
pip install assaystone
cd your-agent-repo
assaystone hook install claude-code --mode warn
```

This merges the hook into `.claude/settings.local.json` (project scope). Use
`--user` for `~/.claude/settings.json`, and `--mode block` to enforce. Restart Claude
Code so it loads the settings.

To run a capability gate at Stop as well:

```bash
assaystone hook install claude-code --mode block \
  --manifest .assaystone/capability.json --stage shadow
```

This also writes `.assaystone/hook.json`:

The equivalent settings entry is:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "assaystone hook claude-code"}
        ]
      }
    ]
  }
}
```

```json
{
  "capability": ".assaystone/capability.json",
  "stage": "shadow"
}
```

## Gate the capability at Stop

With `capability` in the config, the hook evaluates the manifest against the working
tree before it lets the session stop. It uses the same oracles as CI; the difference
is who is watching:

- **pass** — the gate is silent.
- **fail or escalate** — the compact oracle table is printed; in `block` mode the
  stop is refused, so the agent keeps working.
- **hook error** (bad manifest, missing oracle) — fails open with the error; a broken
  hook must not trap the session.
- The hook does **not** sign a receipt and does **not** load the owner or receipt
  keys. Those belong to CI and the owner, not the agent. The CI gate with a receipt
  remains the authoritative record; the hook is the agent's feedback loop.

Keep the hook manifest fast. A full test suite at every Stop is correct but slow;
use a capability whose criteria are the checks an agent should iterate on, and keep
the full suite in CI.

## Behavior

The hook reads the JSON payload from stdin:

- `transcript_path` — the session JSONL.
- `cwd` — the repository baseline.
- `stop_hook_active` — Claude Code's loop guard.

It reads the current files touched by `Write` / `Edit` / `MultiEdit` (workspace mode —
the working tree is already post-session). When the repository has a `HEAD` commit, it
also builds a pre-image baseline from `HEAD` so diff-size and public-API checks remain
meaningful. It then runs the default audit rules and:

- **no findings** — exits `0` silently.
- **findings** — prints a compact summary.
- **warn mode** (default) — exits `0`; Claude stops normally.
- **block mode** — exits `2` for high/critical findings; Claude sees the message and
  continues instead of stopping.
- **`stop_hook_active`** — exits `0` to avoid a loop.
- **audit failure** — fails open with a message; a broken hook should not break the
  session.

## Enforce and tune

```bash
assaystone hook install claude-code --mode block
```

Or add `.assaystone/hook.json` to the repository:

```json
{
  "mode": "warn",
  "fail_on": "high",
  "ignore": [
    {"verifier": "tests.integrity", "paths": ["server/tests/**"]},
    {"verifier": "quality.no_debug_prints", "reason_contains": "generated"}
  ]
}
```

| Variable | Values | Default |
|---|---|---|
| `ASSAYSTONE_HOOK_MODE` | `warn`, `block` | `warn` |
| `ASSAYSTONE_HOOK_FAIL_ON` | `none`, `high`, `any` | `high` |

Environment variables override the config file. In warn mode, an identical finding is
reported once per session; the dedupe state lives under
`$XDG_CACHE_HOME/assaystone/hooks/` (or `~/.cache/...`). Block mode still blocks on
every offending turn, with `stop_hook_active` preventing an immediate loop.

## Why warn first

Legitimate tasks edit tests. Run in warn mode for a week, look at the findings, and
only then switch to block. The audit also points at false alarms: a finding you
disagree with is a candidate for a contract exception or a verifier change.

## Test manually

```bash
echo '{"transcript_path": "/path/to/session.jsonl", "cwd": "/path/to/repo"}' \
  | ASSAYSTONE_HOOK_MODE=block assaystone hook claude-code
```

The transcript path can be absolute or relative to `cwd`.

## Security

The hook runs locally and makes no network calls. The transcript may contain sensitive
text; the hook reads it to reconstruct artifacts and does not store it.
