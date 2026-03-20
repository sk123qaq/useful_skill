# 模型选择

## 当前适用范围

本文件描述的是 `data_analysis_pro` 当前内建的表格预测基线能力，主要对应 `baseline_runner.py` 和 `model_catalog.py`。

它不是通用机器学习百科，也不是时间序列、深度学习或自动调参平台的说明书。

## 先问是不是一定要上模型

在当前 skill 中，预测建模不是默认第一步。

推荐顺序仍然是：

1. 先做 `column_profile.py`
2. 再做 `eda_stats.py`
3. 再做 `relationship_screening.py`
4. 只有当问题真的是“要预测某个目标”时，再进入基线建模

如果用户的问题本质上是：

- 描述当前情况
- 看字段关系
- 解释某个变化
- 评估实验效果

那就不要因为“有数据”而强行上模型。

## 当前内建的基线模型

### 分类

当前基线目录来自 `model_catalog.py`：

- `dummy_most_frequent`
- `logistic_regression`
- `random_forest_classifier`

### 回归

当前基线目录来自 `model_catalog.py`：

- `dummy_mean`
- `dummy_median`
- `linear_regression`
- `random_forest_regressor`

### 可选扩展候选

代码里还提供了一个较轻量的 tuning catalog，但它不是强制流程，也不是独立 CLI：

- 分类：若干 `decision_tree`、`balanced logistic regression`、`balanced random forest`
- 回归：`ridge`、更深的 `random_forest_regressor`

## 如何调用

`baseline_runner.py` 当前更适合作为 Python 助手调用，而不是终端里直接执行。

```python
import pandas as pd
from data_analysis_pro.scripts.baseline_runner import run_baseline_ladder

df = pd.read_csv("data.csv")
report = run_baseline_ladder(df, target="label", task="classification")
```

如果需要把结果保存成工件，可传 `output_dir`，脚本会写出 `baseline_results.json`。

## 当前默认验证方式

当前实现默认使用交叉验证：

- 分类：`StratifiedKFold`
- 回归：`KFold`

默认折数是 `5`，但实际折数会自动受样本量和最小类别样本数限制。

如果传入 `weight_col`，当前实现会改用 weight-aware 的折分策略。

## 当前默认主指标

- 分类默认主指标：`accuracy`
- 回归默认主指标：`rmse`

除此之外，分类结果通常还会包含：

- `balanced_accuracy`
- `f1_macro`
- `precision_pos`
- `recall_pos`
- 对二分类且模型能给分数时，还可能包含：
  - `roc_auc`
  - `average_precision`
  - `brier_loss`

回归结果通常还会包含：

- `mae`
- `r2`

## 何时不要依赖当前基线助手

下面这些情形当前不应直接依赖本文件描述的建模路径：

- 时间序列预测
- 需要滚动窗口或严格时间切分的问题
- 需要概率校准或阈值优化才能交付的场景
- 需要大规模自动调参的场景
- 目标定义本身还不稳定的场景

特别说明：

- `run_model_ladder(..., time_col=...)` 当前不会真的启用时间序列验证；`time_col` 在实现里没有进入建模逻辑。
- 因此，不要把本 skill 当前的基线能力包装成时间序列建模能力。

## 选择原则

- 先让 dummy baseline 出来，确认问题是否值得建模。
- 先让线性模型出结果，确认是否存在简单且稳定的信号。
- 只有当前两步都完成后，再看树模型是否真的带来明显改善。
- 如果字段很多、ID 字段很多、缺失严重、业务口径不稳，先回到清洗和字段收缩，而不是继续堆模型。

## 防护准则

- 不要把高维 one-hot 后的内部特征空间误当作“模型已经准备好”。
- 不要把随机切分结果偷换成对未来时间的预测能力。
- 不要因为 random forest 分数更高，就默认它比 logistic regression 更适合业务解释。
- 如果模型只是勉强优于 dummy，不要把它写成可上线能力。
