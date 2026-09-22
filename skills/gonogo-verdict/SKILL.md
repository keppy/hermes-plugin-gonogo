---
name: gonogo-verdict
description: Use when a measurement result is about to be read as a decision — pass rates, accuracy claims, "is this agent good enough to ship", or comparing two runs. Turns a score into a defensible ship / don't-ship call with gonogo.
---

# Turning a score into a decision

A pass rate is not a decision. `47/50` reads as 94%, but the 95% interval on
that is [83.8%, 97.9%] — so if the bar is 90%, you cannot yet say you cleared
it. Most tools print the 94% and stop. The three tools in this plugin are what
turn the number into a call, and they run gonogo's statistics locally: no
network, no model calls, no credentials.

## Which tool answers which question

| The question | Tool |
| --- | --- |
| "Is this good enough to ship?" — a count, a pass rate, a results file | `gonogo_decide` |
| "Give me the report artifact" — for a doc, a PR, a pilot review | `gonogo_report` |
| "Is B actually better than A?" | `gonogo_compare` |

Call `gonogo_decide` the moment someone states a pass rate as if it settled
something, or asks whether an agent can be put in front of real work — even
when they did not ask for statistics. Call `gonogo_compare` before agreeing
that a change improved anything: on pilot-sized samples a 3-point gap is
usually noise, and "not distinguishable" is the useful answer.

## The five verdicts

| Verdict | What it means for the decision |
| --- | --- |
| `AUTOMATE` | The pass rate's **lower bound** clears the target. Ship it. |
| `AUTOMATE WITH REVIEW` | Not good enough overall, but a confident subset is. Ship behind a confidence threshold; the rest goes to a person. |
| `ASSIST ONLY` | A draft generator, not an unattended step. |
| `DO NOT AUTOMATE` | Not a fit for this workflow as scoped. |
| `INSUFFICIENT EVIDENCE` | The estimate looks fine but the sample cannot support the claim. The result includes roughly how many cases would be needed. |

`INSUFFICIENT EVIDENCE` is the reason this exists — it is the verdict an honest
consultant gives and a dashboard never does. Do not soften it into a maybe.

## How to report a result (do not drift from this)

- **Quote the interval, not the point estimate.** "87.2% [82.5%, 90.8%]" — the
  interval is the finding. A bare "87%" is the thing this plugin exists to stop.
- **The verdict is measured on the lower bound.** Never write "98% precision,
  so it ships" — if the lower bound is 89.3% against a 95% target, it does not
  ship, and the report will say `ASSIST ONLY`. Read the verdict, not the peak.
- **Keep the calibration caveat.** A calibration error above ~0.15 means the
  confidence scale is not a probability — but the operating point still stands,
  because precision at a cut point is measured directly from held-out results.
  Calibration and discrimination are different properties. Say both.
- **Keep self-implicating detail in.** If the operating point was chosen on the
  same cases it is scored on, or the target was picked after seeing the number,
  that belongs in the answer.
- **`needed_n` is actionable, not a complaint.** "Roughly 412 cases to support a
  95% claim at this rate" tells someone what to do next.

## Results file format

One JSON object per line — a plain file a domain expert can build in a
spreadsheet. Only `passed` is required.

```jsonl
{"id": "inv-001", "passed": true,  "confidence": 0.94, "expected": "Acme", "output": "Acme"}
{"id": "inv-002", "passed": false, "confidence": 0.61, "expected": "Borealis", "output": "Boreal", "detail": "truncated vendor"}
{"id": "inv-003", "passed": true,  "confidence": 0.88, "error": "TimeoutError: 30s"}
{"id": "inv-004", "passed": false, "abstained": true}
```

- `confidence` (0–1) is optional but unlocks selective automation — without any
  variation in it, no abstention threshold can be derived and the tool says so.
- `error` marks a crashed case (a failed case, not an aborted run); `abstained`
  marks an explicit abstention, which lands at zero confidence so a threshold
  defers it first.
- `group` on every case folds correlated checks into one trial per group —
  several fields from one document are one draw of the system under test, and
  counting them separately makes the interval narrower than the evidence.
- An optional `target` per run: the accuracy the deployment actually needs
  (default 0.95). The target belongs to the deployment, not to this plugin.

`gonogo_report` with `save_report` writes the report JSON; `gonogo_compare`
pairs two of those by case id, so a run measured today can be checked against
one measured last week.
