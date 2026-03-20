# 失败恢复

## 诚实的失败

当运行被阻断或不安全时：
- 保留已经成功产出的工件
- 明确说明哪里卡住了
- 说明哪些结论仍然成立，哪些结论不能成立
- 给出最小下一步建议

## 优先级

相比于一份虽精美但具有误导性的报告，优先选择诚实的 `not_usable`（不可用）结果。

## 当前 skill 的恢复方式

`data_analysis_pro` 当前不是 checkpoint / continuation 系统。不要假设存在：

- `--continue-after-scout`
- `--continue-after-baseline`
- `judgment_context_after_scout`
- `judgment_context_after_baseline`
- `data_processing_decision.json`
- `modeling_decision.json`

如果某个脚本失败，优先采用下面的降级方式：

1. 缩小问题范围
2. 改用更小的原子脚本
3. 用临时 Python 代码组合现有函数
4. 明确停在当前证据边界，不硬凑完整流程

## 失败时至少应保留的内容

建议至少保留：

- 用户要回答的问题
- 输入数据路径或数据来源
- 已成功运行的脚本及其输出路径
- 报错脚本和核心错误信息
- 还能安全说出的结论
- 建议下一步

## 常见降级路径

- `causal_analysis.py` 跑不通：先退回 `column_profile.py`、`eda_stats.py`、`relationship_screening.py`，把问题降级为描述性或诊断性分析。
- `experiment_analysis.py` 跑不通：先输出实验设计缺口、样本分布和原始指标摘要，不直接给显著性结论。
- 基线建模条件不足：不要强行上模型，先做字段清洗、目标定义复核和 leakage 排查。
