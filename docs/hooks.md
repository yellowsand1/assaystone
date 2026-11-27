# Claude Code hooks

Three hooks, one policy:

- **`assaystone hook claude-code-pre`** runs on `PreToolUse`. It decides one tool
  call *before* it executes, from a small local policy, and can block it.
- **`assaystone hook claude-code-post`** runs on `PostToolUse`. It checks what
  the action produced — Python syntax, leaked secrets — and feeds the defect
  back to the model on the next step.
- **`assaystone hook claude-code`** runs on `Stop`. It audits the session
  transcript against the repository and can refuse the stop.

Both write what they observed into `.assaystone/`, which is excluded from the
diff under review: the tool's own records are not the work.

## Install

```bash
pip install assaystone
cd your-agent-repo
assaystone hook install claude-code --mode warn
```

This merges both hooks into `.claude/settings.local.json` (project scope) and
writes a starter `.assaystone/policy.json`. Use
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
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": "assaystone hook claude-code-pre"}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": "assaystone hook claude-code-post"}
        ]
      }
    ],
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
  "stage": "shadow",
  "trail": ".assaystone/trail.jsonl"
}
```

With `trail`, the hook appends its decision to that trail and writes the entry
hash into `.assaystone/runtime/last.json`, so a later gate can check that the
session and the decision it names are the same object. The record ignores
`.assaystone/` when it hashes the workspace: the evidence directory is not the
work under review, and it changes as the record is written.

The hook's gate skips `runtime` and `drill` oracles and says so — the process
that writes the session evidence cannot require it to exist already. CI, running
after the session, evaluates them normally.

## Gate the action before it runs

The pre-tool hook reads `.assaystone/policy.json` and evaluates the call with no
model, no network, and no repository copy:

```json
{
  "mode": "warn",
  "deny_paths": [".github/workflows/", ".github/actions/"],
  "deny_commands": [
    "rm\\s+-rf\\s+/(?:\\s|$)",
    "git\\s+push\\s+(?:--force|-f)\\b",
    "chmod\\s+777\\b",
    "DROP\\s+(?:TABLE|DATABASE)\\b"
  ],
  "allow_write_roots": ["."],
  "record": true
}
```

- **`deny_tools`** — exact Claude Code tool names, for example `WebFetch`.
- **`deny_paths`** — prefixes for any path the tool will write or edit.
- **`deny_commands`** — regular expressions searched in a `Bash` command.
- **`allow_write_roots`** — when set, a write outside these prefixes is denied.
- **`mode`** — `warn` reports; `block` exits 2, which makes Claude Code refuse the
  call and show the reason to the model. `ASSAYSTONE_HOOK_MODE` overrides it.
- **`record`** — append every decision to `.assaystone/session.jsonl`.

Every call is denied if its path resolves outside the workspace, regardless of
the policy. Denied arguments are recorded as digests, and commands are stored
redacted, so the record does not become a secret leak.

A missing policy file is passive: installing a hook must not silently start
denying work. The installer writes a conservative starter policy; edit it.

Limits, stated rather than hidden:

- The command rule is lexical. `bash -c "$(echo cm0gLXJmIC8= | base64 -d)"` will
  not match a pattern for `rm -rf /`. This is a guardrail, not a sandbox.
- `deny_paths` sees file-tool arguments. A shell redirect such as
  `echo x > .github/workflows/ci.yml` is a `Bash` call with no path argument; it
  needs a `deny_commands` pattern of its own.
- A script the agent writes and then runs is only seen at the `Bash` call that
  runs it, not at the writes inside the script.
- It judges the call, not the intent. A denied action can still be legitimate;
  the message says which rule matched so a human can adjust the policy.

## Check the result after the action

The pre-tool gate stops the call it can see. The post-tool gate checks what the
call produced, at the earliest point where the result exists:

- **Python syntax.** After `Write` / `Edit` / `MultiEdit` on a `.py` file, the
  file is parsed. A syntax error is fed back with the line number, so the model
  fixes it on the next step instead of at Stop.
- **High-confidence secrets.** Written content, the command, and the tool
  response are scanned for AWS access keys, private-key headers, GitHub tokens,
  and `sk-` keys. Generic `token=` patterns are deliberately not matched.
- **Evidence.** Every post decision is appended to `.assaystone/session.jsonl`
  with `phase: "post"` and the violations, next to the pre-tool decisions.

Both checks are controlled by the policy:

```json
{
  "mode": "block",
  "post_syntax": true,
  "post_secrets": true
}
```

Exit 2 shows the message to the model; the action is not undone. This is a
correction loop, not a transaction. Same limits as the pre-tool gate: lexical
matching, no semantic judgment, and a missing policy is passive.

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
