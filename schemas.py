"""Tool schemas — what the model reads to decide when to call each tool."""

_TARGET = {
    "type": "number",
    "description": (
        "The accuracy the deployment needs, as a fraction (0.95 = 95%). "
        "The verdict is measured against this, on the interval's LOWER bound. "
        "Default 0.95."
    ),
}

_LEVEL = {
    "type": "number",
    "description": "Confidence level for the intervals, as a fraction. Default 0.95.",
}

GONOGO_DECIDE = {
    "name": "gonogo_decide",
    "description": (
        "Decide whether a measured accuracy is good enough to ship, and say so "
        "honestly at pilot sample sizes. Returns one of: AUTOMATE, AUTOMATE WITH "
        "REVIEW, ASSIST ONLY, DO NOT AUTOMATE, INSUFFICIENT EVIDENCE — with the "
        "pass rate's Wilson interval, the confidence threshold that maximizes "
        "candidate automated volume while keeping same-set precision's lower bound above the target; a fresh holdout is required before shipping, "
        "calibration error, and how many cases would be needed to support the "
        "claim. "
        "Call this whenever someone is about to read a point estimate as an "
        "answer — '47 of 50 passed, that's 94%' — or asks whether an agent is "
        "good enough to put in front of real work. Give either passed + total, "
        "or results_path for a per-case results file. "
        "Do NOT use it to compare two agents (use gonogo_compare) or to produce "
        "the full report artifact (use gonogo_report)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "passed": {
                "type": "integer",
                "description": "Number of cases that passed. Use with total.",
            },
            "total": {
                "type": "integer",
                "description": "Number of cases evaluated. Use with passed.",
            },
            "results_path": {
                "type": "string",
                "description": (
                    "Path to a results file: JSONL with one object per case "
                    "({id, passed, confidence?}) or a gonogo report JSON. "
                    "Use instead of passed + total when per-case confidence "
                    "exists, since confidence is what unlocks the review "
                    "threshold."
                ),
            },
            "target": _TARGET,
            "level": _LEVEL,
            "task": {
                "type": "string",
                "description": "Name of the task being evaluated, for the report wording.",
            },
            "unit": {
                "type": "string",
                "description": (
                    "What one trial is called: 'cases' (default) or 'groups'. "
                    "Only meaningful for passed + total; a results file with a "
                    "'group' on every case is folded to one trial per group "
                    "automatically."
                ),
            },
        },
        "required": [],
    },
}

GONOGO_REPORT = {
    "name": "gonogo_report",
    "description": (
        "Build the full gonogo score report for a results file: the verdict, "
        "every rate with its interval, the risk–coverage table (candidate coverage "
        "at each confidence threshold and how many trials land on a "
        "human), the reliability/calibration table, and the worst failures. "
        "Use when the deliverable is the artifact — a report to paste into a "
        "doc, PR or pilot review — rather than a yes/no answer. "
        "Set save_report to write the report JSON, which gonogo_compare can "
        "pair against a later run. Set write_html for a standalone HTML report."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "results_path": {
                "type": "string",
                "description": (
                    "Path to a results file: JSONL with one object per case "
                    "({id, passed, confidence?, expected?, output?, score?, "
                    "group?, error?, abstained?}) or a previously saved gonogo "
                    "report JSON."
                ),
            },
            "task": {
                "type": "string",
                "description": "Task name for the report title. Defaults to the file name.",
            },
            "target": _TARGET,
            "level": _LEVEL,
            "show_failures": {
                "type": "integer",
                "description": "How many failed cases to list in the report. Default 5, 0 for none.",
            },
            "save_report": {
                "type": "string",
                "description": (
                    "Path to write the report JSON to. Do this whenever the run "
                    "might be compared against another one later — gonogo pairs "
                    "runs by case id (or group id for grouped trials)."
                ),
            },
            "write_html": {
                "type": "string",
                "description": "Path to write a standalone HTML version of the report to.",
            },
            "include_report_json": {
                "type": "boolean",
                "description": (
                    "Also return the full report JSON (per-case outcomes) inline. "
                    "Default false — it is large; prefer save_report."
                ),
            },
        },
        "required": ["results_path"],
    },
}

GONOGO_COMPARE = {
    "name": "gonogo_compare",
    "description": (
        "Test whether one agent is actually better than another on the cases "
        "they share — McNemar's test on paired case or group outcomes, reporting the "
        "difference in pass rate with an interval and a p-value. "
        "Call this when a change is claimed to be an improvement, BEFORE "
        "agreeing to it: on pilot-sized samples a 3-point gap is usually "
        "indistinguishable from noise, and 'no detectable difference' is the "
        "useful answer. "
        "Takes two results files or two saved gonogo report JSONs that share "
        "case ids (or group ids with matching membership); trials only one side ran are ignored. For a single run's "
        "ship / don't-ship call, use gonogo_decide instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "report_a": {
                "type": "string",
                "description": "Path to the baseline run (results file or saved report JSON).",
            },
            "report_b": {
                "type": "string",
                "description": "Path to the candidate run, sharing case ids with report_a.",
            },
            "level": _LEVEL,
        },
        "required": ["report_a", "report_b"],
    },
}
