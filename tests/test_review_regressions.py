"""Plugin contract checks: strict rows, grouped pairing, strict JSON and holdout caveat."""
import json

import pytest

import tools


def write(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None])
def test_nonboolean_passed_is_rejected_in_all_tools(tmp_path, bad):
    path = write(tmp_path, "bad.jsonl", [{"id": "x", "passed": bad}])
    assert "passed must be a boolean" in json.loads(tools.gonogo_decide({"results_path": path}))["error"]
    assert "passed must be a boolean" in json.loads(tools.gonogo_report({"results_path": path}))["error"]
    assert "passed must be a boolean" in json.loads(tools.gonogo_compare(
        {"report_a": path, "report_b": path}))["error"]


def test_mixed_confidence_rejected(tmp_path):
    path = write(tmp_path, "mixed.jsonl", [{"id": "a", "passed": True, "confidence": 0.9},
                                            {"id": "b", "passed": False}])
    for tool in (tools.gonogo_decide, tools.gonogo_report):
        assert "mixed missing and present confidence" in json.loads(
            tool({"results_path": path}))["error"]


def test_grouped_report_and_compare_are_group_based(tmp_path):
    a = write(tmp_path, "a.jsonl", [
        {"id": "x", "group": "g1", "passed": True, "confidence": 0.8},
        {"id": "y", "group": "g1", "passed": False, "confidence": 0.4},
        {"id": "x", "group": "g2", "passed": True, "confidence": 0.8},
        {"id": "y", "group": "g2", "passed": True, "confidence": 0.8},
    ])
    b = write(tmp_path, "b.jsonl", [
        {"id": "y", "group": "g1", "passed": True, "confidence": 0.4},
        {"id": "x", "group": "g1", "passed": True, "confidence": 0.8},
        {"id": "y", "group": "g2", "passed": True, "confidence": 0.8},
        {"id": "x", "group": "g2", "passed": True, "confidence": 0.8},
    ])
    report = json.loads(tools.gonogo_report({"results_path": a, "level": 0.90}))
    assert report["n_passed"] == 3 and report["n_trials_passed"] == 1
    assert "| Stated confidence | Groups |" in report["markdown"]
    assert "1/2 groups" not in report["markdown"]  # case and group counts separately
    cmp = json.loads(tools.gonogo_compare({"report_a": a, "report_b": b}))
    assert cmp["unit"] == "groups" and cmp["n_shared"] == 2 and cmp["only_b"] == 1
    assert "shared groups" in cmp["markdown"]
    changed = write(tmp_path, "changed.jsonl", [
        {"id": "other", "group": "g1", "passed": True},
        {"id": "x", "group": "g2", "passed": True},
        {"id": "y", "group": "g2", "passed": True},
    ])
    assert "different case membership" in json.loads(tools.gonogo_compare(
        {"report_a": a, "report_b": changed}))["error"]


def test_candidate_threshold_does_not_authorize_ship_and_strict_saved_json(tmp_path):
    rows = ([{"id": f"p{i}", "passed": True, "confidence": 0.9} for i in range(60)]
            + [{"id": f"f{i}", "passed": False, "confidence": 0.2} for i in range(20)])
    path = write(tmp_path, "cases.jsonl", rows)
    out = json.loads(tools.gonogo_decide({"results_path": path, "target": 0.9}))
    assert out["verdict"] == "AUTOMATE WITH REVIEW"
    assert out["can_automate"] is False
    assert "fresh holdout" in out["reason"]
    save = tmp_path / "report.json"
    report = json.loads(tools.gonogo_report({"results_path": path, "target": 0.9,
                                              "save_report": str(save)}))
    assert "fresh holdout required" in report["markdown"]
    json.dumps(report, allow_nan=False)
    json.dumps(json.loads(save.read_text(encoding="utf-8")), allow_nan=False)


def test_count_only_group_unit_does_not_claim_case_counts():
    out = json.loads(tools.gonogo_decide({"passed": 9, "total": 10, "unit": "groups"}))
    assert out["unit"] == "groups" and out["n_cases"] is None
    assert "cases passed" not in out["markdown"]


def test_compare_raw_errors_and_abstentions_are_failures(tmp_path):
    a = write(tmp_path, "a.jsonl", [{"id": "x", "passed": True, "error": "timeout"},
                                    {"id": "y", "passed": True, "abstained": True}])
    b = write(tmp_path, "b.jsonl", [{"id": "x", "passed": True},
                                    {"id": "y", "passed": True}])
    out = json.loads(tools.gonogo_compare({"report_a": a, "report_b": b}))
    assert out["only_b"] == 2 and out["rate_a"] == 0.0


def test_comparison_never_pairs_row_positions_without_explicit_ids(tmp_path):
    a = write(tmp_path, "a.jsonl", [{"input": "unrelated a", "passed": False}])
    b = write(tmp_path, "b.jsonl", [{"input": "unrelated b", "passed": True}])
    assert "explicit stable" in json.loads(tools.gonogo_compare(
        {"report_a": a, "report_b": b}))["error"]
    saved = tmp_path / "saved.json"
    tools.gonogo_report({"results_path": a, "save_report": str(saved)})
    assert "explicit stable" in json.loads(tools.gonogo_compare(
        {"report_a": str(saved), "report_b": str(saved)}))["error"]


@pytest.mark.parametrize("tool,args", [
    (tools.gonogo_decide, {"passed": 9, "total": 10, "target": "garbage"}),
    (tools.gonogo_decide, {"passed": 9, "total": 10, "level": None}),
])
def test_malformed_supplied_probability_never_defaults(tool, args):
    out = json.loads(tool(args))
    assert "must be a number in (0, 1)" in out["error"]


def test_confidence_free_answer_and_abstention_is_valid(tmp_path):
    path = write(tmp_path, "abstain.jsonl", [
        {"id": "a", "passed": True},
        {"id": "b", "passed": False, "abstained": True},
    ])
    for tool in (tools.gonogo_decide, tools.gonogo_report):
        out = json.loads(tool({"results_path": path}))
        assert out["n_passed"] == 1 and out["n_trials"] == 2

