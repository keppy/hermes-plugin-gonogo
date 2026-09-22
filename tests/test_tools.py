"""Tests for the gonogo plugin's tool handlers.

Handlers are called the way Hermes calls them: a dict of args, a JSON string
back. Run with gonogo importable:

    python -m pytest tests
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools  # noqa: E402

pytest.importorskip("gonogo", reason="gonogo-eval must be installed")


def write(tmp_path: Path, name: str, rows: list[dict]) -> str:
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(path)


def rows_for(passed: int, failed: int, confidence: float | None = None) -> list[dict]:
    rows = [{"id": f"p{i}", "passed": True} for i in range(passed)]
    rows += [{"id": f"f{i}", "passed": False} for i in range(failed)]
    if confidence is not None:
        for row in rows:
            row["confidence"] = confidence
    return rows


# --------------------------------------------------------------------------- #
# gonogo_decide


def test_counts_below_target_with_no_confidence_is_assist_only():
    """47/50 at a 95% target: 94% is under the bar, and with no confidence
    signal there is no subset to route to a human."""
    out = json.loads(tools.gonogo_decide({"passed": 47, "total": 50, "target": 0.95}))
    assert out["verdict"] == "ASSIST ONLY"
    assert out["can_automate"] is False
    assert out["needed_n"] is None
    assert out["pass_rate"]["low"] == pytest.approx(0.838, abs=0.001)


def test_point_above_target_with_a_wide_interval_is_insufficient_evidence():
    """The headline case: 94% observed against a 90% target, but the interval
    reaches down to 83.8%, so the sample cannot support the claim."""
    out = json.loads(tools.gonogo_decide({"passed": 47, "total": 50, "target": 0.90}))
    assert out["verdict"] == "INSUFFICIENT EVIDENCE"
    assert out["pass_rate"]["point"] > 0.90 > out["pass_rate"]["low"]
    assert out["needed_n"] == 204


def test_counts_clear_a_low_target():
    """95% on 100 cases has a lower bound of 88.8%, which clears an 85% bar."""
    out = json.loads(tools.gonogo_decide({"passed": 95, "total": 100, "target": 0.85}))
    assert out["verdict"] == "AUTOMATE"
    assert out["can_automate"] is True


def test_weak_result_is_do_not_automate():
    out = json.loads(tools.gonogo_decide({"passed": 3, "total": 10}))
    assert out["verdict"] == "DO NOT AUTOMATE"


def test_point_estimate_is_never_the_answer():
    """94% point estimate, 95% target: the interval is what decides."""
    out = json.loads(tools.gonogo_decide({"passed": 47, "total": 50}))
    assert out["pass_rate"]["point"] == pytest.approx(0.94, abs=0.005)
    assert out["pass_rate"]["text"].startswith("94.0% [")
    assert out["verdict"] != "AUTOMATE"


def test_no_confidence_signal_is_reported_not_hidden():
    out = json.loads(tools.gonogo_decide({"passed": 47, "total": 50}))
    assert out["operating_point"] is None
    assert out["calibration_error"] is None
    assert any("confidence" in note for note in out["notes"])


def test_bad_counts_are_an_error_not_a_crash():
    out = json.loads(tools.gonogo_decide({"passed": 60, "total": 50}))
    assert "error" in out


def test_target_out_of_range_is_an_error():
    out = json.loads(tools.gonogo_decide({"passed": 10, "total": 10, "target": 1.5}))
    assert "error" in out


def test_missing_args_is_an_error():
    assert "error" in json.loads(tools.gonogo_decide({}))


def test_results_path_with_confidence_unlocks_an_operating_point(tmp_path):
    rows = rows_for(180, 20)
    for i, row in enumerate(rows):
        row["confidence"] = 0.95 if i < 180 else 0.4
    path = write(tmp_path, "results.jsonl", rows)
    out = json.loads(tools.gonogo_decide({"results_path": path, "target": 0.9}))
    assert out["operating_point"] is not None
    assert out["operating_point"]["coverage"] < 1.0
    assert out["operating_point"]["n_deferred"] >= 20
    assert out["n_cases"] == 200


def test_missing_file_is_an_error():
    out = json.loads(tools.gonogo_decide({"results_path": "C:/nope/never.jsonl"}))
    assert "error" in out


def test_row_without_passed_is_an_error(tmp_path):
    path = write(tmp_path, "bad.jsonl", [{"id": "a", "confidence": 0.5}])
    assert "error" in json.loads(tools.gonogo_decide({"results_path": path}))


def test_bad_confidence_is_an_error(tmp_path):
    path = write(tmp_path, "bad.jsonl", [{"id": "a", "passed": True, "confidence": 1.4}])
    assert "error" in json.loads(tools.gonogo_decide({"results_path": path}))


# --------------------------------------------------------------------------- #
# groups


def test_grouped_rows_are_folded_to_one_trial_per_group(tmp_path):
    rows = [
        {"id": "g1-a", "passed": True, "group": "g1"},
        {"id": "g1-b", "passed": True, "group": "g1"},
        {"id": "g2-a", "passed": True, "group": "g2"},
        {"id": "g2-b", "passed": False, "group": "g2"},
    ]
    path = write(tmp_path, "grouped.jsonl", rows)
    out = json.loads(tools.gonogo_decide({"results_path": path, "target": 0.5}))
    assert out["unit"] == "groups"
    assert out["n_trials"] == 2          # two groups, not four cases
    assert out["n_cases"] == 4           # the case count is context
    assert out["n_passed"] == 1          # g2 fails because one case in it failed


def test_mixed_grouping_is_an_error(tmp_path):
    rows = [{"id": "a", "passed": True, "group": "g1"},
            {"id": "b", "passed": True}]
    path = write(tmp_path, "mixed.jsonl", rows)
    out = json.loads(tools.gonogo_decide({"results_path": path}))
    assert "error" in out and "group" in out["error"]


# --------------------------------------------------------------------------- #
# gonogo_report


def test_report_returns_markdown_and_saves_a_comparable_json(tmp_path):
    rows = rows_for(90, 10)
    for i, row in enumerate(rows):
        row["confidence"] = 0.9 if i < 90 else 0.3
    path = write(tmp_path, "results.jsonl", rows)
    save = tmp_path / "out" / "report.json"
    out = json.loads(tools.gonogo_report({
        "results_path": path, "task": "invoice routing", "target": 0.85,
        "save_report": str(save), "show_failures": 3}))

    assert out["task"] == "invoice routing"
    assert "Score report" in out["markdown"]
    assert out["summary"].startswith("invoice routing:")
    assert Path(out["saved_report"]).is_file()

    saved = json.loads(save.read_text(encoding="utf-8"))
    assert len(saved["cases"]) == 100
    assert saved["cases"][0]["id"] == "p0"


def test_report_writes_html(tmp_path):
    path = write(tmp_path, "results.jsonl", rows_for(8, 2))
    html = tmp_path / "report.html"
    out = json.loads(tools.gonogo_report({"results_path": path, "write_html": str(html)}))
    assert Path(out["html_path"]).is_file()
    assert "<html" in html.read_text(encoding="utf-8").lower()


def test_report_reads_back_a_saved_report_json(tmp_path):
    path = write(tmp_path, "results.jsonl", rows_for(18, 2))
    save = tmp_path / "report.json"
    first = json.loads(tools.gonogo_report({"results_path": path, "save_report": str(save)}))
    second = json.loads(tools.gonogo_report({"results_path": str(save)}))
    assert second["n_cases"] == first["n_cases"]
    assert second["verdict"] == first["verdict"]


def test_report_json_is_opt_in(tmp_path):
    path = write(tmp_path, "results.jsonl", rows_for(8, 2))
    out = json.loads(tools.gonogo_report({"results_path": path}))
    assert "report" not in out


# --------------------------------------------------------------------------- #
# gonogo_compare


def test_compare_calls_a_real_difference(tmp_path):
    a = write(tmp_path, "a.jsonl", [{"id": f"c{i}", "passed": i < 60} for i in range(100)])
    b = write(tmp_path, "b.jsonl", [{"id": f"c{i}", "passed": i < 90} for i in range(100)])
    out = json.loads(tools.gonogo_compare({"report_a": a, "report_b": b}))
    assert out["n_shared"] == 100
    assert out["significant"] is True
    assert out["difference"] == pytest.approx(0.30, abs=0.01)


def test_compare_refuses_a_noise_gap(tmp_path):
    """Three points on 60 cases is not an improvement."""
    a = write(tmp_path, "a.jsonl", [{"id": f"c{i}", "passed": i < 51} for i in range(60)])
    b = write(tmp_path, "b.jsonl", [{"id": f"c{i}", "passed": i < 54} for i in range(60)])
    out = json.loads(tools.gonogo_compare({"report_a": a, "report_b": b}))
    assert out["significant"] is False
    assert "no detectable difference" in out["summary"]


def test_compare_pairs_saved_reports(tmp_path):
    a = write(tmp_path, "a.jsonl", [{"id": f"c{i}", "passed": i < 10} for i in range(20)])
    b = write(tmp_path, "b.jsonl", [{"id": f"c{i}", "passed": i < 19} for i in range(20)])
    sa, sb = tmp_path / "a.json", tmp_path / "b.json"
    tools.gonogo_report({"results_path": a, "save_report": str(sa)})
    tools.gonogo_report({"results_path": b, "save_report": str(sb)})
    out = json.loads(tools.gonogo_compare({"report_a": str(sa), "report_b": str(sb)}))
    assert out["n_shared"] == 20
    assert out["only_b"] > 0


def test_compare_with_unmatched_ids_is_an_error(tmp_path):
    a = write(tmp_path, "a.jsonl", [{"id": "x", "passed": True}])
    b = write(tmp_path, "b.jsonl", [{"id": "y", "passed": True}])
    out = json.loads(tools.gonogo_compare({"report_a": a, "report_b": b}))
    assert "error" in out
