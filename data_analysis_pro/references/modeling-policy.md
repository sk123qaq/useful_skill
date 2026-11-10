# Modeling Policy

## 切分

| 数据结构 | 允许策略 | 禁止 |
|---|---|---|
| 有时间列，预测未来 | `temporal` / `expanding` / `rolling` | 随机 `kfold` |
| 无时间列，独立样本 | `kfold` | 按 target 排序后切 |
| 同组样本（会员/门店/患者） | `group` | 同组跨 train/test |
| 面板/多层 | 时间 + group 组合；先聚合或明确层级 | 把同一实体多行随机分到两边 |

`split_plan.py` 的 `validate` 会检查：

- 索引越界/重叠；
- 测试折之间重叠；
- 时间策略下训练集时间 < 测试集时间。

失败就修 plan，不要绕过。

## 基线

预测分支的最低要求：

1. `dummy`（分类 most_frequent / 回归 mean）。
2. 至少一个非 dummy：`linear_regression`/`logistic_regression`/`random_forest_*`。
3. 同一 split、同一预处理、同一指标。

通过线：

- 分类：最佳非 dummy 比 dummy 高 ≥0.02（accuracy/F1 等）。
- 回归：RMSE/MAE 相对 dummy 下降 ≥5%。
- 稳定性：各折指标 std/mean ≤0.2。

不满足 → `exploratory`，不是“模型效果不错”。

## 指标

- 分类不平衡：不要只看 accuracy；看 F1/recall/AUC，并写清阈值。
- 回归：RMSE/MAE 带单位；R² 只在同目标同切分下比较。
- 排序：NDCG/MAP 需要明确的 relevance 定义。
- 任何指标都要写“越高越好/越低越好”，避免方向误读。

## 解释

- 特征重要性不是因果效应。
- 同期价格/同一行字段的高重要性，先怀疑泄漏。
- SHAP/PDP 只在模型和数据版本固定时解释；不要跨模型混用。
- 不要用“模型认为”替代业务机制；机制需要因果设计或外部证据。

## 何时停止加模型

- 非 dummy 已经赢 dummy，但提升 < 业务可感知阈值。
- 增加模型复杂度没有带来稳定性提升。
- 交叉验证方差大于均值改善。
- 解释成本超过决策价值。

停止时写“基线已足够/不够”，不要堆模型列表。
