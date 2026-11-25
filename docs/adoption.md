# Run a 45-minute design-partner session

The first external evidence does not come from a launch post. It comes from three
people who let you run the audit on one of their real sessions and tell you what it
missed. This is the script for that session.

## Who to ask

Someone who has recently complained, in public, about an agent that said it was
done and was not. Search for phrases like "agent deleted tests", "said it was done
but", "CI was green and the bug was still there".

Do not ask a company. Ask a person. Do not ask for adoption. Ask for 45 minutes.

## The invitation

> Hi — I saw your post about [specific problem]. I built a small check for that
> class of failure (a deleted test, a rewritten test runtime, a CI bypass) and I am
> collecting real sessions to find what it misses. Would you be up for 45 minutes
> where I run it on one of your recent sessions? Nothing leaves your machine, and
> finding nothing is a useful result too.

Keep it to five sentences. No deck, no signup, no request for stars.

## The session

| minutes | what |
|---|---|
| 0–5 | What they run, which agent, what "done" means on their team. Do not demo yet. |
| 5–15 | Ask them to pick one recent session where they were unsure. Run `uvx assaystone audit --latest claude-code` (or the Codex equivalent) on their machine. |
| 15–30 | Walk through the findings. For each: is it real, is it noise, would you have caught it? Write down the false positives. |
| 30–40 | Ask what the tool did not see. This is the part you are there for. |
| 40–45 | Ask whether they would run it for two weeks and what would have to be true. |

## If they own a deployment

The audit asks "what did the agent do?" The plane asks "should this capability
ship?" If the person owns a service, spend ten more minutes on their repository:

```bash
assaystone capability init --root . --owner <their team>
assaystone gate --manifest .assaystone/capability.json --stage shadow --root . --strict
```

The first run usually fails on the branch check or escalates on a missing
approval. That failure is the conversation: which of their irreversible actions
has no evidence today, and who would have to sign it. Do not fill in approvals
for them; the draft is theirs to correct.

## What to collect

- Consent to use a **redacted** trace as a fixture.
- The human verdict: `pass` or `fail`, and one line on the defect.
- The defect tag, or "new" if it does not fit.
- One quote about what it missed. Negative quotes are more valuable than praise.
- The false-alarm count from the session.

Add the trace the same day:

```bash
assaystone corpus add \
  --corpus assaystone/demo_data/goodhart/corpus.json \
  --family mechanical \
  --trace ./session.jsonl --format claude-code \
  --baseline ./repo-before \
  --label fail --defect <tag> \
  --note "what happened" --validate
```

If the current pack escapes the case, that is the finding. Add a verifier or
declare the blind spot; do not quietly drop the case.

## What not to do

- Do not install anything on their machine without asking.
- Do not ask them to change their test command or CI.
- Do not turn a false positive into an argument. Write it down and fix it.
- Do not ask for a testimonial before the session. Ask after, and only if the
  result was useful.

## After three sessions

You should have: three traces, three verdicts, a list of false positives, and at
least one failure class you did not anticipate. That is enough to write the first
honest field note — including the part where the tool was wrong.
