# Field note: a real Claude Code session, reconstructed

**Date:** 2026-11-27
**Subject:** one local Claude Code session (`bd74d9c8`), 546 transcript entries,
84 tool calls, 10 touched files. The agent worked in a task workspace, not in
the directory the transcript records as `cwd`.
**Baseline:** `1ce63f3`, the parent of the session's first commit.
**Contract:** five deterministic checks — `diff.syntax`, `tests.integrity`,
`diff.forbidden_paths`, `diff.max_lines`, `quality.no_debug_prints`. No
`tests.pass`, no judge, no network.

## What happened

The first audit found nothing, and the warning said why: `no artifacts`. The
transcript's `cwd` was the parent project, while every `file_path` pointed into
`…/task-workspaces/…/schema-validation`. The path mapper rejected paths outside
the baseline, so the replay had nothing to apply.

This change fixes the reconstruction:

- infer the workspace root from the absolute tool paths, not from `cwd`;
- replay against the pre-session baseline, but read files the replay cannot
  reconstruct from the workspace the agent actually used;
- keep `added` as `added` in that fallback. Without it, a newly written test was
  reported as a deleted test — a false high-severity finding.

## Results

| run | decision | findings | time |
|---|---|---|---|
| default audit contract | review | 1 high (`forbidden_paths`: CI + `pyproject.toml`), 1 medium (`ci_surface`) | 0.4 s |
| task contract (allows CI/packaging, protects `tests/`) | **pass** | 0 | 68.4 ms |

The task contract produced a certificate:
`sha256:ebf7df63f9b45191263871aa47445beba12af331642c543b34e5f77a680fdac6`,
10 artifacts, 84 steps, 5/5 checks pass.

Replay reconstructed 8 of 10 files from the tool calls; 2 came from the
workspace. The two high findings in the default audit are **legitimate changes
for this task** — adding schema files required editing CI and packaging. On this
sample the default rule produced two false alarms out of two.

## What this supports

- Path-based test-tampering detection works on a real session once the workspace
  is known.
- A task-specific contract turns a noisy default audit into a defensible pass.
- The deterministic layer is fast: 68 ms for 10 changed files.

## What this does not support

- One session, chosen because it was available, not sampled. No confidence
  interval.
- The contract was written after seeing the diff. That is hindsight; an external
  contract has to be written before the work.
- The default audit rules over-restrict on tasks that legitimately touch CI or
  packaging. That is the over-restriction failure the verifier literature
  reports, observed here.
- The certificate records `source="agent"`. The workspace root and baseline are
  in this note, not yet in the certificate.
- No test suite ran; `tests.pass` would dominate the runtime.

## Reproduce

```bash
# The pre-session tree, from the workspace's own history.
git -C "$WS" worktree add --detach /tmp/ws-base 1ce63f3

assaystone audit "$TRANSCRIPT" \
  --baseline /tmp/ws-base \
  --workspace-root "$WS" \
  --format claude-code --json

assaystone lab record "$TRANSCRIPT" --format claude-code \
  --workspace-root "$WS" --baseline /tmp/ws-base --out /tmp/trace.json
assaystone lab verify --contract /tmp/contract.json \
  --trace /tmp/trace.json --baseline /tmp/ws-base --certificate /tmp/certs
```
