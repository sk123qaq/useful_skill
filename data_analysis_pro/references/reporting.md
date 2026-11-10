# Reporting

## 原则

报告不是分析过程的流水账，也不是模型输出的翻译。报告只回答：

1. 决策问题是什么。
2. 数据能支持到什么程度。
3. 结论是什么，证据在哪里。
4. 哪些事不能从这份数据得出。

## Claim Registry

每条结论一个 claim：

```json
{
  "claims": [
    {
      "claim_id": "C1",
      "text": "2026年1-8月锂辉石进口占进口LCE的74.2%。",
      "evidence_grade": "report-ready",
      "supported_by": ["describe.json", "lce_import_matrix.csv"]
    }
  ]
}
```

规则：

- `claim_id` 唯一，报告里必须出现 `[C1]`。
- `supported_by` 必须是真实存在的工件路径（相对 run_dir）。
- `evidence_grade` 不能高于 `gate_review.json.max_evidence_grade`。
- 一条 claim 只表达一个结论；不要把“相关 + 因果 + 建议”塞进一条。
- 没有证据的“洞察”不是 claim，是假设；写在局限/下一步。

## 报告结构

`report_bundle.py` 生成：

1. 标题与契约摘要（任务、单元、数据范围、target/time）。
2. 决策问题。
3. 数据与口径（行数、清洗、缺失、样本限制）。
4. 方法（路由、切分、模型/因果设计）。
5. 结果（描述/基线/因果/实验）。
6. 结论（只来自 claim_registry）。
7. 局限。
8. 工件索引（路径、大小、sha256）。

Agent 可以在 `report.md` 基础上补充业务解释，但不能新增没有 claim 的数字结论。

## 证据等级措辞

| 等级 | 可以写 | 不可以写 |
|---|---|---|
| `report-ready` | “结果表明”“在本数据/窗口内” | “必然”“证明” |
| `exploratory` | “初步提示”“与……一致”“值得进一步验证” | “显著证明”“可用于决策” |
| `not_usable` | “当前数据不足以判断” | 任何方向性结论 |

## 报告 lint

`report_lint.py` 检查：

- 必需章节是否存在。
- 每条 claim 是否在报告中出现。
- `supported_by` 是否存在。
- claim 等级是否越级。
- gate 不是 report-ready 时，报告是否仍写“report-ready”。
- 报告中的路径引用是否存在（warning）。

未通过 lint 的报告不得交付。

## 交付答复

最终答复建议 4 段：

1. **结论**：3–6 条，带 claim id。
2. **证据**：每条指向文件/图/表。
3. **局限**：样本、口径、未做的检验。
4. **下一步**：缺什么数据、补什么设计。

不要把 `report.md` 全文粘进聊天；给路径和摘要。
