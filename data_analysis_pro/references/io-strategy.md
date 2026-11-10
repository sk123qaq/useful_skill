# IO Strategy

## 目录

目录输入不是“自动选文件”。`io_router.py manifest` 返回：

- `kind: directory`
- `candidates`: 文件路径、大小、扩展名、可读性
- 每个候选的列名/Sheet（Excel 只列 Sheet；列名要显式 `--sheet` 后才读）

Agent 必须显式选择：

```bash
python scripts/io_router.py manifest --input-path data/ --output-path run/data_manifest.json
python scripts/io_router.py load --input-path data/imports.csv --sheet "明细" --comment "#" --sample-rows 5
```

不要用“最大的文件”当默认。一个 32KB 的编码对照表可能比 5MB 的主数据更“大”。

## Excel

- 默认只读第一个 Sheet 是**错误默认**。
- 先 `manifest` 看 Sheet 列表，再显式 `--sheet`。
- 表头不在第一行时用 `--skiprows`；不要靠猜。
- 合并单元格/多级表头：先导出成规整表，或在清洗脚本里明确处理；不要在加载器里隐式 flatten。

## CSV

- 有些海关/业务导出在开头带 `#` 注释。用 `--comment "#"`，不要手工删行后再分析。
- 编码：默认 UTF-8；GBK/GB18030 用 `--encoding`。
- 分隔符异常：先看前 5 行原始文本，确认是逗号、制表符还是分号；不要用 `sep=None` 猜。
- 千分位/百分号/货币符号：在 `clean.py` 的配置里声明，不要静默 `astype(float)`。

## 采样

- `--sample-rows` 只用于看结构，不用于最终统计。
- `data_scope: sample` 时，报告中必须写“样本”，不能写“全量”。
- 分层/时间采样要在 contract 里写清；不要用随机头尾样本代替时间切分。

## 失败时

加载失败就报告原始错误和文件路径。不要：

- 换一个“看起来差不多”的文件继续；
- 把失败行静默 `dropna()`；
- 把注释行当数据行；
- 把编码错误当缺失值。
