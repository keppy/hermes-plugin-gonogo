# gonogo — a Hermes plugin

**47 out of 50 is not 94%.** It lands somewhere between 84% and 98%, so if you
were aiming at 95%, you cannot yet say you got there.

This plugin gives a Hermes agent a decision instead of a number. Ask it whether
something is good enough to ship and it answers with one of five verdicts, the
interval behind it, the confidence threshold that routes uncertain cases to a
human, and — when the sample is simply too small to say — that it is too small
to say.

```bash
hermes plugins install keppy/hermes-plugin-gonogo
hermes plugins enable gonogo
```

Requires `gonogo-eval>=0.3,<0.4`, which Hermes installs for you from the
plugin's `pyproject.toml`. The 0.2 line is not compatible: the grouped
pairing and paired-interval behaviour this plugin reports arrived in 0.3.

## The ecosystem this belongs to

This plugin is the in-session half of a small ecosystem that takes a task
from *which model?* to *ship it or not*:

```
your task ──► evalroute ─ choose a (model, effort) arm;
                │         measured where available, priors marked
                ▼
your cases ──► thomas ── train on labels (encoder) or score_text (RL);
                │         evaluate on untouched cases with gonogo
                ▼
              gonogo ── ship it, test a threshold on fresh cases, or walk away
```

- **[gonogo](https://github.com/keppy/gonogo)** — the library behind this
  plugin, and the root of the map. Any agent, your real cases, a target;
  the verdict comes with the interval behind it.
- **[thomas](https://github.com/keppy/thomas)** — the training harness. RL
  shares `score_text` across training and held-out evaluation; encoder SFT
  instead learns labels and needs a separate held-out evaluation.
- **[evalroute](https://github.com/keppy/hermes-plugin-evalroute)** — the
  routing layer: classify the task, hand back the arm with measured
  costs where available and priors otherwise; collect ratings to prioritize
  the next controlled batch.
- **The Hermes plugins** — the same three, inside your agent's session:
  this one for decisions, [thomas](https://github.com/keppy/hermes-plugin-thomas)
  with a human approval hook on its training tool, and evalroute's `/route`
  before the first turn.

## What it adds

| Tool | The question it answers |
| --- | --- |
| `gonogo_decide` | "Is this good enough to ship?" — from a pass count or a results file |
| `gonogo_report` | "Give me the report artifact" — for a doc, a PR, a pilot review |
| `gonogo_compare` | "Is B actually better than A?" — McNemar on paired cases |

Plus a bundled skill, `gonogo-verdict`, that loads the reporting discipline
with it: quote the interval and not the point estimate, read the verdict off
the *lower bound*, keep the calibration caveat, keep the self-implicating
detail in.

## Why a plugin and not a library

The library already exists — `pip install gonogo-eval`. What a plugin changes is
*who asks*. Any Hermes session can now end a measurement with a defensible call
instead of a plausible-looking percentage, in the same conversation where the
measurement happened, without anyone remembering to go run a script.

## A worked exchange

> **You:** The invoice router got 47 of 50 right. Ship it?
>
> **Agent:** *(calls `gonogo_decide` with passed=47, total=50, target=0.95)*

```
**ASSIST ONLY** — pass rate 94.0% [83.8%, 97.9%] is below the 95% target
and no confident subset reaches it; useful as a draft-generator, not as an
unattended step

Pass rate 94.0% [83.8%, 97.9%] over 50 cases (47 passed), target 95%
Note: Every case reported the same confidence, so no abstention threshold can be
derived. Emit a real per-case confidence to unlock selective automation.
```

Two things that matter there. The interval reaches down to 83.8%, so 94% is not
the number the decision gets made on. And the tool noticed the results carried no
per-case confidence — which is what a review threshold would have been built
from, so it says so rather than silently reporting an overall rate.

Give it a results file with confidence on it instead and the same call finds the
operating point:

```
**AUTOMATE WITH REVIEW** — overall pass rate 85.0% [73.9%, 91.9%] misses the 90%
target; a candidate threshold at confidence 0.86 reaches 100.0% precision on 85% of cases on this selection set, but needs a fresh holdout before deployment

Candidate operating point (fresh holdout required): abstain below 0.86 → 85% cases selected at 100.0% precision 100.0% [93.0%, 100.0%], 9 cases to review
Calibration error 0.10
Note: The 0.86 threshold was chosen by searching this same case set, so its
precision is optimistically biased. Re-measure it on fresh cases before relying on it.
```

That last note is the plugin's own caveat, not a user's: a threshold found by
searching the case set it is scored on is biased upward. `can_automate` remains
false for this candidate; holdout signoff is a separate step.

## The results file

One JSON object per line. `passed` alone is enough for a one-run verdict.
For `gonogo_compare`, every row in both runs needs the same stable, explicit
`id` (and matching group membership if grouped); generated row positions are
not paired evidence. The file is plain enough to build in a spreadsheet.

```jsonl
{"id": "inv-001", "passed": true,  "confidence": 0.97, "expected": "Acme Supply", "output": "Acme Supply"}
{"id": "inv-006", "passed": false, "confidence": 0.42, "expected": "Acme Supply", "output": "Cinder Works", "detail": "normalized the trading name to its parent entity"}
{"id": "inv-007", "passed": false, "error": "TimeoutError: 30s"}
{"id": "inv-008", "passed": false, "abstained": true}
```

- `confidence` (0–1) is optional for an entire file, but mixed missing and present
  values are rejected; it is what unlocks a candidate review threshold.
- `error` is a crashed case — a failure, not an aborted run. `abstained` lands at
  zero confidence, so a threshold defers it first.
- `group` on every case folds correlated checks into one trial per group.
- `examples/invoice_routing.jsonl` is a 60-case synthetic set to try it on.

`gonogo_report` with `save_report` writes the report JSON, and `gonogo_compare`
pairs two of those by case id (or by group id with matching case membership) —
so a run measured today can be checked against one measured last week.

## What it can touch

Three tools, and nothing else: no hooks, no middleware, no environment
variables, no credentials, no network. Count-only calls need no file; results
calls read the path you give them and optionally write report JSON or HTML when
requested. The whole blast radius is the one dependency and those opt-in files.

## Development

```bash
uv venv .venv && uv pip install --python .venv/Scripts/python.exe gonogo-eval pytest pyyaml
.venv/Scripts/python.exe -m pytest tests -q

hermes plugins validate .     # the catalog admission gate, including the security scan
hermes plugins doctor . --ci  # discovery, manifest, import, registration
```

The tests assert the verdicts themselves — that 47/50 at a 95% target is
`ASSIST ONLY`, that the same 47/50 at 90% is `INSUFFICIENT EVIDENCE` needing
about 204 cases, and that a 3-point gap on 60 cases is not an improvement.

MIT. The statistics are [gonogo](https://github.com/keppy/gonogo)'s; this plugin
is the surface that lets an agent ask for them.
