# 关系筛查与描述性线索

## 适用范围

当问题属于描述性或诊断性分析，且你已经有一个明确的 `target`，希望快速找出“哪些字段最值得继续看”时，使用 `scripts/relationship_screening.py`。

当前 `data_analysis_pro` 并没有内建 `scripts/analysis_methods.py`。不要把本文件理解为“聚类 / Apriori / ANOVA / 根因分解”的现成实现清单。

## 当前内建能力

`relationship_screening.py` 会根据目标变量和候选变量的类型，自动选择一个轻量级的关系强度指标，并按 effect size 排序。

当前脚本实际覆盖的关系筛查包括：

- 类别 vs 类别：`Cramer's V`
- 类别 vs 数值：`eta squared`
- 数值 vs 数值：`abs(Spearman r)`

目标变量的类型也会被自动识别：

- 二值目标：`binary`
- 少量类别目标：`categorical`
- 连续目标：`numeric`

## CLI

```bash
python3 data_analysis_pro/scripts/relationship_screening.py \
  --input-path data.csv \
  --target label \
  --top-k 20
```

参数很少：

- `--input-path`：输入数据路径
- `--target`：目标列
- `--top-k`：返回前若干个候选关系，默认 `20`

## 如何使用结果

这个脚本适合做“第一轮筛查”，不适合单独作为最终结论。

推荐用法：

1. 先跑 `column_profile.py` 看字段质量和潜在 ID 字段。
2. 再跑 `relationship_screening.py` 找出前几位候选特征。
3. 对排名靠前的字段，继续用 `eda_stats.py`、交叉表、分组统计或图表做人工复核。

## 当前未内建的能力

下面这些主题在当前 skill 中没有稳定的现成脚本，不要误认为已经内建：

- 聚类
- Apriori / 购物篮分析
- 单因素 ANOVA 工作流
- KPI 根因分解 / contribution decomposition

如果任务确实需要这些方法，应由 Agent 结合现有脚本和临时 Python 代码自行处理，而不是假设本 skill 已经封装好。

## 防护准则

- 高基数字段、主键、订单号、用户 ID 可能会得到虚高的关系分数，先结合 `column_profile.py` 判断它是不是标识符或泄露字段。
- 关系强度只用于筛查，不等于业务重要性，更不等于因果关系。
- 对小样本或严重不平衡数据，effect size 排名很容易不稳定，结论必须复核。
- 如果字段经过 one-hot 或复杂编码，优先回到原始业务字段层面解释，而不是直接把编码列当业务发现。
