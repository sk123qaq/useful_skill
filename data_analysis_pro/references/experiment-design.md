# 实验设计

## 当前定位

这份文档更适合作为 A/B 实验分析与汇报的设计指南。

`scripts/experiment_analysis.py` 负责两臂实验的 SRM、平衡性、效应、功效和多重检验；它不替代实验设计。结果写入 `experiment_report.json`，再由 gate 判定证据等级。

不要用观察数据冒充随机实验；没有分流机制就回到因果分支。

## 实验开始前至少定义清楚

- 主要指标
- 护栏指标
- 随机化单位
- 曝光规则
- 观测窗口
- 停止准则

如果这些定义不清楚，后面的显著性、提升度、功效分析都可能只是形式正确。

## 分析期间建议检查

- SRM（样本比例偏差）
- 实验组与对照组的平衡性
- 绝对提升度与相对提升度
- 统计显著性与效应量
- 业务显著性，而不只是 p 值

## 当前脚本已实现范围

`experiment_analysis.py` 当前已实现：

- 双臂实验（非 0/1 组别也支持，需显式 `control`/`treatment`）
- 二值指标（比例 z 检验）与连续指标（Welch t 检验）
- SRM 卡方检验
- 协变量平衡性（二值/连续/类别）
- `bonferroni`、`holm`、`fdr_bh` 多重检验修正
- `bonferroni`、`pocock`、`obrien_fleming` 序列监测
- 二值/连续指标的功效与样本量估算
- 主/护栏指标决策汇总

报告顶层字段：`srm_p_value`、`balance_passed`、`balance_test`、`primary_metric`、`effect`、`p_value`、`decision`。平衡性用 Bonferroni 阈值 `alpha/协变量数`；单个协变量 `p<alpha` 记 `marginal`，不单独阻断。

已用公开数据 `causaldata.black_politicians` 实跑（5593 行，见 `references/worked-examples.md`）。

## 配置示例的正确用法

你可以把类似下面的 JSON 视为“分析配置草案”，用于表达实验口径，而不是默认可直接交给某个稳定 runner：

```json
{
  "group_col": "variant",
  "control": "control",
  "treatment": "treatment",
  "expected_allocation": {
    "control": 0.5,
    "treatment": 0.5
  },
  "metrics": [
    {
      "name": "converted",
      "type": "binary",
      "role": "primary",
      "success_value": 1,
      "preferred_direction": "increase",
      "practical_significance": 0.02
    },
    {
      "name": "revenue",
      "type": "continuous",
      "role": "secondary",
      "preferred_direction": "increase",
      "cuped_covariate": "pre_revenue"
    },
    {
      "name": "refund",
      "type": "binary",
      "role": "guardrail",
      "success_value": 1,
      "preferred_direction": "decrease"
    }
  ],
  "covariates": ["pre_sessions", "device"],
  "multiple_testing": {
    "method": "holm",
    "metric_names": ["converted", "revenue", "refund"]
  },
  "sequential_monitoring": {
    "method": "obrien_fleming",
    "current_look": 3,
    "total_looks": 5,
    "metric_names": ["converted", "revenue"]
  },
  "power_analysis": {
    "power": 0.8,
    "metric_names": ["converted", "revenue"],
    "mde": {"converted": 0.03, "revenue": 10}
  },
  "alpha": 0.05
}
```

## 当前更稳妥的使用方式

如果你要做实验分析，推荐顺序是：

1. 先用这份文档明确实验口径
2. 再确认 `experiment_analysis.py` 在当前环境和当前数据上确实能跑通
3. 若脚本不能运行，就按同样口径写最小分析代码，而不是假装已有稳定 pipeline

## 常见误区

- 未经修正地反复偷看结果并提前停止
- 混淆曝光单位和分析单位
- 实验组污染
- 使用干预后变量做控制
- 把噪声很大的细分切片写成确定结论

## 防护准则

- 先把实验定义写清楚，再谈统计工具。
- 不要因为 reference 里有方法名，就默认脚本一定可跑。
- 如果本次分析是额外手写代码完成的，要在交付里明确说明。
- 当前已知最小验证路径：`brfss_2024_obesity_modeling_sample.csv` 过滤 `exercise_past_30d in {yes,no}` 后，可成功跑通一条单指标实验分析链。
