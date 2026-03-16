#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from analysis_methods import normalize_task as normalize_analysis_task
from analysis_methods import run_analysis_method
from business_templates import build_business_report
from causal_analysis import normalize_task as normalize_causal_task
from causal_analysis import run_causal_analysis
from causal_narrative import build_causal_narrative, write_causal_narrative
from clean_preprocess import build_cleaning_report
from common import availability_report, ensure_modules, ensure_output_dir, parse_json_arg, write_json, write_markdown
from db_connectors import connection_plan, explain_driver_risks, read_sql_query
from eda_stats import build_eda_report
from experiment_analysis import analyze_experiment
from explain_viz import build_storyline, save_basic_charts, select_chart_plan
from feature_engineering import build_feature_plan
from io_router import build_file_read_plan, load_dataframe
from model_explainability import explain_supervised_model
from model_runner import best_model_name_from_report, run_baseline_model, select_model_candidates
from report_export import export_dashboard
from report_index import export_run_index, infer_outputs_root
from source_research_adapter import execute_web_search_request


def infer_task(task: str, target: str | None, time_col: str | None) -> str:
    if task != "auto":
        return task
    if time_col and target:
        return "time-series"
    if target:
        return "regression"
    return "descriptive"


def _load_dataset(args) -> tuple[Any | None, dict[str, Any]]:
    if args.input_path:
        return load_dataframe(args.input_path, sample_rows=args.sample_rows), build_file_read_plan(args.input_path)
    if args.db_url and args.query:
        frame = read_sql_query(args.db_url, args.query, limit=args.sample_rows if args.sample_rows > 0 else None)
        plan = connection_plan(args.db_url)
        plan["risks"] = explain_driver_risks(args.db_url)
        return frame, plan
    return None, {"note": "No input source provided. Pipeline will only write environment and task planning artifacts."}


def _write_summary(run_dir: Path, task: str, read_plan: dict[str, Any], findings: list[str], risks: list[str], recommendations: list[str]) -> None:
    content = [
        "# Data Analysis Run Summary",
        "",
        f"- task: `{task}`",
        f"- read artifact: `{run_dir / 'read_plan.json'}`",
        f"- environment artifact: `{run_dir / 'environment.json'}`",
        "",
        build_storyline(findings, risks, recommendations),
        "",
        "## Read Plan",
        f"```json\n{json.dumps(read_plan, ensure_ascii=False, indent=2)}\n```",
    ]
    write_markdown(run_dir / "run_summary.md", "\n".join(content))


def _run_research_workflows(research_config: Any, run_dir: Path) -> dict[str, Any]:
    if not research_config:
        return {}
    requests = research_config if isinstance(research_config, list) else [research_config]
    reports = []
    for index, request_config in enumerate(requests, start=1):
        subdir = run_dir / ("research" if len(requests) == 1 else f"research-{index}")
        subdir.mkdir(parents=True, exist_ok=True)
        reports.append(execute_web_search_request(request_config, output_dir=subdir))
    aggregated = {
        "request_count": len(reports),
        "reports": reports,
        "record_count_total": sum(report["normalized_package"]["record_count_deduplicated"] for report in reports),
        "conflict_count_total": sum(len(report["normalized_package"]["conflicts"]) for report in reports),
    }
    write_json(run_dir / "research_report.json", aggregated)
    return aggregated


def _maybe_export_formal_report(run_dir: Path, enabled: bool, title: str | None) -> None:
    if not enabled:
        return
    ensure_modules(["docx", "reportlab"], "formal report export")
    from formal_report_export import export_formal_report

    export_formal_report(run_dir, title=title)


