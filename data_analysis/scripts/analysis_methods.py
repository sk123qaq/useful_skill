#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from common import ensure_output_dir, module_available, parse_json_arg, slugify, write_json
from io_router import load_dataframe


TASK_ALIASES = {
    "cluster": "cluster",
    "clustering": "cluster",
    "apriori": "apriori",
    "association": "apriori",
    "association-rules": "apriori",
    "anova": "anova",
    "root-cause": "root-cause",
    "root_cause": "root-cause",
}


def normalize_task(task: str) -> str:
    normalized = task.strip().lower()
    if normalized not in TASK_ALIASES:
        raise ValueError(f"Unsupported analysis task: {task}")
    return TASK_ALIASES[normalized]


def _numeric_feature_frame(df: pd.DataFrame, feature_cols: list[str] | None = None, max_features: int = 8) -> tuple[pd.DataFrame, list[str]]:
    selected = feature_cols or list(df.select_dtypes(include=["number", "bool"]).columns)[:max_features]
    if not selected:
        raise ValueError("No numeric feature columns available for clustering.")
    frame = df[selected].copy()
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame.fillna(frame.median(numeric_only=True)).fillna(0.0)
    return frame.astype(float), selected


def _prepare_transactions(df: pd.DataFrame, config: dict[str, Any]) -> list[set[str]]:
    delimiter = str(config.get("delimiter", "|"))
    transaction_col = config.get("transaction_col")
    items_col = config.get("items_col")
    item_col = config.get("item_col")
    item_indicator_cols = config.get("item_indicator_cols")

    transactions: list[set[str]] = []
    if transaction_col and item_col:
        grouped = df.dropna(subset=[transaction_col, item_col]).groupby(transaction_col)[item_col].agg(list)
        for items in grouped:
            itemset = {str(item).strip() for item in items if str(item).strip()}
            if itemset:
                transactions.append(itemset)
        return transactions

    if items_col:
        for raw in df[items_col].dropna().tolist():
            itemset = {item.strip() for item in str(raw).split(delimiter) if item.strip()}
            if itemset:
                transactions.append(itemset)
        return transactions

    if item_indicator_cols:
        for _, row in df[item_indicator_cols].iterrows():
            itemset = {column for column in item_indicator_cols if bool(row[column])}
            if itemset:
                transactions.append(itemset)
        return transactions

    raise ValueError("Apriori requires `items_col`, `transaction_col + item_col`, or `item_indicator_cols` in config.")


def _frequent_itemsets(transactions: list[set[str]], min_support: float, max_len: int) -> dict[frozenset[str], float]:
    if not transactions:
        return {}
    transaction_count = len(transactions)
    min_count = max(1, int(np.ceil(min_support * transaction_count)))
    unique_items = sorted({item for basket in transactions for item in basket})

    current_level: dict[frozenset[str], int] = {}
    for item in unique_items:
        count = sum(1 for basket in transactions if item in basket)
        if count >= min_count:
            current_level[frozenset([item])] = count

    frequent: dict[frozenset[str], float] = {itemset: count / transaction_count for itemset, count in current_level.items()}
    level_itemsets = set(current_level.keys())
    k = 2
    while level_itemsets and k <= max_len:
        candidates: set[frozenset[str]] = set()
        previous = sorted(level_itemsets, key=lambda itemset: sorted(itemset))
        for i, left in enumerate(previous):
            for right in previous[i + 1 :]:
                union = left | right
                if len(union) != k:
                    continue
                if all(frozenset(subset) in level_itemsets for subset in combinations(union, k - 1)):
                    candidates.add(union)

        counts: dict[frozenset[str], int] = {}
        for candidate in candidates:
            count = sum(1 for basket in transactions if candidate.issubset(basket))
            if count >= min_count:
                counts[candidate] = count

        level_itemsets = set(counts.keys())
        frequent.update({itemset: count / transaction_count for itemset, count in counts.items()})
        k += 1

    return frequent


