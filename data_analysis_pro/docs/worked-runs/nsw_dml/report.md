# 职业培训对1978年收入的平均处理效应（DML）

- **任务类型**: `causal`
- **分析单元**: 个人
- **数据来源**: /tmp/nsw.csv
- **数据范围**: full
- **目标/时间**: target=`re78`, time=`None`
- **证据等级（gate）**: `report-ready`

## 决策问题

职业培训对1978年收入的平均处理效应（DML）

## 数据与口径

- 行数: 445; 列数: 11; 来源: `/tmp/nsw.csv`
- 清洗: 445 → 445 行; 重复删除 0

## 方法

路线由 `analysis_contract.json` 固定为 `causal`；特征风险、切分、基线等前置工件见工件索引。

## 结果

### 因果

- 设计: `dml`; 估计量: `ATE`
- 点估计: 2110; 95% CI: [636.5433235289588, 3583.7446314818294]; p=0.005006
- 方法/任务: `dml`; 假设与局限见 `causal_design.json` / `causal_report.json`

## 结论（仅 claim_registry）

- **[C1]** 在条件可交换与重叠假设下，职业培训对1978年收入的DML ATE约为2110美元（95% CI 637–3584，p=0.005）。 — 证据: `causal_report.json`, `causal_design.json`; 等级: `report-ready`

## 局限

见各工件 limitations 字段；未列出的口径风险不应假定不存在。

## 工件索引

| path | bytes | sha256 |
|---|---|---|
| analysis_contract.json | 689 | 7ec169ac55ae91fc |
| causal_design.json | 498 | 0d17d7572c371dc7 |
| causal_narrative_report.json | 1856 | fedba44623bfca4d |
| causal_narrative_report.md | 2787 | d4a688590866bc83 |
| causal_report.json | 1128 | 9b8dc97bbeba49d5 |
| claim_registry.json | 273 | 4b48728a22ec89b3 |
| clean.csv | 24593 | 75be812b62c26579 |
| cleaning_report.json | 6523 | 5169fbdc292402d6 |
| data_manifest.json | 439 | 6bb4f00a620d1226 |
| dml_residual_fit.png | 86571 | cc793f0aae2645ef |
| dml_residuals.csv | 49952 | d96709856b85ab91 |
| dml_score_distribution.png | 25522 | 460632c4dd01c178 |
| feature_risk_report.json | 2864 | bb0db5b26484c33f |
| features.csv | 24593 | 75be812b62c26579 |
| features.json | 365 | d6371031ef490ba9 |
| gate_review.json | 1427 | 2f282766bf53cfb5 |
| profile.json | 6941 | c4b62f3862d09d61 |
| route_decision.json | 206 | 6b5ba66766742a33 |
