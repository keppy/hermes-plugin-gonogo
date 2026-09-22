"""Tool handlers for the gonogo plugin.

Every handler returns a JSON string and never raises: a missing file, a bad
row, or an uninstalled dependency comes back as ``{"error": ...}`` for the
model to read and act on.

The statistics are gonogo's, not this plugin's. Rows are rebuilt into real
``Case``/``Prediction``/``CaseResult`` objects and handed to the same public
calls ``gonogo.evaluate`` uses (``group_results`` + ``decide`` + ``Report``),
so a verdict from here is the verdict the library would give.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

__all__ = ["gonogo_decide", "gonogo_report", "gonogo_compare"]

_module: Any = None


def _gonogo():
    """Import gonogo on first use.

    Declared in pyproject.toml, but imported lazily so registration (and
    ``hermes plugins validate``) still works where the dependency was skipped
    with ``--no-deps``.
    """
    global _module
    if _module is None:
        import gonogo as mod

        _module = mod
    return _module


# --------------------------------------------------------------------------- #
# helpers


def _fail(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, **extra}, ensure_ascii=False)


def _clean(value: Any) -> Any:
    """NaN and infinity are not valid JSON — report them as null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _load_rows(raw_path: Any) -> tuple[list[dict], dict | None]:
    """Read a results file.

    Accepts either a JSONL file with one object per case, or a single JSON
    object — a gonogo report payload (``Report.to_dict()``), whose ``cases``
    list is the per-case outcome record. Returns ``(rows, report_payload)``.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("no results path given")
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise ValueError(f"{path} is not a file")

    text = path.read_text(encoding="utf-8")
    payload: dict | None = None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        doc = None

    if isinstance(doc, dict) and isinstance(doc.get("cases"), list):
        payload = doc
        rows = [row for row in doc["cases"] if isinstance(row, dict)]
    else:
        rows = []
        for lineno, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{lineno}: each line must be a JSON object")
            rows.append(row)

    if not rows:
        raise ValueError(f"{path}: no cases found")
    return rows, payload


def _to_results(rows: list[dict], g) -> list[Any]:
    """Rebuild per-case rows into gonogo CaseResults.

    Mirrors ``gonogo.evaluate``: an agent error is a failed case (not an
    aborted run) and an explicit abstention is a failure at zero confidence,
    so it is deferred first by any threshold.
    """
    results = []
    for i, row in enumerate(rows, 1):
        if "passed" not in row:
            raise ValueError(f"case {row.get('id') or i!r}: missing required key 'passed'")
        case_id = str(row.get("id") or f"case-{i}")
        group = row.get("group")
        case = g.Case(
            input=row.get("input", case_id),
            expected=row.get("expected", ""),
            id=case_id,
            group=None if group is None else str(group),
        )

        if row.get("error"):
            detail = f"agent error: {row['error']}"
            results.append(g.CaseResult(
                case, g.Prediction(output=None, error=str(row["error"])),
                passed=False, score=0.0, detail=detail))
            continue
        if row.get("abstained"):
            results.append(g.CaseResult(
                case, g.Prediction(row.get("output"), confidence=0.0, abstained=True),
                passed=False, score=0.0, detail="agent abstained"))
            continue

        confidence = row.get("confidence")
        if confidence is not None:
            confidence = _as_float(confidence, -1.0)
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(
                    f"case {case_id!r}: confidence must be in [0, 1], got {row['confidence']!r}")
        passed = bool(row["passed"])
        score = row.get("score")
        score = _as_float(score, 1.0 if passed else 0.0)
        metadata = {k: v for k, v in row.items()
                    if k not in ("id", "group", "passed", "confidence", "score",
                                 "detail", "error", "abstained", "output", "input", "expected")}
        case.metadata = metadata
        results.append(g.CaseResult(
            case, g.Prediction(row.get("output", passed), confidence=confidence),
            passed=passed, score=score, detail=str(row.get("detail", ""))))
    return results


def _trials(rows: list[dict], g) -> tuple[list[tuple[float, bool]], str, int | None, list[Any]]:
    """Per-trial (confidence, passed), folding groups exactly as evaluate does.

    Several checks on one run of a scenario share a draw of the system under
    test, so counting them as independent trials narrows the interval below
    what the evidence supports. One trial per group, passing only if every
    case in it passed.
    """
    results = _to_results(rows, g)
    grouped = [r.case.group is not None for r in results]
    if all(grouped):
        groups = g.group_results(results)
        trials = [(min(r.confidence for r in rs), all(r.passed for r in rs))
                  for rs in groups.values()]
        return trials, "groups", len(groups), results
    if any(grouped):
        raise ValueError(
            "some cases carry a group and some do not; gonogo has no honest reading for a "
            "mixed set — put a group on every case, or on none")
    return [(r.confidence, r.passed) for r in results], "cases", None, results


def _decision_dict(decision, *, task: str, n_cases: int, n_passed: int) -> dict:
    point = decision.pass_rate
    op = decision.operating_point
    return {
        "task": task,
        "verdict": decision.verdict.value,
        "can_automate": decision.can_automate,
        "reason": decision.reason,
        "target": decision.target,
        "unit": decision.unit,
        "n_trials": point.n,
        "n_cases": n_cases,
        "n_passed": n_passed,
        "pass_rate": {
            "point": point.point, "low": point.low, "high": point.high,
            "level": point.level, "n": point.n, "text": str(point),
        },
        "operating_point": None if op is None else {
            "threshold": op.threshold,
            "coverage": op.coverage,
            "n_covered": op.n_covered,
            "n_deferred": op.n_deferred,
            "precision": op.precision.point,
            "precision_low": op.precision.low,
            "precision_high": op.precision.high,
            "precision_text": str(op.precision),
        },
        "calibration_error": _clean(decision.calibration_error),
        "needed_n": decision.needed_n,
        "notes": list(decision.notes),
    }


def _decision_markdown(d: dict) -> str:
    lines = [f"**{d['verdict']}** — {d['reason']}", ""]
    unit = d["unit"]
    lines.append(
        f"Pass rate {d['pass_rate']['text']} over {d['n_trials']} {unit} "
        f"({d['n_passed']}/{d['n_cases']} cases passed), target {d['target']:.0%}")
    op = d["operating_point"]
    if op:
        lines.append(
            f"Operating point: abstain below {op['threshold']:.2f} → {op['coverage']:.0%} "
            f"handled at {op['precision']:.1%} precision {op['precision_text']}, "
            f"{op['n_deferred']} to review")
    if d["calibration_error"] is not None:
        lines.append(f"Calibration error {d['calibration_error']:.2f}")
    if d["needed_n"]:
        lines.append(f"Needs about {d['needed_n']} {unit} to support the claim at this target")
    for note in d["notes"]:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def _task_name(path: Any, given: Any, payload: dict | None) -> str:
    if isinstance(given, str) and given.strip():
        return given.strip()
    if payload and isinstance(payload.get("task"), str) and payload["task"]:
        return payload["task"]
    return Path(str(path)).stem


def _outcomes_payload(raw_path: Any) -> dict:
    """A ``{cases: [{id, passed}]}`` payload — what gonogo.compare pairs on."""
    rows, payload = _load_rows(raw_path)
    if payload is not None:
        return payload
    cases = []
    for i, row in enumerate(rows, 1):
        if "passed" not in row:
            raise ValueError(f"case {row.get('id') or i!r}: missing required key 'passed'")
        cases.append({"id": str(row.get("id") or f"case-{i}"), "passed": bool(row["passed"])})
    return {"cases": cases}


# --------------------------------------------------------------------------- #
# tools


def gonogo_decide(args: dict, **kwargs: Any) -> str:
    """Is this good enough to ship? Counts, or a per-case results file."""
    try:
        g = _gonogo()
    except ImportError as exc:
        return _fail(f"gonogo is not importable in this environment ({exc}); "
                     "install gonogo-eval>=0.2 into the Hermes venv")

    try:
        target = _as_float(args.get("target"), 0.95)
        level = _as_float(args.get("level"), 0.95)
        if not 0.0 < target < 1.0:
            return _fail(f"target must be in (0, 1), got {target}")
        if not 0.0 < level < 1.0:
            return _fail(f"level must be in (0, 1), got {level}")

        path = args.get("results_path")
        if isinstance(path, str) and path.strip():
            rows, payload = _load_rows(path)
            trials, unit, n_groups, results = _trials(rows, g)
            n_cases = len(results)
            task = _task_name(path, args.get("task"), payload)
        else:
            passed = _as_int(args.get("passed"))
            total = _as_int(args.get("total"))
            if passed is None or total is None:
                return _fail("give either results_path, or both passed and total")
            if total <= 0 or not 0 <= passed <= total:
                return _fail(f"need total > 0 and 0 <= passed <= total, "
                             f"got passed={passed}, total={total}")
            trials = [(1.0, True)] * passed + [(1.0, False)] * (total - passed)
            unit = str(args.get("unit") or "cases")
            n_groups = None
            n_cases = total
            task = str(args.get("task") or "task")

        decision = g.decide(trials, target=target, level=level, unit=unit)
        if n_groups is not None:
            decision.n_groups = n_groups
        n_passed = sum(1 for _, passed_ in trials if passed_)

        out = _decision_dict(decision, task=task, n_cases=n_cases, n_passed=n_passed)
        out["markdown"] = _decision_markdown(out)
        return json.dumps(out, ensure_ascii=False)
    except ValueError as exc:
        return _fail(str(exc))
    except Exception as exc:  # never raise out of a tool handler
        return _fail(f"{type(exc).__name__}: {exc}")


def gonogo_report(args: dict, **kwargs: Any) -> str:
    """The full report artifact for a results file."""
    try:
        g = _gonogo()
    except ImportError as exc:
        return _fail(f"gonogo is not importable in this environment ({exc}); "
                     "install gonogo-eval>=0.2 into the Hermes venv")

    try:
        path = args.get("results_path")
        rows, payload = _load_rows(path)
        target = _as_float(args.get("target"), 0.95)
        level = _as_float(args.get("level"), 0.95)
        if not 0.0 < target < 1.0:
            return _fail(f"target must be in (0, 1), got {target}")
        show_failures = _as_int(args.get("show_failures"))
        show_failures = 5 if show_failures is None else max(0, show_failures)

        trials, unit, n_groups, results = _trials(rows, g)
        decision = g.decide(trials, target=target, level=level, unit=unit)
        if n_groups is not None:
            decision.n_groups = n_groups

        task = _task_name(path, args.get("task"), payload)
        report = g.Report(
            task=task, results=results, decision=decision,
            metadata={"source": "hermes-plugin-gonogo", "group_rule": "auto"})

        n_passed = sum(1 for _, passed_ in trials if passed_)
        out = _decision_dict(decision, task=task, n_cases=len(results), n_passed=n_passed)
        out["summary"] = report.summary()
        out["markdown"] = report.markdown(show_failures=show_failures)

        save = args.get("save_report")
        if isinstance(save, str) and save.strip():
            dest = Path(save).expanduser()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
                            encoding="utf-8")
            out["saved_report"] = str(dest)

        html_path = args.get("write_html")
        if isinstance(html_path, str) and html_path.strip():
            dest = Path(html_path).expanduser()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(report.html(show_failures=show_failures), encoding="utf-8")
            out["html_path"] = str(dest)

        if args.get("include_report_json"):
            out["report"] = report.to_dict()

        return json.dumps(out, ensure_ascii=False)
    except ValueError as exc:
        return _fail(str(exc))
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {exc}")


def gonogo_compare(args: dict, **kwargs: Any) -> str:
    """Is B actually better than A on the cases they share?"""
    try:
        g = _gonogo()
    except ImportError as exc:
        return _fail(f"gonogo is not importable in this environment ({exc}); "
                     "install gonogo-eval>=0.2 into the Hermes venv")

    try:
        level = _as_float(args.get("level"), 0.95)
        if not 0.0 < level < 1.0:
            return _fail(f"level must be in (0, 1), got {level}")
        a = _outcomes_payload(args.get("report_a"))
        b = _outcomes_payload(args.get("report_b"))
        cmp = g.compare(a, b, level=level)
        return json.dumps({
            "n_shared": cmp.n_shared,
            "rate_a": cmp.rate_a,
            "rate_b": cmp.rate_b,
            "difference": cmp.difference,
            "difference_low": cmp.low,
            "difference_high": cmp.high,
            "level": cmp.level,
            "discordant": cmp.discordant,
            "only_a": cmp.only_a,
            "only_b": cmp.only_b,
            "p_value": cmp.p_value,
            "exact": cmp.exact,
            "significant": cmp.significant,
            "summary": cmp.summary(),
            "markdown": f"**{'Distinguishable' if cmp.significant else 'Not distinguishable'}**\n\n"
                        f"```\n{cmp.summary()}\n```\n\n{cmp}",
        }, ensure_ascii=False)
    except ValueError as exc:
        return _fail(str(exc))
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {exc}")
