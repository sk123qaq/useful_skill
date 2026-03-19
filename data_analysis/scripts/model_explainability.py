#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common import configure_matplotlib_defaults, ensure_output_dir, friendly_chart_feature_label, parse_json_arg, write_json
from io_router import load_dataframe
from model_runner import fit_selected_model


def _configure_chinese_font():
    preferred_fonts = [
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "PingFang SC",
        "Hiragino Sans GB",
        "Songti SC",
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
    ]
    return configure_matplotlib_defaults(preferred_fonts)


def native_feature_importance(model, feature_names: list[str], top_n: int = 15) -> list[dict[str, Any]]:
    values = None
    if hasattr(model, "feature_importances_"):
        values = np.asarray(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        coefficients = np.asarray(model.coef_, dtype=float)
        if coefficients.ndim > 1:
            coefficients = np.mean(np.abs(coefficients), axis=0)
        values = np.abs(coefficients)
    if values is None:
        return []
    ranking = sorted(zip(feature_names, values.tolist()), key=lambda item: item[1], reverse=True)
    return [{"feature": feature, "importance": float(importance)} for feature, importance in ranking[:top_n]]


def permutation_feature_importance(model, X_test, y_test, task: str, top_n: int = 15) -> list[dict[str, Any]]:
    from sklearn.inspection import permutation_importance

    scoring = "f1_weighted" if task == "classification" else "r2"
    X_numeric = _coerce_numeric_matrix(X_test)
    result = permutation_importance(model, X_numeric, y_test, n_repeats=10, random_state=42, scoring=scoring, n_jobs=1)
    ranking = sorted(
        zip(X_numeric.columns.tolist(), result.importances_mean.tolist(), result.importances_std.tolist()),
        key=lambda item: item[1],
        reverse=True,
    )
    return [
        {"feature": feature, "importance_mean": float(mean_value), "importance_std": float(std_value)}
        for feature, mean_value, std_value in ranking[:top_n]
    ]


def _coerce_numeric_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.astype(float)


def _is_binary_indicator(series: pd.Series) -> bool:
    unique_values = sorted(series.dropna().unique().tolist())
    return bool(unique_values) and set(unique_values).issubset({0.0, 1.0}) and len(unique_values) <= 2


def _choose_pdp_features(X_train: pd.DataFrame, ranked_features: list[str], limit: int = 3) -> list[str]:
    selected: list[str] = []
    fallback: list[str] = []
    for feature in ranked_features:
        if feature not in X_train.columns:
            continue
        series = X_train[feature]
        unique_count = int(series.nunique(dropna=True))
        if unique_count >= 4:
            selected.append(feature)
        elif unique_count > 1:
            fallback.append(feature)
        if len(selected) >= limit:
            break

    if selected:
        return selected[:limit]

    if len(selected) < limit:
        for feature in fallback:
            if feature not in selected:
                selected.append(feature)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _partial_dependence_curve(model, X_numeric: pd.DataFrame, feature: str) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.inspection import partial_dependence

    result = partial_dependence(model, X_numeric, [feature])
    average = np.asarray(result["average"][0], dtype=float)
    values = result.get("grid_values")
    if values is None:
        values = result.get("values")
    if values is None:
        raise ValueError("partial_dependence result missing grid values")
    grid = np.asarray(values[0], dtype=float)
    return grid, average


def _save_binary_partial_dependence_plot(model, X_numeric: pd.DataFrame, feature: str, output_dir: Path) -> str:
    import matplotlib.pyplot as plt  # type: ignore

    grid, average = _partial_dependence_curve(model, X_numeric, feature)
    fig, ax = plt.subplots(figsize=(6.8, 5))
    display_label = friendly_chart_feature_label(feature)
    positions = np.arange(len(grid))
    ax.bar(positions, average, width=0.55, color=["#5B8FF9", "#5AD8A6"][: len(positions)], edgecolor="#3D4A57")
    for index, value in enumerate(average):
        ax.text(index, value, f"{value:.3f}", ha="center", va="bottom", fontsize=10)
    ax.set_title(f"{display_label}部分依赖图")
    ax.set_xlabel(display_label)
    ax.set_ylabel("模型预测变化")
    ax.set_xticks(positions)
    if set(grid.tolist()).issubset({0.0, 1.0}):
        ax.set_xticklabels(["否", "是"][: len(positions)])
    else:
        ax.set_xticklabels([str(item) for item in grid.tolist()])
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    path = output_dir / f"pdp_{feature}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return str(path)


def shap_feature_importance(model, X_sample, output_dir: Path, top_n: int = 15) -> dict[str, Any]:
    try:
        import matplotlib.pyplot as plt  # type: ignore
        import shap  # type: ignore

        _configure_chinese_font()
        X_numeric = _coerce_numeric_matrix(X_sample)
        display_feature_names = [friendly_chart_feature_label(column) for column in X_numeric.columns]
        explainer = shap.TreeExplainer(model)
        values = explainer.shap_values(X_numeric)
        if isinstance(values, list):
            values = np.stack([np.asarray(item, dtype=float) for item in values], axis=-1)
        else:
            values = np.asarray(values, dtype=float)
        if values.ndim == 3:
            values = np.mean(np.abs(values), axis=2)
        mean_abs = np.mean(np.abs(values), axis=0)
        ranking = sorted(zip(X_numeric.columns.tolist(), mean_abs.tolist()), key=lambda item: item[1], reverse=True)

        shap.summary_plot(
            values,
            X_numeric.to_numpy(),
            feature_names=display_feature_names,
            plot_type="bar",
            max_display=min(top_n, len(X_numeric.columns)),
            show=False,
        )
        ax = plt.gca()
        ax.set_title("SHAP 特征重要性", fontsize=13)
        ax.set_xlabel("平均 |SHAP| 影响强度")
        bar_path = output_dir / "shap_bar.png"
        plt.tight_layout()
        plt.savefig(bar_path, dpi=150, bbox_inches="tight")
        plt.close()

        return {
            "available": True,
            "top_features": [{"feature": feature, "mean_abs_shap": float(value)} for feature, value in ranking[:top_n]],
            "artifact": str(bar_path),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def save_partial_dependence_plots(model, X_train, features: list[str], output_dir: Path) -> list[str]:
    from sklearn.inspection import PartialDependenceDisplay
    import matplotlib.pyplot as plt  # type: ignore

    _configure_chinese_font()
    artifacts = []
    X_numeric = _coerce_numeric_matrix(X_train)
    for feature in features:
        if _is_binary_indicator(X_numeric[feature]):
            artifacts.append(_save_binary_partial_dependence_plot(model, X_numeric, feature, output_dir))
            continue
        fig, ax = plt.subplots(figsize=(7, 5))
        display = PartialDependenceDisplay.from_estimator(model, X_numeric, [feature], ax=ax)
        plot_ax = display.axes_[0, 0] if getattr(display, "axes_", None) is not None else ax
        display_label = friendly_chart_feature_label(feature)
        plot_ax.set_title(f"{display_label}部分依赖图")
        plot_ax.set_xlabel(display_label)
        plot_ax.set_ylabel("模型预测变化")
        path = output_dir / f"pdp_{feature}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        artifacts.append(str(path))
    return artifacts


def explain_supervised_model(
    df,
    target: str,
    task: str,
    output_dir: Path,
    model_name: str | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    fitted = fit_selected_model(df, target=target, task=task, model_name=model_name)
    model = fitted["model"]
    X_train = fitted["X_train"]
    X_test = fitted["X_test"]
    y_test = fitted["y_test"]

    native = native_feature_importance(model, fitted["feature_names"], top_n=top_n)
    permutation = permutation_feature_importance(model, X_test, y_test, task=task, top_n=top_n)
    prioritized_features = _choose_pdp_features(
        X_train,
        [item["feature"] for item in permutation] or [item["feature"] for item in native],
        limit=3,
    )

    pdp_artifacts: list[str] = []
    if prioritized_features:
        try:
            pdp_artifacts = save_partial_dependence_plots(model, X_train, prioritized_features[:3], output_dir)
        except Exception:
            pdp_artifacts = []

    shap_report = shap_feature_importance(model, X_test.head(min(len(X_test), 200)), output_dir, top_n=top_n)

    return {
        "task": task,
        "model_name": fitted["model_name"],
        "native_feature_importance": native,
        "permutation_importance": permutation,
        "partial_dependence_features": prioritized_features[:3],
        "partial_dependence_artifacts": pdp_artifacts,
        "shap": shap_report,
        "train_rows": int(len(fitted["X_train"])),
        "test_rows": int(len(fitted["X_test"])),
        "n_features": int(len(fitted["feature_names"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate explainability artifacts for a fitted supervised model.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--task", required=True, choices=["classification", "regression"])
    parser.add_argument("--target", required=True)
    parser.add_argument("--model-name")
    parser.add_argument("--output-dir")
    parser.add_argument("--config-json")
    args = parser.parse_args()

    output_dir = ensure_output_dir(args.output_dir, prefix="explainability")
    config = parse_json_arg(args.config_json)
    top_n = int(config.get("top_n", 10)) if config else 10

    df = load_dataframe(args.input_path)
    report = explain_supervised_model(df, target=args.target, task=args.task, output_dir=output_dir, model_name=args.model_name, top_n=top_n)
    write_json(output_dir / "explainability_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
