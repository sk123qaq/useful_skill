# 外区邮件是否降低议员回复率

- **任务类型**: `experiment`
- **分析单元**: 议员
- **数据来源**: /tmp/black_politicians.csv
- **数据范围**: full
- **目标/时间**: target=`responded`, time=`None`
- **证据等级（gate）**: `report-ready`

## 决策问题

外区邮件是否降低议员回复率

## 数据与口径

- 行数: 5593; 列数: 14; 来源: `/tmp/black_politicians.csv`
- 清洗: 5593 → 5593 行; 重复删除 0

## 方法

路线由 `analysis_contract.json` 固定为 `experiment`；特征风险、切分、基线等前置工件见工件索引。

## 结果

### 实验

- 主指标: `responded`; 效应: -0.2661; p=3.059e-90
- SRM p=0.6398; 平衡性通过: `True`
- 决策: `do_not_ship_treatment` — Treatment shows statistically significant regressions on a primary or guardrail metric.

## 结论（仅 claim_registry）

- **[C1]** 外区邮件使议员回复率从55.5%降至28.9%，绝对效应-26.6个百分点（p<0.001）；SRM p=0.64，平衡性检验通过。 — 证据: `experiment_report.json`; 等级: `report-ready`

## 局限

见各工件 limitations 字段；未列出的口径风险不应假定不存在。

## 工件索引

| path | bytes | sha256 |
|---|---|---|
| analysis_contract.json | 678 | 78b347305c3962a8 |
| claim_registry.json | 261 | 52e158ef9cffa4e5 |
| clean.csv | 382628 | 4d871c1584a4d2fe |
| cleaning_report.json | 9309 | e1380d4e4751516d |
| data_manifest.json | 587 | 7f14d712a3ee941c |
| experiment_report.json | 8679 | 77fe8b3eb87b6486 |
| feature_risk_report.json | 3753 | c445f05ba8506511 |
| features.csv | 382628 | 4d871c1584a4d2fe |
| features.json | 503 | b985516591a488e1 |
| gate_review.json | 1447 | 3f5a0271863a1752 |
| profile.json | 9326 | 85474ec07a091a27 |
| route_decision.json | 217 | 1de1ce12307e7092 |
