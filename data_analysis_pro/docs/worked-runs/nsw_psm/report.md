# 职业培训对1978年收入的处理效应

- **任务类型**: `causal`
- **分析单元**: 个人
- **数据来源**: /tmp/nsw.csv
- **数据范围**: full
- **目标/时间**: target=`re78`, time=`None`
- **证据等级（gate）**: `report-ready`

## 决策问题

职业培训对1978年收入的处理效应

## 数据与口径

- 行数: 445; 列数: 11; 来源: `/tmp/nsw.csv`
- 清洗: 445 → 445 行; 重复删除 0

## 方法

路线由 `analysis_contract.json` 固定为 `causal`；特征风险、切分、基线等前置工件见工件索引。

## 结果

### 因果

- 设计: `psm`; 估计量: `ATT`
- 点估计: 1863; 95% CI: [372.02484571725404, 3353.9932254204705]; p=0.01464
- 方法/任务: `psm`; 假设与局限见 `causal_design.json` / `causal_report.json`

## 结论（仅 claim_registry）

- **[C1]** 在共同支撑与可观测混杂假设下，职业培训对参与者1978年收入的ATT约为1863美元（95% CI 372–3354，p=0.015）。 — 证据: `causal_report.json`, `causal_design.json`; 等级: `report-ready`

## 局限

见各工件 limitations 字段；未列出的口径风险不应假定不存在。

## 工件索引

| path | bytes | sha256 |
|---|---|---|
| analysis_contract.json | 665 | 5c3b2178a9682d0b |
| causal_design.json | 510 | 4a9def6f84c5df8d |
| causal_narrative_report.json | 1858 | 7ca81e020890a08c |
| causal_narrative_report.md | 2749 | 194a64aeb2d5187b |
| causal_report.json | 7618 | 77f48708a2da0ea6 |
| claim_registry.json | 284 | dffb1c491b84ce10 |
| clean.csv | 24593 | 75be812b62c26579 |
| cleaning_report.json | 6526 | 7910b5c372e5e903 |
| data_manifest.json | 439 | fa50a49e2f7202bf |
| feature_risk_report.json | 2870 | 37645804242b7d2a |
| features.csv | 24593 | 75be812b62c26579 |
| features.json | 371 | a4b2886bd4e238ca |
| gate_review.json | 1427 | 4379c1aa437e77fb |
| profile.json | 6941 | a6513f26c4db36d4 |
| psm_balance_smd.png | 33062 | 37c8246002e95990 |
| psm_matched_pairs.csv | 16972 | bdd369afe0e2c1b0 |
| psm_propensity_overlap.png | 28337 | 781456142c7f2677 |
| route_decision.json | 197 | 3f657d33a2aff4b9 |
