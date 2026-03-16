# Reporting

## Purpose

Use `scripts/report_export.py` to turn a run directory into a single static HTML artifact, `report_dashboard.html`, that is easier for humans and agents to review than many separate JSON and PNG files.
Use `scripts/formal_report_export.py` when you need a ready-made Chinese `.docx` and `.pdf` deliverable from an existing run directory.
Use `scripts/report_index.py` to build `run_index.html` and `run_index.json` across the whole `outputs/` tree.
Use `scripts/streamlit_dashboard.py` when you need an interactive browser over historical runs, filters, task-aware comparisons, and artifact drill-down.
When a user needs a formal Chinese report, use [report-artifact-interpretation-zh.md](report-artifact-interpretation-zh.md), [report-delivery-templates-zh.md](report-delivery-templates-zh.md), [analysis-report-docx-template.md](../templates/analysis-report-docx-template.md), and [analysis-report-pdf-template.md](../templates/analysis-report-pdf-template.md) as the handoff package for `docx` and `pdf` skills.

## Expected Inputs

The exporter is designed to read whatever exists in a run directory and degrade gracefully. It is most useful when these artifacts are present:

- `run_summary.md`
- `cleaning_report.json`
- `chart_plan.json`
- `model_report.json`
- `explainability_report.json`
- `business_report.json`
- `experiment_report.json`
- `analysis_report.json`
- `causal_report.json`
- `causal_narrative_report.json`
- PNG charts written by the pipeline

## Output

- `report_dashboard.html`: static report with summary cards, key findings, task-specific sections, chart gallery, and artifact index
- `analysis-report-zh.docx`: formal editable Chinese report generated from the run artifacts
- `analysis-report-zh.pdf`: formal fixed-layout Chinese report generated from the run artifacts
- `run_index.html`: static multi-run browser with task/group filters and direct links to dashboards and narratives
- `run_index.json`: machine-readable summary across discovered run directories
- `comparisons/<task>.html`: task-specific comparison page, for example experiment-vs-experiment or rd-vs-rd
- `streamlit run scripts/streamlit_dashboard.py -- --outputs-root outputs`: interactive dashboard for filtering runs, reading narratives, opening artifacts, and comparing similar analyses
- Chinese report handoff docs:
  - `references/report-artifact-interpretation-zh.md`
  - `references/report-delivery-templates-zh.md`
  - `templates/analysis-report-docx-template.md`
  - `templates/analysis-report-pdf-template.md`

## Formal Report Export Workflow

Use this workflow when the user asks for a formal report deliverable instead of, or in addition to, the HTML dashboard.

1. Finish the normal analysis run and keep all JSON / PNG / Markdown artifacts in the run directory.
2. Read `references/report-artifact-interpretation-zh.md` so the narrative uses the same metric meanings and chart-reading rules as the skill.
3. Run `python3 scripts/formal_report_export.py --run-dir <run_dir>` to generate the first-draft DOCX / PDF, plus `formal_report_draft.md`, `report_context.json`, and `formal_report_validation.json`.
4. Ask the agent to read `report_context.json` and the PNG charts, then write a structured `chart_review.json` with one object per chart plus an `overall_summary`.
5. Re-run `python3 scripts/formal_report_export.py --run-dir <run_dir> --chart-review-json <path>` so the script deterministically fills the reviewed chart text back into the fixed layout.
6. If the analysis itself is being launched from scratch, prefer `python3 scripts/run_pipeline.py ... --formal-report --report-title "..."` for the first-draft export, then do the `chart_review.json` handoff as a second pass.
7. The validation file checks not only file existence, but also paragraph/text extraction, embedded images, stale-output risk, Markdown leakage, and obvious raw technical identifiers.
8. In both DOCX and PDF outputs, require:
   - short plain-language explanations for technical terms
   - explicit guidance on whether each key metric looks good, weak, or inconclusive
   - per-chart natural-language interpretation, implication, and Chinese caption note populated from `chart_review.json`
9. After export, read the generated DOCX or PDF again and do a quality pass. Check for raw feature ids, raw model ids, literal Markdown syntax, fragmented bullets, stale old content, and unexplained metrics. Revise and re-export if needed.
10. Prefer the dashboard as a review layer, but build the formal report from the raw artifacts rather than copying dashboard text blindly.

## Public Dataset Adapters

For common public bundles that are awkward to analyze with the generic row/column pipeline, prefer the dedicated adapter when available.

- WDI zip bundle:
  - `python3 scripts/run_pipeline.py --dataset wdi --input-path <WDI_csv.zip>`
  - or `python3 scripts/wdi_analysis_report.py --zip-path <WDI_csv.zip>`

The WDI adapter handles wide-to-long transformation, aggregate filtering, recent-complete-year selection, custom chart metadata, and report-friendly narrative scaffolding.

## Guardrails

- treat the dashboard as a delivery layer, not a replacement for machine-readable artifacts
- prefer `causal_narrative_report` over raw causal JSON when the audience is non-technical
- keep raw reports and charts in the same directory so the dashboard can reference them directly
- if a section is missing, leave it out rather than fabricating content
- do not force cross-run numeric ranking when tasks are not comparable; prefer task-aware summaries instead
- for multi-run comparison, compare like with like: experiment to experiment, regression to regression, causal method to the same causal method or causal suite
- keep the Streamlit app read-only; it should inspect outputs, not mutate run artifacts
- default formal report language to Chinese unless the user explicitly asks for another language
- do not present unexplained jargon, naked p-values, or isolated model metrics in formal reports
- when describing a value as good or bad, anchor the judgment to a baseline, threshold, or business context
- normalize one-hot feature ids, model ids, and categorical code values into business-readable Chinese before they appear in formal reports
- when summarizing explainability, prefer variable dimensions such as “糖尿病状态” or “自评健康” over sparse encoded features
- exporters should write to a temporary file and replace the final path atomically so repeated exports do not retain stale sections
