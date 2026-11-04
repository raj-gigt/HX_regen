"""Run the documented JSON examples through the application's real adapters."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from core.contracts import ModuleInput
from core.results import TerminalResultPresenter
from core.selection import select_module
from main import build_registry

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"


def load_manifest():
    return json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))["cases"]


def run_case(case, registry=None):
    """Check routing, dispatch, and native completion; never treat a mock as a design."""
    registry = registry or build_registry()
    payload = json.loads((EXAMPLES / case["file"]).read_text(encoding="utf-8"))
    original = copy.deepcopy(payload)
    decision = select_module(case["routing_answers"])
    if decision.module_id != case["module_id"]:
        raise AssertionError(f"Route selected {decision.module_id}, expected {case['module_id']}")
    if case["case_type"] == "routing_only":
        if payload.get("case_type") != "routing_only":
            raise AssertionError("Placeholder example must be explicitly marked routing_only.")
        return {"file": case["file"], "module_id": decision.module_id, "case_type": "routing_only",
                "passed": True, "status": "routing_only", "route": decision.path_id,
                "note": "Selection verified; no engineering calculation executed."}, None
    kind = case["input_kind"]
    if kind == "module_values":
        values = copy.deepcopy(payload)
        if values.get("selected_subtype") != decision.subtype:
            raise AssertionError("Regenerator payload subtype disagrees with routing answers.")
    else:
        values = {kind: payload}
    values.update(routing_answers=case["routing_answers"], selected_subtype=decision.subtype)
    if kind == "evaporator_payload":
        equipment = payload["equipment_key"]
        allowed = {"falling_film"} if decision.subtype == "Forced-Circulation-or-Falling-Film" else {
            "kettle", "horizontal_thermosyphon", "vertical_thermosyphon"}
        if equipment not in allowed:
            raise AssertionError("Evaporator example is not selectable under its routing answers.")
        values.update(equipment_key=equipment, calculation_type=payload["calculation_type"])
    elif kind == "condenser_payload":
        values["equipment_key"] = payload["equipment_key"]
    result = registry.run(case["module_id"], ModuleInput(values=values))
    native = result.results.get("native_status")
    if case["module_id"] == "evaporator":
        native = result.results.get("native_result", {}).get("outputs", {}).get("Calculation status")
    elif case["module_id"] == "regenerator" and decision.subtype == "Fixed-Ceramic-Matrix":
        text = result.results.get("console_output", "")
        native = "OPTIMUM DESIGN FOUND" if "RESULT: OPTIMUM DESIGN FOUND!" in text else "NO DESIGN OR WARNING"
    if payload != original:
        raise AssertionError("An adapter mutated the example payload.")
    passed = result.status == case["expected_status"] and native == case["expected_native_status"]
    if case["expected_status"] == "success":
        passed = passed and not result.errors and bool(result.results)
    if case["case_type"] == "diagnostic":
        passed = passed and bool(result.errors)
    summary = {"file": case["file"], "module_id": case["module_id"], "case_type": case["case_type"],
               "passed": bool(passed), "status": result.status, "native_status": native,
               "expected_status": case["expected_status"], "expected_native_status": case["expected_native_status"],
               "route": decision.path_id, "subtype": decision.subtype,
               "warning_count": len(result.warnings), "errors": list(result.errors)}
    return summary, TerminalResultPresenter.to_payload(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", help="One manifest path, e.g. condenser/air_cooled.json; repeat for multiple cases.")
    parser.add_argument("--report", type=Path, default=EXAMPLES / "test_report.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tmp/example_results")
    args = parser.parse_args(argv)
    cases = load_manifest()
    if args.case:
        selected = {item.replace("examples/", "", 1) if item.startswith("examples/") else item for item in args.case}
        missing = selected - {case["file"] for case in cases}
        if missing:
            parser.error("Unknown example(s): " + ", ".join(sorted(missing)))
        cases = [case for case in cases if case["file"] in selected]
    summaries = []
    registry = build_registry()
    for case in cases:
        try:
            summary, result = run_case(case, registry)
            if result is not None:
                target = args.output_dir / Path(case["file"]).with_suffix(".result.json")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(result, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8")
        except Exception as exc:
            summary = {"file": case["file"], "module_id": case["module_id"], "case_type": case["case_type"],
                       "passed": False, "error": str(exc)}
        summaries.append(summary)
        label = "PASS" if summary["passed"] else "FAIL"
        print(f"{label}  {case['file']}  [{summary.get('native_status') or summary.get('status') or summary.get('error')}]")
    passed = sum(item["passed"] for item in summaries)
    report = {"executed_at_utc": datetime.now(timezone.utc).isoformat(), "total": len(summaries),
              "passed": passed, "failed": len(summaries) - passed,
              "note": "Pass means the software returned the expected result. It does not establish engineering acceptance. Diagnostic and routing-only cases are marked separately.",
              "cases": summaries}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(summaries)} cases passed. Report: {args.report}")
    return 0 if passed == len(summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