def _association_rules(
    frequent_itemsets: dict[frozenset[str], float],
    min_confidence: float,
    max_rules: int,
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for itemset, support in frequent_itemsets.items():
        if len(itemset) < 2:
            continue
        items = sorted(itemset)
        for r in range(1, len(items)):
            for antecedent_tuple in combinations(items, r):
                antecedent = frozenset(antecedent_tuple)
                consequent = itemset - antecedent
                antecedent_support = frequent_itemsets.get(antecedent)
                consequent_support = frequent_itemsets.get(consequent)
                if not antecedent_support or not consequent_support:
                    continue
                confidence = support / antecedent_support
                if confidence < min_confidence:
                    continue
                lift = confidence / consequent_support if consequent_support else None
                leverage = support - antecedent_support * consequent_support
                rules.append(
                    {
                        "antecedent": sorted(antecedent),
                        "consequent": sorted(consequent),
                        "support": float(support),
                        "confidence": float(confidence),
                        "lift": float(lift) if lift is not None else None,
                        "leverage": float(leverage),
                    }
                )
    rules.sort(key=lambda item: (item.get("lift") or 0.0, item["confidence"], item["support"]), reverse=True)
    return rules[:max_rules]


def _configure_plotting() -> None:
    if not module_available("matplotlib"):
        return
    from explain_viz import _configure_chinese_font

    _configure_chinese_font()


def clustering_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    feature_cols = config.get("feature_cols")
    max_features = int(config.get("max_features", 8))
    frame, selected_features = _numeric_feature_frame(df, feature_cols=feature_cols, max_features=max_features)

    if len(frame) < 4:
        raise ValueError("Clustering needs at least 4 usable rows.")

    scale_features = bool(config.get("standardize", True))
    scaler = StandardScaler() if scale_features else None
    matrix = scaler.fit_transform(frame) if scaler else frame.to_numpy(dtype=float)

    chosen_k = config.get("n_clusters")
    candidate_scores: list[dict[str, Any]] = []
    if chosen_k is None:
        max_k = min(int(config.get("max_clusters", 6)), max(2, len(frame) - 1))
        for k in range(2, max_k + 1):
            model = KMeans(n_clusters=k, n_init=20, random_state=42)
            with contextlib.redirect_stderr(io.StringIO()):
                labels = model.fit_predict(matrix)
            if len(set(labels)) < 2:
                continue
            with contextlib.redirect_stderr(io.StringIO()):
                score = silhouette_score(matrix, labels)
            candidate_scores.append({"n_clusters": k, "silhouette_score": float(score)})
        if not candidate_scores:
            raise ValueError("Unable to select clusters automatically. Try passing `n_clusters`.")
        chosen_k = max(candidate_scores, key=lambda item: item["silhouette_score"])["n_clusters"]

    model = KMeans(n_clusters=int(chosen_k), n_init=20, random_state=42)
    with contextlib.redirect_stderr(io.StringIO()):
        labels = model.fit_predict(matrix)
    profiled = frame.copy()
    profiled["cluster"] = labels
    cluster_sizes = profiled["cluster"].value_counts().sort_index()
    cluster_profiles = profiled.groupby("cluster")[selected_features].mean().round(4)

    report: dict[str, Any] = {
        "task": "cluster",
        "feature_cols": selected_features,
        "n_rows_used": int(len(frame)),
        "n_clusters": int(chosen_k),
        "selection_metric": "silhouette" if candidate_scores else "user_supplied",
        "candidate_scores": candidate_scores,
        "cluster_sizes": {str(cluster): int(size) for cluster, size in cluster_sizes.items()},
        "cluster_profiles": {
            str(cluster): {feature: float(value) for feature, value in row.items()}
            for cluster, row in cluster_profiles.iterrows()
        },
        "artifacts": [],
    }

    if scaler is not None:
        centers = scaler.inverse_transform(model.cluster_centers_)
    else:
        centers = model.cluster_centers_
    report["cluster_centers"] = {
        str(index): {feature: float(value) for feature, value in zip(selected_features, center)}
        for index, center in enumerate(centers)
    }

    if output_dir is not None:
        assignments = df.loc[frame.index].copy()
        assignments["cluster"] = labels
        assignment_path = output_dir / "cluster_assignments.csv"
        assignments.to_csv(assignment_path, index=False)
        report["assignments_artifact"] = str(assignment_path)
        report["artifacts"].append(str(assignment_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.bar([str(cluster) for cluster in cluster_sizes.index], cluster_sizes.values)
            ax.set_title("Cluster sizes")
            ax.set_xlabel("Cluster")
            ax.set_ylabel("Rows")
            path = output_dir / "cluster_sizes.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            if len(selected_features) >= 2:
                projection = PCA(n_components=2, random_state=42).fit_transform(matrix)
                fig, ax = plt.subplots(figsize=(7, 5))
                scatter = ax.scatter(projection[:, 0], projection[:, 1], c=labels, cmap="tab10", alpha=0.85)
                ax.set_title("Cluster projection (PCA)")
                ax.set_xlabel("PC1")
                ax.set_ylabel("PC2")
                legend = ax.legend(*scatter.legend_elements(), title="Cluster", loc="best")
                ax.add_artist(legend)
                path = output_dir / "cluster_projection.png"
                fig.tight_layout()
                fig.savefig(path, dpi=150)
                plt.close(fig)
                report["artifacts"].append(str(path))

    return report


def apriori_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    transactions = _prepare_transactions(df, config)
    if len(transactions) < 3:
        raise ValueError("Apriori needs at least 3 transactions.")

    min_support = float(config.get("min_support", 0.2))
    min_confidence = float(config.get("min_confidence", 0.5))
    max_len = int(config.get("max_len", 3))
    max_rules = int(config.get("max_rules", 10))
    frequent_itemsets = _frequent_itemsets(transactions, min_support=min_support, max_len=max_len)
    rules = _association_rules(frequent_itemsets, min_confidence=min_confidence, max_rules=max_rules)

    frequent_rows = [
        {"items": sorted(itemset), "size": len(itemset), "support": float(support)}
        for itemset, support in sorted(frequent_itemsets.items(), key=lambda item: (len(item[0]), item[1], sorted(item[0])), reverse=True)
    ]

    report: dict[str, Any] = {
        "task": "apriori",
        "n_transactions": int(len(transactions)),
        "unique_items": int(len({item for basket in transactions for item in basket})),
        "min_support": min_support,
        "min_confidence": min_confidence,
        "max_len": max_len,
        "frequent_itemsets": frequent_rows[:20],
        "rules": rules,
        "artifacts": [],
    }

    if output_dir is not None and output_dir:
        rules_path = output_dir / "association_rules.json"
        write_json(rules_path, {"rules": rules})
        report["artifacts"].append(str(rules_path))

        if rules and module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            top_rules = rules[: min(len(rules), 8)]
            labels = [" + ".join(rule["antecedent"]) + " -> " + " + ".join(rule["consequent"]) for rule in top_rules]
            lifts = [rule["lift"] or 0.0 for rule in top_rules]
            fig, ax = plt.subplots(figsize=(9, 5))
            ax.barh(labels[::-1], lifts[::-1])
            ax.set_title("Top association rules by lift")
            ax.set_xlabel("Lift")
            path = output_dir / "association_rules_lift.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def anova_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    import scipy.stats as stats

    target = config.get("target")
    group_col = config.get("group_col")
    alpha = float(config.get("alpha", 0.05))
    if not target or not group_col:
        raise ValueError("ANOVA requires `target` and `group_col` in config.")

    frame = df[[group_col, target]].dropna().copy()
    frame[target] = pd.to_numeric(frame[target], errors="coerce")
    frame = frame.dropna(subset=[target])
    grouped = {str(name): group[target].astype(float).to_numpy() for name, group in frame.groupby(group_col)}
    grouped = {name: values for name, values in grouped.items() if len(values) >= 2}
    if len(grouped) < 2:
        raise ValueError("ANOVA needs at least two groups with at least two observations each.")

    group_stats = {
        name: {
            "count": int(len(values)),
            "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
            "median": float(np.median(values)),
        }
        for name, values in grouped.items()
    }

    normality = {}
    all_normal = True
    for name, values in grouped.items():
        if len(values) < 3:
            normality[name] = {"available": False, "reason": "Need at least 3 rows for Shapiro-Wilk."}
            all_normal = False
            continue
        sample = values[:5000]
        statistic, p_value = stats.shapiro(sample)
        normality[name] = {
            "test": "shapiro",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "approximately_normal_at_0_05": bool(p_value >= 0.05),
        }
        all_normal = all_normal and p_value >= alpha

    levene_stat, levene_p = stats.levene(*grouped.values(), center="median")
    equal_variance = bool(levene_p >= alpha)

    recommended_test = "anova" if all_normal and equal_variance else "kruskal"
    if recommended_test == "anova":
        statistic, p_value = stats.f_oneway(*grouped.values())
        overall_mean = float(frame[target].mean())
        ss_between = sum(len(values) * (float(np.mean(values)) - overall_mean) ** 2 for values in grouped.values())
        ss_total = float(((frame[target] - overall_mean) ** 2).sum())
        effect_size = ss_between / ss_total if ss_total else 0.0
        result = {
            "test": "one_way_anova",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "significant_at_alpha": bool(p_value < alpha),
            "effect_size_name": "eta_squared",
            "effect_size": float(effect_size),
        }
        tukey_rows: list[dict[str, Any]] = []
        if result["significant_at_alpha"] and module_available("statsmodels"):
            from statsmodels.stats.multicomp import pairwise_tukeyhsd  # type: ignore

            tukey = pairwise_tukeyhsd(endog=frame[target], groups=frame[group_col], alpha=alpha)
            headers = tukey.summary().data[0]
            for row in tukey.summary().data[1:]:
                record = dict(zip(headers, row))
                tukey_rows.append(
                    {
                        "group1": str(record["group1"]),
                        "group2": str(record["group2"]),
                        "mean_diff": float(record["meandiff"]),
                        "p_adj": float(record["p-adj"]),
                        "lower": float(record["lower"]),
                        "upper": float(record["upper"]),
                        "reject": bool(record["reject"]),
                    }
                )
        result["posthoc_tukey"] = tukey_rows
    else:
        statistic, p_value = stats.kruskal(*grouped.values())
        n_total = int(sum(len(values) for values in grouped.values()))
        k = int(len(grouped))
        effect_size = (float(statistic) - k + 1) / (n_total - k) if n_total > k else 0.0
        result = {
            "test": "kruskal_wallis",
            "statistic": float(statistic),
            "p_value": float(p_value),
            "significant_at_alpha": bool(p_value < alpha),
            "effect_size_name": "epsilon_squared",
            "effect_size": float(max(effect_size, 0.0)),
            "posthoc_tukey": [],
        }

    report: dict[str, Any] = {
        "task": "anova",
        "target": target,
        "group_col": group_col,
        "alpha": alpha,
        "group_statistics": group_stats,
        "assumptions": {
            "normality_by_group": normality,
            "variance_homogeneity": {
                "test": "levene",
                "statistic": float(levene_stat),
                "p_value": float(levene_p),
                "equal_variance_at_alpha": equal_variance,
            },
        },
        "recommended_test": recommended_test,
        "result": result,
        "artifacts": [],
    }

    if output_dir is not None and module_available("matplotlib"):
        import matplotlib.pyplot as plt  # type: ignore

        _configure_plotting()
        ordered_groups = sorted(grouped.keys())
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.boxplot([grouped[name] for name in ordered_groups], labels=ordered_groups)
        ax.set_title(f"{target} by {group_col}")
        ax.set_xlabel(group_col)
        ax.set_ylabel(target)
        path = output_dir / f"anova_{slugify(target)}_by_{slugify(group_col)}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        report["artifacts"].append(str(path))

    return report


def _segment_label(record: dict[str, Any], dimension_cols: list[str]) -> str:
    return " | ".join(f"{column}={record[column]}" for column in dimension_cols)


def root_cause_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    metric_col = config.get("metric_col")
    if not metric_col:
        raise ValueError("Root-cause analysis requires `metric_col` in config.")
    compare_col = config.get("compare_col")
    dimension_cols = config.get("dimension_cols") or list(df.select_dtypes(exclude=["number", "bool"]).columns)[:2]
    dimension_cols = [column for column in dimension_cols if column != compare_col]
    if not dimension_cols:
        raise ValueError("Root-cause analysis needs at least one dimension column.")

    frame = df[dimension_cols + [metric_col] + ([compare_col] if compare_col else [])].copy()
    frame[metric_col] = pd.to_numeric(frame[metric_col], errors="coerce")
    frame = frame.dropna(subset=[metric_col])
    top_n = int(config.get("top_n", 8))

    if compare_col:
        baseline_value = config.get("baseline_value")
        current_value = config.get("current_value")
        if baseline_value is None or current_value is None:
            available = sorted(frame[compare_col].dropna().astype(str).unique().tolist())
            if len(available) < 2:
                raise ValueError("Root-cause compare mode needs two compare values.")
            baseline_value, current_value = available[:2]

        baseline = frame.loc[frame[compare_col].astype(str) == str(baseline_value)]
        current = frame.loc[frame[compare_col].astype(str) == str(current_value)]
        baseline_grouped = baseline.groupby(dimension_cols)[metric_col].agg(["sum", "mean", "count"]).reset_index()
        current_grouped = current.groupby(dimension_cols)[metric_col].agg(["sum", "mean", "count"]).reset_index()
        merged = baseline_grouped.merge(current_grouped, on=dimension_cols, how="outer", suffixes=("_baseline", "_current")).fillna(0.0)
        merged["delta"] = merged["sum_current"] - merged["sum_baseline"]
        total_delta = float(merged["delta"].sum())
        merged["delta_share"] = merged["delta"] / total_delta if total_delta else 0.0
        merged["segment"] = merged.apply(lambda row: _segment_label(row.to_dict(), dimension_cols), axis=1)
        ranked = merged.sort_values("delta", ascending=False)
        segment_rows = [
            {
                "segment": row["segment"],
                "baseline_sum": float(row["sum_baseline"]),
                "current_sum": float(row["sum_current"]),
                "baseline_mean": float(row["mean_baseline"]),
                "current_mean": float(row["mean_current"]),
                "baseline_count": int(row["count_baseline"]),
                "current_count": int(row["count_current"]),
                "delta": float(row["delta"]),
                "delta_share": float(row["delta_share"]),
            }
            for _, row in ranked.iterrows()
        ]
        positive_rows = [row for row in segment_rows if row["delta"] > 0]
        negative_rows = sorted((row for row in segment_rows if row["delta"] < 0), key=lambda row: row["delta"])
        report: dict[str, Any] = {
            "task": "root-cause",
            "metric_col": metric_col,
            "dimension_cols": dimension_cols,
            "compare_col": compare_col,
            "baseline_value": baseline_value,
            "current_value": current_value,
            "overall_delta": total_delta,
            "top_positive_drivers": positive_rows[:top_n],
            "top_negative_drivers": negative_rows[:top_n],
            "segment_table": segment_rows,
            "artifacts": [],
        }
    else:
        grouped = frame.groupby(dimension_cols)[metric_col].agg(["sum", "mean", "count"]).reset_index()
        overall_mean = float(frame[metric_col].mean())
        grouped["weighted_deviation"] = (grouped["mean"] - overall_mean) * grouped["count"]
        grouped["segment"] = grouped.apply(lambda row: _segment_label(row.to_dict(), dimension_cols), axis=1)
        ranked = grouped.sort_values("weighted_deviation", ascending=False)
        segment_rows = [
            {
                "segment": row["segment"],
                "sum": float(row["sum"]),
                "mean": float(row["mean"]),
                "count": int(row["count"]),
                "weighted_deviation": float(row["weighted_deviation"]),
            }
            for _, row in ranked.iterrows()
        ]
        positive_rows = [row for row in segment_rows if row["weighted_deviation"] > 0]
        negative_rows = sorted(
            (row for row in segment_rows if row["weighted_deviation"] < 0),
            key=lambda row: row["weighted_deviation"],
        )
        report = {
            "task": "root-cause",
            "metric_col": metric_col,
            "dimension_cols": dimension_cols,
            "overall_mean": overall_mean,
            "top_positive_drivers": positive_rows[:top_n],
            "top_negative_drivers": negative_rows[:top_n],
            "segment_table": segment_rows,
            "artifacts": [],
        }

    if output_dir is not None and module_available("matplotlib"):
        import matplotlib.pyplot as plt  # type: ignore

        _configure_plotting()
        drivers = report["top_positive_drivers"][: max(3, min(top_n, 6))]
        if drivers:
            fig, ax = plt.subplots(figsize=(9, 5))
            labels = [row["segment"] for row in drivers][::-1]
            values = [row.get("delta", row.get("weighted_deviation", 0.0)) for row in drivers][::-1]
            colors = ["#2ca02c" if value >= 0 else "#d62728" for value in values]
            ax.barh(labels, values, color=colors)
            ax.set_title("Top root-cause drivers")
            ax.set_xlabel("Contribution")
            path = output_dir / "root_cause_drivers.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def run_analysis_method(df: pd.DataFrame, task: str, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    normalized = normalize_task(task)
    if normalized == "cluster":
        return clustering_analysis(df, config, output_dir=output_dir)
    if normalized == "apriori":
        return apriori_analysis(df, config, output_dir=output_dir)
    if normalized == "anova":
        return anova_analysis(df, config, output_dir=output_dir)
    if normalized == "root-cause":
        return root_cause_analysis(df, config, output_dir=output_dir)
    raise ValueError(f"Unsupported analysis task: {task}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run clustering, association, ANOVA, or root-cause analysis.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--task", required=True, choices=sorted(TASK_ALIASES.keys()))
    parser.add_argument("--output-dir")
    parser.add_argument("--config-json")
    args = parser.parse_args()

    output_dir = ensure_output_dir(args.output_dir, prefix="analysis-method") if args.output_dir else None
    config = parse_json_arg(args.config_json)
    df = load_dataframe(args.input_path)
    report = run_analysis_method(df, task=args.task, config=config, output_dir=output_dir)
    if output_dir is not None:
        write_json(output_dir / "analysis_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
