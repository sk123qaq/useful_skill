#!/usr/bin/env python3
"""IO router: list candidates, then load exactly what the caller names.

The old router silently picked the largest file in a directory. That is how a
32 KB product-code lookup table got analysed instead of the customs data.
This version never selects for the caller.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402

SMALL_FILE_BYTES = 150 * 1024 * 1024
AUTOSAMPLE_THRESHOLD_BYTES = 500 * 1024 * 1024
DEFAULT_SAMPLE_ROWS = 100_000
SUPPORTED_FORMATS = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".xlsb", ".parquet", ".feather", ".json", ".jsonl"}
COMPRESSION_SUFFIXES = {".gz", ".gzip", ".bz2", ".xz"}
ARCHIVE_SUFFIXES = {".zip"}


def _suffix_profile(path_like: str | Path) -> dict[str, Any]:
    suffixes = [s.lower() for s in Path(path_like).suffixes]
    compression = suffixes[-1] if suffixes and suffixes[-1] in COMPRESSION_SUFFIXES else None
    archive = suffixes[-1] if suffixes and suffixes[-1] in ARCHIVE_SUFFIXES else None
    logical = suffixes[-2] if (archive or compression) and len(suffixes) >= 2 else (suffixes[-1] if suffixes else "")
    return {
        "suffixes": suffixes,
        "archive_suffix": archive,
        "compression_suffix": compression,
        "logical_suffix": logical,
        "supported": logical in SUPPORTED_FORMATS,
    }


def _candidate(path: Path, root: Path | None = None) -> dict[str, Any]:
    profile = _suffix_profile(path.name)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    info = {
        "name": str(path.relative_to(root)) if root else path.name,
        "path": str(path.resolve()),
        "size_bytes": size,
        "format": profile["logical_suffix"] or "unknown",
        "compression": profile["compression_suffix"],
        "supported": profile["supported"],
    }
    if profile["logical_suffix"] in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        info["sheets"] = list_sheets(path).get("sheets", [])
    return info


def list_sheets(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if _suffix_profile(p.name)["logical_suffix"] not in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        return {"path": str(p.resolve()), "sheets": []}
    try:
        import pandas as pd

        with pd.ExcelFile(p) as xls:
            return {"path": str(p.resolve()), "sheets": list(xls.sheet_names)}
    except Exception as exc:
        return {"path": str(p.resolve()), "sheets": [], "error": str(exc)}


def resolve_input_source(input_path: str) -> dict[str, Any]:
    """Resolve a file or list a directory. Never auto-select a directory child."""
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        return {"path": str(path), "exists": False, "supported": False, "kind": "missing",
                "warnings": ["Input path does not exist."]}
    if path.is_dir():
        candidates: list[dict[str, Any]] = []
        for child in sorted(path.rglob("*")):
            if child.is_file() and _suffix_profile(child.name)["supported"]:
                candidates.append(_candidate(child, root=path))
        candidates.sort(key=lambda item: item["size_bytes"], reverse=True)
        return {
            "path": str(path),
            "exists": True,
            "kind": "directory",
            "supported": False,
            "candidates": candidates,
            "warnings": [
                "Directory input is a candidate list, not a data file. "
                "Pass an explicit --input-path to load one file."
            ],
        }
    profile = _suffix_profile(path.name)
    resolved = {
        "path": str(path),
        "exists": True,
        "kind": "file",
        "supported": profile["supported"],
        "format": profile["logical_suffix"] or "unknown",
        "compression": profile["compression_suffix"],
        "size_bytes": path.stat().st_size,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
    }
    if profile["logical_suffix"] in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        resolved["sheets"] = list_sheets(path).get("sheets", [])
    return resolved


def build_file_read_plan(input_path: str) -> dict[str, Any]:
    resolved = resolve_input_source(input_path)
    if resolved.get("kind") != "file":
        return resolved
    if not resolved.get("supported"):
        return resolved
    suffix = str(resolved.get("format", "")).lower()
    if suffix in {".csv", ".tsv"}:
        backend = "pandas"
    elif suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        backend = "pandas_excel"
    elif suffix in {".parquet", ".feather"}:
        backend = "pandas_or_polars"
    else:
        backend = "unknown"
    plan = {**resolved, "recommended_backend": backend, "preview_available": suffix in {".csv", ".tsv"}}
    if int(resolved.get("size_bytes") or 0) > AUTOSAMPLE_THRESHOLD_BYTES:
        plan["sampling_recommended"] = True
        plan["sampling_strategy"] = "head_chunk"
        plan["suggested_sample_rows"] = DEFAULT_SAMPLE_ROWS
    return plan


def load_dataframe(
    input_path: str,
    sample_rows: int | None = None,
    auto_sample: bool = True,
    *,
    sheet: str | int | None = None,
    comment: str | None = None,
    skiprows: int | None = None,
    encoding: str | None = None,
):
    resolved = resolve_input_source(input_path)
    if resolved.get("kind") == "directory":
        names = ", ".join(item["name"] for item in resolved.get("candidates", [])[:8])
        raise ValueError(f"Directory input must be resolved to one file. Candidates: {names or '(none)'}")
    if not resolved.get("supported"):
        raise ValueError(f"Unsupported or missing input: {resolved.get('path')}")

    import pandas as pd

    suffix = str(resolved.get("format", "")).lower()
    path = Path(str(resolved["path"]))
    if sample_rows is None and auto_sample and int(resolved.get("size_bytes") or 0) > AUTOSAMPLE_THRESHOLD_BYTES:
        sample_rows = DEFAULT_SAMPLE_ROWS
        print(f"Note: sampling first {sample_rows} rows of {resolved.get('size_mb')} MB file.", file=sys.stderr)

    read_kwargs: dict[str, Any] = {}
    if comment is not None:
        read_kwargs["comment"] = comment
    if skiprows is not None:
        read_kwargs["skiprows"] = skiprows
    if encoding is not None:
        read_kwargs["encoding"] = encoding

    if suffix in {".csv", ".tsv"}:
        return pd.read_csv(
            path,
            sep="\t" if suffix == ".tsv" else ",",
            nrows=sample_rows,
            compression="infer",
            **read_kwargs,
        )
    if suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, nrows=sample_rows, **read_kwargs)
    if suffix in {".parquet", ".feather"}:
        frame = pd.read_parquet(path, **read_kwargs)
        return frame.head(sample_rows) if sample_rows else frame
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=(suffix == ".jsonl"), nrows=sample_rows if suffix == ".jsonl" else None)
    raise ValueError(f"Could not load {suffix}")


def _preview_columns(path: str, *, sheet: str | int | None = None, comment: str | None = None,
                     skiprows: int | None = None) -> list[str]:
    try:
        frame = load_dataframe(path, sample_rows=5, auto_sample=False, sheet=sheet, comment=comment, skiprows=skiprows)
        return [str(c) for c in frame.columns]
    except Exception:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description="List/read data sources without guessing.")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="List candidates / describe one file")
    manifest.add_argument("--input-path", required=True)
    manifest.add_argument("--output-path")
    manifest.add_argument("--sheet", default=None)
    manifest.add_argument("--comment", default=None)
    manifest.add_argument("--skiprows", type=int, default=None)

    load = sub.add_parser("load", help="Load one explicit file and report shape/dtypes")
    load.add_argument("--input-path", required=True)
    load.add_argument("--output-path")
    load.add_argument("--sheet", default=None)
    load.add_argument("--comment", default=None)
    load.add_argument("--skiprows", type=int, default=None)
    load.add_argument("--encoding", default=None)
    load.add_argument("--sample-rows", type=int, default=None)

    args = parser.parse_args()
    if args.command == "manifest":
        payload = build_file_read_plan(args.input_path)
        if payload.get("kind") == "directory":
            for item in payload.get("candidates", []):
                if item.get("format") in {".xlsx", ".xlsm", ".xls", ".xlsb"} and args.sheet is None:
                    item["columns"] = None
                    item["note"] = "Select a sheet explicitly with --sheet."
                else:
                    item["columns"] = _preview_columns(item["path"], comment=args.comment, skiprows=args.skiprows)
        elif payload.get("kind") == "file":
            if payload.get("format") in {".xlsx", ".xlsm", ".xls", ".xlsb"} and args.sheet is None:
                payload["columns"] = None
                payload["note"] = "Select a sheet explicitly with --sheet."
            else:
                payload["columns"] = _preview_columns(
                    payload["path"], sheet=args.sheet, comment=args.comment, skiprows=args.skiprows
                )
        payload["created_at"] = common.now_utc_iso()
        if args.output_path:
            common.write_json(args.output_path, payload)
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    frame = load_dataframe(
        args.input_path, sample_rows=args.sample_rows, auto_sample=False,
        sheet=args.sheet, comment=args.comment, skiprows=args.skiprows, encoding=args.encoding,
    )
    payload = {
        "path": str(Path(args.input_path).resolve()),
        "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "columns": [str(c) for c in frame.columns],
        "dtypes": {str(c): str(t) for c, t in frame.dtypes.items()},
        "head": frame.head(3).to_dict(orient="records"),
        "created_at": common.now_utc_iso(),
    }
    if args.output_path:
        common.write_json(args.output_path, payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
