# 公开数据实跑记录

这两组例子用于验证因果/实验分支的完整链路：契约 → 清单/画像/清洗 → 特征风险 → 路由 → 分支 → gate → claim → report/lint。数据来自 Python 包 `causaldata`（`uv pip install causaldata`）。本次运行的报告与 gate 工件保存在 `docs/worked-runs/`。

## 1. 因果：NSW 职业培训（PSM / DML）

数据：`causaldata.nsw_mixtape`，445 行；处理 `treat`（185/260），结果 `re78`，协变量 `age, educ, black, hisp, marr, nodegree, re74, re75`。

```bash
python - <<'PY'
import causaldata
causaldata.nsw_mixtape.load_pandas().data.to_csv('/tmp/nsw.csv', index=False)
PY

RUN=/tmp/nsw_causal
python scripts/contract.py init --question "职业培训对1978年收入的处理效应" \
  --task causal --target re78 --unit-of-analysis 个人 --data-source /tmp/nsw.csv \
  --success-criteria "估计 ATT 并给出识别假设" --stop-conditions "重叠不足/假设不成立" \
  --output-path "$RUN/analysis_contract.json"
python scripts/io_router.py manifest --input-path /tmp/nsw.csv --output-path "$RUN/data_manifest.json"
python scripts/column_profile.py --input-path /tmp/nsw.csv --target re78 --output-path "$RUN/profile.json"
python scripts/clean.py --input-path /tmp/nsw.csv --output-path "$RUN/clean.csv" \
  --report-path "$RUN/cleaning_report.json" --target re78
python scripts/features.py --input-path "$RUN/clean.csv" --output-path "$RUN/features.csv" \
  --report-path "$RUN/features.json"
python scripts/feature_risk.py scan --input-path "$RUN/features.csv" \
  --contract "$RUN/analysis_contract.json" --output-path "$RUN/feature_risk_report.json"
python scripts/feature_risk.py confirm --report "$RUN/feature_risk_report.json" \
  --labels '{"age":{"label":"safe"},"educ":{"label":"safe"},"black":{"label":"safe"},"hisp":{"label":"safe"},"marr":{"label":"safe"},"nodegree":{"label":"safe"},"re74":{"label":"safe"},"re75":{"label":"safe"},"treat":{"label":"safe"},"data_id":{"label":"collection_artifact","used":false}}' \
  --output-path "$RUN/feature_risk_report.json"
python scripts/causal_design.py init --estimand ATT --treatment treat --outcome re78 --design psm \
  --assumptions "conditional exchangeability,common support,no unmeasured confounding" \
  --adjustment "age,educ,black,hisp,marr,nodegree,re74,re75" --sensitivity "rosenbaum bounds" \
  --data-path /tmp/nsw.csv --output-path "$RUN/causal_design.json"
python scripts/route.py init --route causal --reasons "有处理/对照/结果与可观测混杂" \
  --output-path "$RUN/route_decision.json"
python scripts/causal_analysis.py --input-path /tmp/nsw.csv --task psm --output-dir "$RUN" \
  --config-json '{"treatment_col":"treat","outcome_col":"re78","covariate_cols":["age","educ","black","hisp","marr","nodegree","re74","re75"],"caliper":0.05}'
```

结果：ATT=1863.01，95% CI [372.02, 3353.99]，p=.01464；167 对匹配；共同支撑 97.3%。gate=`report-ready`，report_lint 通过。

DML 用同一数据、`--task dml`、`--design dml`，估计 ATE=2110.14，95% CI [636.54, 3583.74]，p=.00501；`/tmp/nsw_dml` 同样 gate=`report-ready`、lint 通过。

## 2. 实验：议员邮件回复（两臂）

数据：`causaldata.black_politicians`，5593 行；处理 `treat_out`（2814/2779），结果 `responded`；协变量 `blackpercent, medianhhincom, south, leg_democrat, leg_senator`。

配置 `experiment_config.json`：

```json
{
  "group_col": "treat_out",
  "control": 0,
  "treatment": 1,
  "alpha": 0.05,
  "expected_allocation": {"0": 0.5, "1": 0.5},
  "metrics": [
    {"name": "responded", "role": "primary", "type": "binary", "success_value": 1,
     "preferred_direction": "increase", "practical_significance": 0.02},
    {"name": "totalpop", "role": "secondary", "type": "continuous"}
  ],
  "covariates": ["blackpercent", "medianhhincom", "south", "leg_democrat", "leg_senator"],
  "multiple_testing": {"method": "holm", "metric_names": ["responded", "totalpop"]},
  "power_analysis": {"metric_names": ["responded"], "power": 0.8, "mde": {"responded": 0.05}},
  "sequential_monitoring": {"method": "obrien_fleming", "information_fraction": 0.5,
                             "total_looks": 2, "metric_names": ["responded"]}
}
```

```bash
python scripts/experiment_analysis.py --input-path /tmp/black_politicians.csv \
  --config-json experiment_config.json --output-path "$RUN/experiment_report.json"
```

结果：SRM p=.6398；平衡性 Bonferroni 通过，`medianhhincom` p=.04985 记为边际；回复率 55.51% → 28.90%，绝对效应 -26.61pp，p=3.06e-90；decision=`do_not_ship_treatment`。gate=`report-ready`，report_lint 通过。

## 解读边界

- NSW 是观察性样本，PSM/DML 的因果解释依赖条件可交换、重叠和无未测混杂；不能把数值当成无假设的实验效应。
- 议员邮件是田野实验，但 `responded` 的测量与样本选择仍需按原论文口径解释；`do_not_ship` 只针对该处理，不外推到所有外区邮件。
- 两个数据集都用于链路验收，不替代业务数据上的设计审查。
