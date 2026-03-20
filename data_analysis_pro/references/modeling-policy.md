# 建模策略

## 当前定位

本文件描述的是 `data_analysis_pro` 当前的轻量建模原则，主要服务于：

- `baseline_runner.py`
- `model_catalog.py`
- `gate_evaluator.py`

它不是调参平台、状态机，也不依赖额外的 decision JSON。

## 基准优先

对于预测性工作，默认顺序应是：

1. 先跑 dummy baseline
2. 再跑线性或广义线性基线
3. 最后再看树模型是否值得

当前第一阶段推荐阶梯：

### 分类
- `dummy_most_frequent`
- `logistic_regression`
- `random_forest_classifier`

### 回归
- `dummy_mean`
- `dummy_median`
- `linear_regression`
- `random_forest_regressor`

## 当前结果复核时使用的关键阈值

这些阈值不是通用真理，而是当前 `gate_evaluator.py` 的真实实现：

- 分类任务的 baseline gate：
  - 最优非 dummy 模型需要比最优 dummy 在主指标上至少高 `0.02`
- 回归任务的 baseline gate：
  - 最优非 dummy 模型需要让主指标至少优于 dummy `5%`
  - 当前实现等价于 `model_value <= dummy_value * 0.95`
- 分类任务的 stability gate：
  - 最优模型在主指标上的折间标准差应不高于 `0.08`
- 回归任务的 stability gate：
  - 最优模型在主指标上的折间标准差应不高于均值绝对值的 `20%`

如果你在报告里写“模型可用”，最好至少能解释清楚它有没有越过这些门槛。

## 实际建模时的轻量原则

- 如果字段明显像 ID、订单号、用户号，先剔除或单独审查，再进建模。
- 如果字段非常宽、编码后会爆炸，先收缩字段，不要直接把树模型当兜底方案。
- 如果目标列类别极不平衡，不要只盯 `accuracy`，至少一起看：
  - `balanced_accuracy`
  - `f1_macro`
  - 如果有概率分数，再看 `roc_auc`、`average_precision`
- 如果问题天然是频数表或聚合表，优先把计数字段作为 `weight_col`，不要把它当普通特征。

## 何时停止升级

下面这些情况出现时，优先停下来重审数据，而不是继续加模型复杂度：

- 最优非 dummy 只比 dummy 略好一点
- 折间波动很大
- 重要特征里混入明显后验字段或泄露字段
- 预测目标本身定义得不稳定
- 字段口径还在变化

## 关于“调参”

当前代码里虽然有更丰富的候选模型目录，但 `data_analysis_pro` 现在没有稳定的“受监控调参流程”。

因此：

- 不要把“继续试几个更复杂模型”包装成系统化调参能力。
- 如果确实要多试几个候选，应明确写这是手动扩展，而不是默认流程。
- 如果交付依赖概率质量或阈值选择，当前 skill 也没有稳定的 calibration / threshold review 管线，不要过度承诺。

## 防护准则

- 可解释性输出不能被翻译成因果建议。
- 随机森林更强，不等于更适合作为第一结论。
- 如果目标问题更适合实验、因果或描述性分析，就不要用建模替代问题定义。