def _finish_run(run_dir: Path, formal_report: bool, report_title: str | None) -> None:
    export_dashboard(run_dir)
    _maybe_export_formal_report(run_dir, formal_report, report_title)
    export_run_index(infer_outputs_root(run_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the data-analysis skill pipeline.")
    parser.add_argument("--dataset", choices=["wdi"])
    parser.add_argument("--input-path")
    parser.add_argument("--db-url")
    parser.add_argument("--query")
    parser.add_argument("--task", default="auto")
    parser.add_argument("--target")
    parser.add_argument("--time-col")
    parser.add_argument("--output-dir")
    parser.add_argument("--config-json")
    parser.add_argument("--sample-rows", type=int, default=5000)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--formal-report", action="store_true")
    parser.add_argument("--report-title")
    args = parser.parse_args()

    config = parse_json_arg(args.config_json)

    if args.dataset == "wdi":
        if not args.input_path:
            parser.error("--dataset wdi requires --input-path pointing to WDI_csv.zip")
        from wdi_analysis_report import build_artifacts as build_wdi_artifacts

        outputs_root = Path(args.output_dir) if args.output_dir else (Path.cwd() / "outputs")
        run_dir = build_wdi_artifacts(Path(args.input_path), outputs_root)
        _finish_run(run_dir, args.formal_report, args.report_title)
        print(run_dir)
        return 0

    run_dir = ensure_output_dir(args.output_dir, prefix="data-analysis")
    environment = availability_report()
    write_json(run_dir / "environment.json", environment)
    research_config = config.get("research")

    task = infer_task(args.task, args.target, args.time_col)

    if args.input_path:
        read_plan = build_file_read_plan(args.input_path)
    elif args.db_url:
        read_plan = connection_plan(args.db_url)
        read_plan["risks"] = explain_driver_risks(args.db_url)
    else:
        read_plan = {"note": "No input source provided."}
    write_json(run_dir / "read_plan.json", read_plan)

    if args.plan_only or (not args.input_path and not (args.db_url and args.query) and not research_config):
        chart_plan = {"task": task, "charts": []}
        write_json(run_dir / "chart_plan.json", chart_plan)
        _write_summary(
            run_dir,
            task,
            read_plan,
            findings=["A planning-only run was requested, so no dataset was loaded."],
            risks=["Execution depends on installing missing packages and supplying a data source."],
            recommendations=["Use the saved read plan to prepare the runtime environment before analysis."],
        )
        _finish_run(run_dir, args.formal_report, args.report_title)
        print(run_dir)
        return 0

    if not args.input_path and not (args.db_url and args.query) and research_config:
        chart_plan = {"task": task, "charts": []}
        write_json(run_dir / "chart_plan.json", chart_plan)
        research_report = _run_research_workflows(research_config, run_dir)
        _write_summary(
            run_dir,
            task,
            read_plan,
            findings=[
                f"Executed {research_report['request_count']} external research request(s).",
                f"Collected {research_report['record_count_total']} deduplicated source candidates.",
            ],
            risks=["External research output is heuristic and should be reviewed before being treated as final metric truth."],
            recommendations=["Review research_report.json and research_sources.md before mixing external benchmarks with local data."],
        )
        _finish_run(run_dir, args.formal_report, args.report_title)
        print(run_dir)
        return 0

    df, read_artifact = _load_dataset(args)
    write_json(run_dir / "read_plan.json", read_artifact)

    cleaning_report = build_cleaning_report(df, time_col=args.time_col, target=args.target)
    eda_report = build_eda_report(df, time_col=args.time_col, target=args.target)
    feature_plan = build_feature_plan(df, target=args.target, time_col=args.time_col)
    chart_plan = select_chart_plan(df, task=task, target=args.target, time_col=args.time_col, config=config)
    write_json(run_dir / "cleaning_report.json", cleaning_report)
    write_json(run_dir / "stats_report.json", eda_report)
    write_json(run_dir / "feature_plan.json", feature_plan)
    write_json(run_dir / "chart_plan.json", chart_plan)

    model_report: dict[str, Any] = {}
    explainability_report: dict[str, Any] = {}
    if args.target and task in {"classification", "regression"}:
        model_report = run_baseline_model(df, target=args.target, task=task, time_col=args.time_col)
        explainability_config = config.get("explainability", {})
        if explainability_config is not False:
            selected_model = explainability_config.get("model_name") if isinstance(explainability_config, dict) else None
            if not selected_model:
                selected_model = best_model_name_from_report(model_report, task=task)
            if selected_model:
                explainability_report = explain_supervised_model(
                    df,
                    target=args.target,
                    task=task,
                    output_dir=run_dir,
                    model_name=selected_model,
                    top_n=int(explainability_config.get("top_n", 10)) if isinstance(explainability_config, dict) else 10,
                )
                write_json(run_dir / "explainability_report.json", explainability_report)
    elif args.target and task == "time-series":
        model_report = select_model_candidates(task, is_time_series=bool(args.time_col))
    elif args.target and task not in {"funnel", "monetization", "retention", "cohort", "ltv", "experiment", "ab-test"}:
        model_report = select_model_candidates(task, is_time_series=bool(args.time_col))
    if model_report:
        write_json(run_dir / "model_report.json", model_report)

    business_report: dict[str, Any] = {}
    if task in {"funnel", "monetization", "retention", "cohort", "ltv"}:
        business_report = build_business_report(df, task=task, config=config)
        write_json(run_dir / "business_report.json", business_report)

    experiment_report: dict[str, Any] = {}
    if task in {"experiment", "ab-test"}:
        experiment_report = analyze_experiment(df, config)
        write_json(run_dir / "experiment_report.json", experiment_report)

    analysis_report: dict[str, Any] = {}
    if task in {"cluster", "clustering", "apriori", "association", "association-rules", "anova", "root-cause", "root_cause"}:
        analysis_report = run_analysis_method(df, task=task, config=config, output_dir=run_dir)
        write_json(run_dir / "analysis_report.json", analysis_report)

    causal_report: dict[str, Any] = {}
    causal_narrative: dict[str, Any] = {}
    research_report: dict[str, Any] = {}
    if task in {
        "did",
        "difference-in-differences",
        "difference_in_differences",
        "rd",
        "regression-discontinuity",
        "regression_discontinuity",
        "rdd",
        "synthetic-control",
        "synthetic_control",
        "synth-control",
        "synthetic",
        "iv",
        "instrumental-variables",
        "instrumental_variables",
        "dml",
        "double-machine-learning",
        "double_machine_learning",
        "dr",
        "doubly-robust",
        "doubly_robust",
        "psm",
        "propensity-score-matching",
        "propensity_score_matching",
        "orthogonal",
        "orthogonal-learner",
        "orthogonal_learner",
        "uplift",
        "heterogeneity",
        "cate",
        "meta-learner",
        "meta_learner",
        "causal",
    }:
        causal_report = run_causal_analysis(df, task=task, config=config, output_dir=run_dir)
        write_json(run_dir / "causal_report.json", causal_report)
        causal_narrative = build_causal_narrative(causal_report, config=config)
        write_causal_narrative(run_dir, causal_narrative)

    if research_config:
        research_report = _run_research_workflows(research_config, run_dir)

    viz_result = save_basic_charts(df, run_dir, task=task, target=args.target, time_col=args.time_col, config=config)
    findings = [
        f"Loaded {int(df.shape[0])} rows and {int(df.shape[1])} columns.",
        f"Detected {cleaning_report['missing_values']['columns_with_missing_values']} columns with missing values.",
    ]
    risks = list(read_artifact.get("warnings", [])) if isinstance(read_artifact, dict) else []
    if not viz_result.get("rendered", False):
        risks.append("Charts were not rendered because matplotlib is unavailable in the current environment.")
    recommendations = feature_plan.get("recommendations", [])[:3]
    if explainability_report:
        findings.append(f"Explainability generated for model {explainability_report['model_name']}.")
        if explainability_report.get("permutation_importance"):
            top_feature = explainability_report["permutation_importance"][0]["feature"]
            findings.append(f"Top permutation-importance feature: {top_feature}.")
        recommendations.append("Review feature importance, PDP, and SHAP artifacts before interpreting model behavior.")
    if task in {"funnel", "monetization", "retention", "cohort", "ltv"} and business_report:
        recommendations.append("Review the business report artifact for KPI-specific interpretation.")
    if task in {"experiment", "ab-test"} and experiment_report:
        findings.append(f"Experiment decision status: {experiment_report['decision']['status']}.")
        recommendations.append("Review the experiment report for SRM, lift, p-values, and guardrail behavior.")
        if experiment_report["sample_ratio_mismatch"]["is_mismatch"]:
            risks.append("Sample ratio mismatch was detected, so the experiment result may be invalid.")
        if experiment_report.get("multiple_testing", {}).get("applied"):
            findings.append(f"Multiple-testing correction applied with {experiment_report['multiple_testing']['method']}.")
        if experiment_report.get("sequential_monitoring", {}).get("applied"):
            findings.append(
                f"Sequential monitoring applied with {experiment_report['sequential_monitoring']['method']} at alpha {experiment_report['sequential_monitoring']['adjusted_alpha']:.4f}."
            )
        underpowered = [
            metric_name
            for metric_name, result in experiment_report.get("metrics", {}).items()
            if result.get("power_analysis", {}).get("underpowered_for_target")
        ]
        if underpowered:
            risks.append(f"These metrics appear underpowered for the requested target power: {', '.join(underpowered)}.")
    if analysis_report:
        normalized_analysis_task = normalize_analysis_task(task)
        findings.append(f"{normalized_analysis_task} analysis report generated.")
        recommendations.append("Review the analysis_report artifact for method-specific outputs and charts.")
        if normalized_analysis_task == "cluster":
            findings.append(f"Selected {analysis_report['n_clusters']} clusters using {analysis_report['selection_metric']}.")
        elif normalized_analysis_task == "apriori":
            findings.append(f"Generated {len(analysis_report.get('rules', []))} association rules.")
            if not analysis_report.get("rules"):
                risks.append("No association rules passed the configured support/confidence thresholds.")
        elif normalized_analysis_task == "anova":
            findings.append(
                f"{analysis_report['result']['test']} p-value: {analysis_report['result']['p_value']:.4f}."
            )
            if not analysis_report["result"]["significant_at_alpha"]:
                risks.append("Group differences were not statistically significant at the configured alpha.")
        elif normalized_analysis_task == "root-cause":
            top_drivers = analysis_report.get("top_positive_drivers", [])
            if top_drivers:
                findings.append(f"Top root-cause driver: {top_drivers[0]['segment']}.")
    if causal_report:
        normalized_causal_task = normalize_causal_task(task)
        findings.append(f"{normalized_causal_task} causal report generated.")
        if causal_narrative:
            findings.append(causal_narrative["headline"])
        recommendations.append("Review the causal_narrative_report artifact first, then use causal_report.json for technical details and charts.")
        if normalized_causal_task == "did":
            findings.append(f"DID estimate: {causal_report['did_estimate']:.4f}.")
            regression = causal_report.get("regression", {})
            if regression.get("available"):
                findings.append(f"DID interaction p-value: {regression['p_value']:.4f}.")
        elif normalized_causal_task == "rd":
            findings.append(f"RD local effect: {causal_report['local_effect']:.4f}.")
            regression = causal_report.get("regression", {})
            if regression.get("available"):
                findings.append(f"RD local p-value: {regression['p_value']:.4f}.")
            if causal_report.get("treated_share", {}).get("right", 1.0) - causal_report.get("treated_share", {}).get("left", 0.0) < 0.5:
                risks.append("Treatment take-up does not jump sharply enough at the cutoff for a clean sharp RD story.")
            discontinuous_covariates = [
                feature
                for feature, details in causal_report.get("covariate_continuity", {}).items()
                if details.get("p_value") is not None and float(details["p_value"]) < 0.05
            ]
            if discontinuous_covariates:
                risks.append(
                    "Covariate continuity may be violated around the cutoff for: "
                    + ", ".join(discontinuous_covariates[:4])
                    + "."
                )
        elif normalized_causal_task == "synthetic-control":
            findings.append(f"Synthetic-control post average gap: {causal_report['post_average_gap']:.4f}.")
            ratio = causal_report.get("post_to_pre_rmspe_ratio")
            if ratio is not None:
                findings.append(f"Synthetic-control post/pre RMSPE ratio: {ratio:.4f}.")
            if causal_report.get("pre_rmspe", 0.0) > 5:
                risks.append("Synthetic control has a relatively large pre-treatment fit error.")
        elif normalized_causal_task == "iv":
            findings.append(f"IV estimate: {causal_report['iv_estimate']:.4f}.")
            first_stage = causal_report.get("first_stage", {})
            findings.append(f"IV first-stage F-statistic: {first_stage.get('f_statistic', 0.0):.4f}.")
            if first_stage.get("weak_instrument_at_f_lt_10"):
                risks.append("The instrument appears weak by the common first-stage F < 10 rule.")
        elif normalized_causal_task == "dml":
            findings.append(f"DML ATE: {causal_report['average_treatment_effect']:.4f}.")
            if causal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("DML residualization has limited overlap.")
        elif normalized_causal_task == "dr":
            findings.append(f"Doubly robust ATE: {causal_report['average_treatment_effect']:.4f}.")
            if causal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("Doubly robust estimation has limited propensity overlap.")
        elif normalized_causal_task == "psm":
            findings.append(
                f"PSM ATT: {causal_report['average_treatment_effect_on_treated']:.4f} from {causal_report['matched_pairs']} matched pairs."
            )
            if causal_report.get("common_support", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("Common support is limited, so the PSM estimate may be unstable.")
            balance = causal_report.get("balance", {})
            if balance and not balance.get("balance_improved", True):
                risks.append("Matching did not improve covariate balance, so the PSM result should not be treated as reliable.")
        elif normalized_causal_task == "orthogonal":
            findings.append(f"Orthogonal learner average predicted effect: {causal_report['average_predicted_effect']:.4f}.")
            if causal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("Orthogonal learner has limited overlap in the nuisance propensity model.")
        elif normalized_causal_task == "uplift":
            findings.append(f"Average predicted uplift: {causal_report['average_predicted_uplift']:.4f}.")
            if not causal_report.get("heterogeneity"):
                risks.append("No sufficiently sized heterogeneity segments were found under the configured minimum group size.")
        elif normalized_causal_task == "cate":
            findings.append(f"CATE meta-learner methods: {', '.join(causal_report.get('methods', {}).keys())}.")
            comparison = causal_report.get("method_comparison", {})
            if "mean_absolute_difference" in comparison:
                findings.append(f"Meta-learner mean absolute CATE gap: {comparison['mean_absolute_difference']:.4f}.")
            if comparison.get("correlation") is not None and float(comparison["correlation"]) < 0.3:
                risks.append("Meta-learner CATE estimates have low agreement, which signals model uncertainty.")
        elif normalized_causal_task == "causal":
            findings.append(f"Causal suite executed methods: {', '.join(causal_report.get('methods', []))}.")
            rd_report = causal_report.get("reports", {}).get("rd", {})
            if rd_report and rd_report.get("treated_share", {}).get("right", 1.0) - rd_report.get("treated_share", {}).get("left", 0.0) < 0.5:
                risks.append("Causal suite RD run does not show a strong treatment jump at the cutoff.")
            if rd_report:
                discontinuous_covariates = [
                    feature
                    for feature, details in rd_report.get("covariate_continuity", {}).items()
                    if details.get("p_value") is not None and float(details["p_value"]) < 0.05
                ]
                if discontinuous_covariates:
                    risks.append(
                        "Causal suite RD run shows potential covariate discontinuity at the cutoff for: "
                        + ", ".join(discontinuous_covariates[:4])
                        + "."
                    )
            synth_report = causal_report.get("reports", {}).get("synthetic-control", {})
            if synth_report and synth_report.get("pre_rmspe", 0.0) > 5:
                risks.append("Causal suite synthetic control has a relatively large pre-treatment fit error.")
            iv_report = causal_report.get("reports", {}).get("iv", {})
            if iv_report and iv_report.get("first_stage", {}).get("weak_instrument_at_f_lt_10"):
                risks.append("Causal suite IV run has a weak first stage.")
            dml_report = causal_report.get("reports", {}).get("dml", {})
            if dml_report and dml_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("Causal suite DML run has limited overlap.")
            dr_report = causal_report.get("reports", {}).get("dr", {})
            if dr_report and dr_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("Causal suite doubly robust run has limited overlap.")
            orthogonal_report = causal_report.get("reports", {}).get("orthogonal", {})
            if orthogonal_report and orthogonal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("Causal suite orthogonal learner has limited overlap.")
            if dml_report and orthogonal_report:
                dml_effect = float(dml_report.get("average_treatment_effect", 0.0))
                orthogonal_effect = float(orthogonal_report.get("average_predicted_effect", 0.0))
                denominator = max(abs(dml_effect), 1.0)
                if abs(dml_effect - orthogonal_effect) / denominator > 0.2:
                    risks.append("Causal suite DML and orthogonal learner estimates diverge materially.")
            cate_report = causal_report.get("reports", {}).get("cate", {})
            cate_comparison = cate_report.get("method_comparison", {})
            if cate_comparison.get("correlation") is not None and float(cate_comparison["correlation"]) < 0.3:
                risks.append("Causal suite meta-learner CATE estimates have low agreement.")
            psm_report = causal_report.get("reports", {}).get("psm", {})
            if psm_report:
                if psm_report.get("common_support", {}).get("share_in_common_support", 1.0) < 0.8:
                    risks.append("Causal suite PSM run has limited common support.")
                if not psm_report.get("balance", {}).get("balance_improved", True):
                    risks.append("Causal suite PSM run did not improve covariate balance.")
    if research_report:
        findings.append(f"External research collected {research_report['record_count_total']} deduplicated source candidates.")
        recommendations.append("Review the research_sources markdown and conflict flags before using external benchmarks in the final analysis.")
        if research_report["conflict_count_total"] > 0:
            risks.append(f"External research found {research_report['conflict_count_total']} source-definition or unit conflicts.")

    _write_summary(run_dir, task, read_artifact, findings, risks, recommendations)
    _finish_run(run_dir, args.formal_report, args.report_title)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
