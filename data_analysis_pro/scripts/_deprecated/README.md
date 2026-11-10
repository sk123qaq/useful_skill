# Deprecated scripts

These files are kept only for reference. They are not part of the workflow and
must not be called by the Agent.

- `eda_stats.py`: replaced by `describe.py` (time series aware, no ignored flags).
- `relationship_screening.py`: unsafe automatic correlation screening; replaced by
  `feature_risk.py` + `describe.py`.
- `metadata_manager.py`: global mutable registry side effect; removed.
- `infer_business_meanings.py`: heuristic label invention; removed.
- `report_export.py`: fixed-file report assembler that ignored baseline/EDA and
  invented "report-ready"; replaced by `report_bundle.py` + `report_lint.py`.
