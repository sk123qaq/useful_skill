from __future__ import annotations

import json
from pathlib import Path

from data_analysis_V2.scripts.orchestrator import run_pipeline


FIXTURES = Path(__file__).parent / "fixtures"


def test_leakage_dataset_routes_to_stop_and_report(tmp_path: Path) -> None:
    result = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "hard_leakage.csv"),
        task="classification",
        target="target",
        data_scope="full",
        formal_report=True,
        output_dir=str(tmp_path),
    )
    run_dir = Path(result["run_dir"])
    route = json.loads((run_dir / "route_decision.json").read_text())
    judgment = json.loads((run_dir / "judgment_bundle.json").read_text())
    assert result["state"] == "stop_and_report"
    assert route["route"] == "stop_and_report"
    assert judgment["evidence_grade"] == "not_usable"
    assert (run_dir / "judgment_context_after_scout.json").exists()
    assert (run_dir / "report_bundle.json").exists()
    assert not (run_dir / "formal_report_v2.md").exists()
