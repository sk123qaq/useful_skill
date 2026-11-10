#!/usr/bin/env python3
"""Shared helpers for the contract-first analysis workflow.

Every script is expected to:
- read explicit inputs (never guess a file from a directory),
- write explicit outputs (never write to the process cwd by accident),
- fail with a non-zero exit code when a precondition is missing.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TASKS = {"descriptive", "predictive", "causal", "experiment", "stop_and_report"}
ROUTES = {"descriptive", "predictive", "causal", "experiment", "stop_and_report"}
EVIDENCE_GRADES = {"report-ready", "exploratory", "not_usable"}
RISK_LABELS = {"safe", "soft_proxy", "post_outcome", "hard_leakage", "collection_artifact", "unreviewed"}


class WorkflowError(ValueError):
    """A deterministic precondition failed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: str | Path | None, *, required: bool = False) -> dict[str, Any]:
    if not path:
        if required:
            raise WorkflowError("missing required JSON path")
        return {}
    p = Path(path)
    if not p.exists():
        if required:
            raise WorkflowError(f"JSON artifact not found: {p}")
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise WorkflowError(f"invalid JSON in {p}: {exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError(f"JSON artifact must be an object: {p}")
    return payload


def write_json(path: str | Path, payload: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return p


def write_text(path: str | Path, text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.rstrip() + "\n", encoding="utf-8")
    return p


def require_keys(payload: dict[str, Any], keys: Iterable[str], name: str) -> None:
    missing = sorted(set(keys) - set(payload))
    if missing:
        raise WorkflowError(f"{name} missing keys: {', '.join(missing)}")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def file_sha256(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_artifact(value: str | Path | None, run_dir: str | Path | None = None) -> Path | None:
    if value is None:
        return None
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    base = Path(run_dir) if run_dir else Path.cwd()
    return (base / p).resolve()


def contract_paths(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": contract.get("target"),
        "time_col": contract.get("time_col"),
        "task": contract.get("task"),
        "unit_of_analysis": contract.get("unit_of_analysis"),
        "focus_columns": as_list(contract.get("focus_columns")),
        "group_col": contract.get("group_col"),
        "treatment": contract.get("treatment"),
    }


def validate_contract_payload(payload: dict[str, Any], *, data_columns: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    required = [
        "decision_question", "task", "target", "time_col", "unit_of_analysis",
        "data_source", "data_scope", "success_criteria", "stop_conditions",
        "report_locale", "dataset_kind",
    ]
    for key in required:
        if key not in payload:
            errors.append(f"missing key: {key}")
    if errors:
        return errors

    if payload.get("task") not in TASKS:
        errors.append(f"task must be one of {sorted(TASKS)}")
    if payload.get("data_scope") not in {"sample", "full"}:
        errors.append("data_scope must be sample or full")
    if payload.get("report_locale") not in {"zh", "en"}:
        errors.append("report_locale must be zh or en")
    if payload.get("dataset_kind") not in {"single_table", "dataset_package", "sql_query"}:
        errors.append("dataset_kind is invalid")
    for key in ("success_criteria", "stop_conditions"):
        if not isinstance(payload.get(key), list) or not payload.get(key):
            errors.append(f"{key} must be a non-empty list")
    if not isinstance(payload.get("unit_of_analysis"), str) or not payload.get("unit_of_analysis").strip():
        errors.append("unit_of_analysis must be a non-empty string")
    if not isinstance(payload.get("decision_question"), str) or not payload.get("decision_question").strip():
        errors.append("decision_question must be a non-empty string")
    if payload.get("time_col") is not None and not isinstance(payload.get("time_col"), str):
        errors.append("time_col must be a string or null")
    if payload.get("target") is not None and not isinstance(payload.get("target"), str):
        errors.append("target must be a string or null")
    if payload.get("task") in {"predictive", "causal", "experiment"} and not payload.get("target"):
        errors.append(f"task={payload.get('task')} requires a target")
    if data_columns is not None:
        if payload.get("target") and payload["target"] not in data_columns:
            errors.append(f"target not found in data: {payload['target']}")
        if payload.get("time_col") and payload["time_col"] not in data_columns:
            errors.append(f"time_col not found in data: {payload['time_col']}")
    return errors


def read_contract(path: str | Path, *, data_columns: list[str] | None = None) -> dict[str, Any]:
    payload = load_json(path, required=True)
    errors = validate_contract_payload(payload, data_columns=data_columns)
    if errors:
        raise WorkflowError("; ".join(errors))
    return payload


def require_output_path(path: str | Path, label: str = "output") -> Path:
    if not path:
        raise WorkflowError(f"{label} path is required")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def parse_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]
