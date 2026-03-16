#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bz2
import csv
import gzip
import io
import json
import lzma
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from common import ensure_modules, install_hint, module_available

SMALL_FILE_BYTES = 150 * 1024 * 1024
LARGE_FILE_BYTES = 1500 * 1024 * 1024

SUPPORTED_FORMATS = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".xlsb", ".parquet", ".feather", ".json", ".jsonl"}
COMPRESSION_SUFFIXES = {".gz", ".gzip", ".bz2", ".xz"}
ARCHIVE_SUFFIXES = {".zip"}
NEGATIVE_NAME_TOKENS = {"readme", "schema", "dictionary", "metadata", "notes", "license"}
POSITIVE_NAME_TOKENS = {"data", "export", "fact", "table", "dataset", "records"}


def _backend_for_suffix(suffix: str, size_bytes: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if suffix in {".csv", ".tsv"}:
        if size_bytes <= SMALL_FILE_BYTES:
            return "pandas", warnings
        if size_bytes <= LARGE_FILE_BYTES:
            return "polars_or_duckdb", warnings
        warnings.append("Prefer pushdown, chunking, or DuckDB for very large delimited files.")
        return "duckdb_or_chunked", warnings
    if suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        warnings.append("Excel is fragile for large datasets. Consider converting to CSV or Parquet first.")
        return "pandas_excel", warnings
    if suffix in {".parquet", ".feather"}:
        if size_bytes <= SMALL_FILE_BYTES:
            return "pandas_or_polars", warnings
        return "polars_or_duckdb", warnings
    if suffix in {".json", ".jsonl"}:
        return "pandas_json", warnings
    warnings.append("Unknown format. Fallback behavior may be limited.")
    return "unknown", warnings


def _suffix_profile(path_like: str | Path) -> dict[str, Any]:
    suffixes = [suffix.lower() for suffix in Path(path_like).suffixes]
    compression_suffix = suffixes[-1] if suffixes and suffixes[-1] in COMPRESSION_SUFFIXES else None
    archive_suffix = suffixes[-1] if suffixes and suffixes[-1] in ARCHIVE_SUFFIXES else None
    if archive_suffix:
        logical_suffix = suffixes[-2] if len(suffixes) >= 2 else ""
    elif compression_suffix:
        logical_suffix = suffixes[-2] if len(suffixes) >= 2 else ""
    else:
        logical_suffix = suffixes[-1] if suffixes else ""
    return {
        "suffixes": suffixes,
        "archive_suffix": archive_suffix,
        "compression_suffix": compression_suffix,
        "logical_suffix": logical_suffix,
        "supported": logical_suffix in SUPPORTED_FORMATS,
    }


def _candidate_score(name: str, size_bytes: int) -> float:
    lower_name = Path(name).name.lower()
    score = float(min(size_bytes / (1024 * 1024), 200))
    if "__macosx" in name.lower():
        score -= 1000
    if any(token in lower_name for token in NEGATIVE_NAME_TOKENS):
        score -= 25
    if any(token in lower_name for token in POSITIVE_NAME_TOKENS):
        score += 8
    return score


def _choose_candidate(candidates: list[dict[str, Any]], noun: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not candidates:
        return None, [f"No supported tabular {noun} found."]
    ranked = sorted(candidates, key=lambda item: (_candidate_score(item["name"], item["size_bytes"]), item["size_bytes"]), reverse=True)
    warnings: list[str] = []
    if len(ranked) > 1:
        sample_names = ", ".join(item["name"] for item in ranked[:3])
        warnings.append(f"Multiple supported {noun}s detected. Auto-selected `{ranked[0]['name']}` from: {sample_names}.")
    return ranked[0], warnings


def resolve_input_source(input_path: str) -> dict[str, Any]:
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        return {"path": str(path), "exists": False, "supported": False, "warnings": ["Input path does not exist."]}

    if path.is_dir():
        candidates: list[dict[str, Any]] = []
        for child in path.rglob("*"):
            if not child.is_file():
                continue
            profile = _suffix_profile(child.name)
            if profile["archive_suffix"] or profile["supported"]:
                candidates.append({"name": str(child.relative_to(path)), "path": child, "size_bytes": child.stat().st_size})
        selected, warnings = _choose_candidate(candidates, "file")
        if selected is None:
            return {"path": str(path), "exists": True, "supported": False, "warnings": warnings}
        resolved = resolve_input_source(str(selected["path"]))
        resolved.setdefault("warnings", [])
        resolved["warnings"] = [f"Directory input auto-selected `{selected['name']}`."] + list(resolved["warnings"]) + warnings
        resolved["container_path"] = str(path)
        return resolved

    profile = _suffix_profile(path.name)
    size_bytes = path.stat().st_size

    if profile["archive_suffix"] == ".zip":
        candidates: list[dict[str, Any]] = []
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member_profile = _suffix_profile(info.filename)
                if member_profile["supported"]:
                    candidates.append(
                        {
                            "name": info.filename,
                            "size_bytes": info.file_size,
                            "logical_suffix": member_profile["logical_suffix"],
                            "compression_suffix": member_profile["compression_suffix"],
                        }
                    )
        selected, warnings = _choose_candidate(candidates, "archive member")
        if selected is None:
            return {
                "path": str(path),
                "exists": True,
                "supported": False,
                "format": ".zip",
                "size_bytes": size_bytes,
                "size_mb": round(size_bytes / (1024 * 1024), 2),
                "warnings": warnings,
            }
        return {
            "path": str(path),
            "exists": True,
            "supported": True,
            "kind": "archive_member",
            "format": selected["logical_suffix"],
            "container_format": ".zip",
            "member_name": selected["name"],
            "member_size_bytes": selected["size_bytes"],
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "warnings": warnings,
        }

    return {
        "path": str(path),
        "exists": True,
        "supported": profile["supported"],
        "kind": "file",
        "format": profile["logical_suffix"] or "unknown",
        "compression": profile["compression_suffix"],
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "warnings": [],
    }


def build_file_read_plan(input_path: str) -> dict[str, Any]:
    resolved = resolve_input_source(input_path)
    if not resolved.get("exists", False):
        return resolved
    if not resolved.get("supported", False):
        resolved.setdefault("warnings", []).append("Supported formats: csv, tsv, xlsx, xlsm, xls, xlsb, parquet, feather, json, jsonl.")
        return resolved

    logical_suffix = str(resolved.get("format", "")).lower()
    logical_size = int(resolved.get("member_size_bytes") or resolved.get("size_bytes") or 0)
    backend, backend_warnings = _backend_for_suffix(logical_suffix, logical_size)
    warnings = list(resolved.get("warnings", [])) + backend_warnings
    requires: list[str] = []
    if backend.startswith("pandas"):
        requires.append("pandas")
        if logical_suffix in {".xlsx", ".xlsm", ".xls"}:
            requires.append("openpyxl")
    elif backend.startswith("polars"):
        requires.extend(["polars", "pyarrow"])
    elif backend.startswith("duckdb"):
        requires.append("duckdb")

    if logical_suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        warnings.append("A worksheet cannot exceed 1,048,576 rows.")
    if resolved.get("kind") == "archive_member":
        warnings.append("Archive inputs are read from the selected member only; inspect other members if joins are expected.")
    if resolved.get("compression"):
        warnings.append(f"Compressed input detected via `{resolved['compression']}`; row counts are estimated from compressed bytes only.")

    return {
        **resolved,
        "recommended_backend": backend,
        "requires": sorted(set(requires)),
        "pandas_available": module_available("pandas"),
        "preview_available": logical_suffix in {".csv", ".tsv"},
    }


@contextmanager
def _open_text_handle(resolved: dict[str, Any]) -> Iterator[Any]:
    kind = resolved.get("kind")
    path = Path(str(resolved["path"]))
    if kind == "archive_member":
        archive = zipfile.ZipFile(path)
        raw = archive.open(str(resolved["member_name"]))
        wrapped = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        try:
            yield wrapped
        finally:
            wrapped.close()
            raw.close()
            archive.close()
        return

    compression = resolved.get("compression")
    opener = path.open
    if compression in {".gz", ".gzip"}:
        opener = gzip.open
    elif compression == ".bz2":
        opener = bz2.open
    elif compression == ".xz":
        opener = lzma.open

    handle = opener(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    try:
        yield handle
    finally:
        handle.close()


def preview_delimited_file(input_path: str, max_rows: int = 5) -> dict[str, Any]:
    resolved = resolve_input_source(input_path)
    logical_suffix = str(resolved.get("format", "")).lower()
    if logical_suffix not in {".csv", ".tsv"}:
        raise ValueError("Preview is only available for CSV/TSV-style inputs.")
    delimiter = "\t" if logical_suffix == ".tsv" else ","
    with _open_text_handle(resolved) as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        rows = []
        for index, row in enumerate(reader):
            rows.append(row)
            if index + 1 >= max_rows:
                break
    header = rows[0] if rows else []
    return {"path": resolved.get("path"), "member_name": resolved.get("member_name"), "header": header, "rows": rows[1:], "preview_rows": max(len(rows) - 1, 0)}


def _read_buffer_with_pandas(raw_bytes: bytes, logical_suffix: str, sample_rows: int | None = None):
    ensure_modules(["pandas"], "tabular file reads")
    import pandas as pd  # type: ignore

    buffer = io.BytesIO(raw_bytes)
    if logical_suffix in {".csv", ".tsv"}:
        return pd.read_csv(buffer, sep="\t" if logical_suffix == ".tsv" else ",", nrows=sample_rows)
    if logical_suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        return pd.read_excel(buffer, nrows=sample_rows)
    if logical_suffix in {".parquet", ".feather"}:
        frame = pd.read_parquet(buffer)
        return frame.head(sample_rows) if sample_rows else frame
    if logical_suffix == ".json":
        frame = pd.read_json(buffer)
        return frame.head(sample_rows) if sample_rows else frame
    if logical_suffix == ".jsonl":
        frame = pd.read_json(buffer, lines=True)
        return frame.head(sample_rows) if sample_rows else frame
    raise ValueError(f"Unsupported archive member format: {logical_suffix or '[no suffix]'}")


def load_dataframe(input_path: str, sample_rows: int | None = None):
    resolved = resolve_input_source(input_path)
    if not resolved.get("supported", False):
        raise ValueError(f"Unsupported file format: {resolved.get('format') or '[unknown]'}")

    logical_suffix = str(resolved.get("format", "")).lower()
    path = Path(str(resolved["path"]))

    if resolved.get("kind") == "archive_member":
        with zipfile.ZipFile(path) as archive:
            raw_bytes = archive.read(str(resolved["member_name"]))
        return _read_buffer_with_pandas(raw_bytes, logical_suffix, sample_rows=sample_rows)

    if logical_suffix in {".csv", ".tsv"}:
        ensure_modules(["pandas"], "tabular file reads")
        import pandas as pd  # type: ignore

        return pd.read_csv(path, sep="\t" if logical_suffix == ".tsv" else ",", nrows=sample_rows, compression="infer")
    if logical_suffix in {".xlsx", ".xlsm", ".xls"}:
        ensure_modules(["pandas", "openpyxl"], "Excel file reads")
        import pandas as pd  # type: ignore

        return pd.read_excel(path, nrows=sample_rows)
    if logical_suffix == ".xlsb":
        ensure_modules(["pandas"], "XLSB file reads")
        import pandas as pd  # type: ignore

        return pd.read_excel(path, nrows=sample_rows)
    if logical_suffix in {".parquet", ".feather"}:
        ensure_modules(["pandas"], "columnar file reads")
        import pandas as pd  # type: ignore

        frame = pd.read_parquet(path)
        return frame.head(sample_rows) if sample_rows else frame
    if logical_suffix == ".json":
        ensure_modules(["pandas"], "JSON file reads")
        import pandas as pd  # type: ignore

        frame = pd.read_json(path, compression="infer")
        return frame.head(sample_rows) if sample_rows else frame
    if logical_suffix == ".jsonl":
        ensure_modules(["pandas"], "JSONL file reads")
        import pandas as pd  # type: ignore

        frame = pd.read_json(path, lines=True, compression="infer")
        return frame.head(sample_rows) if sample_rows else frame

    raise ValueError(f"Unsupported file format: {logical_suffix or '[no suffix]'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or preview file reads for the data-analysis skill.")
    parser.add_argument("--input-path", required=True, help="Path to the local data file.")
    parser.add_argument("--sample-rows", type=int, default=5, help="Rows to preview for delimited files.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    plan = build_file_read_plan(args.input_path)
    if not plan.get("exists", False):
        output = plan
    elif plan.get("preview_available"):
        output = {"plan": plan, "preview": preview_delimited_file(args.input_path, max_rows=args.sample_rows)}
    else:
        output = {"plan": plan}
        if plan.get("requires"):
            output["install_hint"] = install_hint(plan["requires"])

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
