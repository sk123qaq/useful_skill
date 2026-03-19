from __future__ import annotations

import json
import time
from pathlib import Path

from data_analysis_V2.scripts.monitored_job import run_monitored_job


def test_slow_job_writes_heartbeat_and_completes(tmp_path: Path) -> None:
    def slow_job(heartbeat):
        for index in range(3):
            heartbeat(f"tick-{index}")
            time.sleep(0.05)
        return {"ok": True}

    result = run_monitored_job("slow_job", tmp_path, slow_job, heartbeat_interval=0.05, stall_after=0.3)
    assert result["status"] == "completed"
    heartbeat_lines = (tmp_path / "slow_job_heartbeat.jsonl").read_text().strip().splitlines()
    assert len(heartbeat_lines) >= 3


def test_stalled_job_is_marked_stalled(tmp_path: Path) -> None:
    def stalled_job():
        time.sleep(0.25)
        return {"ok": False}

    result = run_monitored_job("stalled_job", tmp_path, stalled_job, heartbeat_interval=0.05, stall_after=0.1)
    assert result["status"] == "stalled"
    status_payload = json.loads((tmp_path / "stalled_job_status.json").read_text())
    assert status_payload["status"] == "stalled"


def test_failed_job_writes_traceback(tmp_path: Path) -> None:
    def failed_job(heartbeat):
        heartbeat("starting")
        raise RuntimeError("boom")

    result = run_monitored_job("failed_job", tmp_path, failed_job, heartbeat_interval=0.05, stall_after=0.3)
    assert result["status"] == "failed"
    assert (tmp_path / "failed_job_traceback.txt").exists()
