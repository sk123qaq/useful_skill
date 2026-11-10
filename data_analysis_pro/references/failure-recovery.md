# Failure Recovery

## 原则

失败要暴露，不要被“清洗”掉。脚本报错、数据不足、假设不成立，都是结果的一部分。

## 常见失败

| 现象 | 原因 | 动作 |
|---|---|---|
| 目录加载选错文件 | 旧版自动选最大文件 | 用 `io_router.py manifest` 列候选，显式 `--input-path` 选文件 |
| `ParserError: Expected 1 fields` | CSV 开头有 `#` 注释 | 加 `--comment "#"`，不要手工删行 |
| Excel 读到的是口径表 | 只读第一个 Sheet | `manifest` 看 Sheet，显式 `--sheet` |
| `SimpleImputer does not support datetime64` | 时间列被当特征 | 切分用 `time_col`，特征里排除时间键 |
| `Input y contains NaN` | target 末行缺失 | `clean.py` 处理或在 baseline 前显式 drop，并记录 |
| 时间序列 CV 异常好 | 随机 KFold 泄漏 | 用 `split_plan.py create --strategy temporal` |
| gate 空输入 report-ready | 旧版占位 gate | 用新版 `gate_evaluator.py`；空目录应 not_usable |
| 报告没有 baseline/EDA | 旧 `report_export.py` 固定扫描 | 用 `report_bundle.py` + `report_lint.py` |
| 因果估计不显著 | 效应小/样本小/识别弱 | 报告置信区间和假设；不要换模型直到显著 |

## 降级路径

1. **预测 → 描述**：target 泄漏不可修复、样本太短、baseline 不赢 dummy。
2. **因果 → 描述/停止**：无对照、无重叠、平行趋势不成立、工具变量不满足排除性。
3. **实验 → 停止**：SRM 失败、分流比例异常、样本量不足。
4. **任何分支 → stop_and_report**：关键字段缺失、口径无法确认、数据质量不过。

降级要写进 `gate_review.json` 和最终答复，不要静默换问题。

## 不能做

- 为了跑通而删掉失败行/失败列，且不记录。
- 把 `not_usable` 改成 `report-ready`。
- 用另一个脚本的输出冒充失败脚本的结果。
- 在报告里写“已检验”但实际没跑。
