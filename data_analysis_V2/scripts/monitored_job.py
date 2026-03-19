from __future__ import annotations

import inspect
import json
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from data_analysis_V2.scripts.common import append_jsonl, ensure_dir, now_utc_iso, write_json


def _invoke_with_optional_heartbeat(fn: Callable[..., dict[str, Any]], heartbeat: Callable[[str | None], None]) -> dict[str, Any]:
    signature = inspect.signature(fn)
    if "heartbeat" in signature.parameters:
        return fn(heartbeat=heartbeat)
    return fn()


def detect_stall(status_path: str | Path, max_staleness_seconds: int) -> dict[str, Any]:
    payload = Path(status_path).read_text()
    last_updated = json.loads(payload)["updated_at"]  # type: ignore[name-defined]
    stale = (time.time() - time.mktime(time.strptime(last_updated[:19], "%Y-%m-%dT%H:%M:%S"))) > max_staleness_seconds
    return {"stalled": stale, "updated_at": last_updated}


def run_monitored_job(
    job_name: str,
    output_dir: str | Path,
    fn: Callable[..., dict[str, Any]],
    heartbeat_interval: float = 0.2,
    stall_after: float = 1.0,
) -> dict[str, Any]:
    run_dir = ensure_dir(output_dir)
    heartbeat_path = run_dir / f"{job_name}_heartbeat.jsonl"
    event_path = run_dir / f"{job_name}_events.jsonl"
    status_path = run_dir / f"{job_name}_status.json"
    traceback_path = run_dir / f"{job_name}_traceback.txt"
    state = {"last_heartbeat_monotonic": time.monotonic(), "last_heartbeat_at": now_utc_iso()}
    result_holder: dict[str, Any] = {}
    error_holder: dict[str, Any] = {}

    def write_status(status: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "job_name": job_name,
            "status": status,
            "updated_at": now_utc_iso(),
            "heartbeat_path": str(heartbeat_path),
            "event_path": str(event_path),
        }
        if extra:
            payload.update(extra)
        write_json(status_path, payload)
        append_jsonl(event_path, payload)

    def heartbeat(message: str | None = None) -> None:
        state["last_heartbeat_monotonic"] = time.monotonic()
        state["last_heartbeat_at"] = now_utc_iso()
        append_jsonl(
            heartbeat_path,
            {
                "job_name": job_name,
                "message": message or "heartbeat",
                "ts": state["last_heartbeat_at"],
            },
        )
        write_status("running", {"last_heartbeat_at": state["last_heartbeat_at"]})

    def target() -> None:
        try:
            result_holder["result"] = _invoke_with_optional_heartbeat(fn, heartbeat)
        except Exception as exc:  # pragma: no cover - exercised via tests
            error_holder["error"] = exc
            traceback_path.write_text(traceback.format_exc())

    write_status("running", {"last_heartbeat_at": state["last_heartbeat_at"]})
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    while thread.is_alive():
        if time.monotonic() - state["last_heartbeat_monotonic"] > stall_after:
            write_status(
                "stalled",
                {
                    "last_heartbeat_at": state["last_heartbeat_at"],
                    "traceback_path": str(traceback_path) if traceback_path.exists() else None,
                },
            )
            return {
                "job_name": job_name,
                "status": "stalled",
                "status_path": str(status_path),
                "heartbeat_path": str(heartbeat_path),
                "event_path": str(event_path),
            }
        time.sleep(max(heartbeat_interval / 2, 0.05))
    if error_holder:
        write_status("failed", {"traceback_path": str(traceback_path)})
        return {
            "job_name": job_name,
            "status": "failed",
            "status_path": str(status_path),
            "traceback_path": str(traceback_path),
            "heartbeat_path": str(heartbeat_path),
            "event_path": str(event_path),
        }
    write_status("completed", {"last_heartbeat_at": state["last_heartbeat_at"]})
    return {
        "job_name": job_name,
        "status": "completed",
        "status_path": str(status_path),
        "heartbeat_path": str(heartbeat_path),
        "event_path": str(event_path),
        "result": result_holder.get("result", {}),
    }
