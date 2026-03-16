---
name: mineru-api
description: MinerU Cloud API for PDF/document parsing. Supports PDF/DOC/PPT/image/HTML to Markdown/JSON/HTML extraction with OCR, formula recognition, table extraction. Use when parsing documents via MinerU cloud API, batch processing files, or extracting structured content with layout preservation.
---

# MinerU Cloud API

MinerU 云端 API 文档解析服务，支持 PDF、DOC、PPT、图片、HTML 等多种格式转换为 Markdown、JSON、HTML。

## 快速开始

### 1. 环境配置

其他人使用时，不应假设仓库内已经包含可用的 Token。请自行准备 MinerU Token，并通过以下任一方式提供：

- 设置环境变量 `MINERU_API_TOKEN`
- 或在运行脚本时使用 `--token`
- 或在本地私有 `.env` 文件中配置

推荐先安装依赖：

```bash
cd /path/to/mineru-api
python3 -m pip install -r requirements.txt
```

如需使用本地 `.env` 文件，可写成：

```env
MINERU_API_TOKEN=your_token_here
```

### 2. 快速解析本地文件（推荐）

使用 `parse_local.py` 脚本快速解析本地文件：

```bash
cd /path/to/mineru-api

# 解析整个文件
python3 scripts/parse_local.py /path/to/document.pdf

# 解析指定页码范围
python3 scripts/parse_local.py /path/to/document.pdf --pages "5-6"

# 启用表格和公式识别（默认已启用）
python3 scripts/parse_local.py /path/to/document.pdf --pages "1-10" --table --formula

# 保存结果到文件
python3 scripts/parse_local.py /path/to/document.pdf --output result.md
```

### 3. Python API 调用

```python
from scripts.mineru_client import MinerUClient
from scripts.parse_local import parse_local_file

# 快速解析本地文件并获取 Markdown 内容
content = parse_local_file(
    file_path="/path/to/document.pdf",
    page_ranges="5-6",
    enable_table=True,
    enable_formula=True
)
print(content)
```

---

## 完整文档

### 设置 API Token

```bash
export MINERU_API_TOKEN='your_api_token_here'
```

Token 从 [MinerU 官网](https://mineru.net) 申请。

### 解析单个 URL 文件

```python
from scripts.mineru_client import MinerUClient
import os

client = MinerUClient(api_token=os.environ.get("MINERU_API_TOKEN"))

# URL 方式解析
result = client.parse_url(
    file_url="https://example.com/document.pdf",
    output_formats=["markdown", "json"],
    enable_table=True,
    enable_formula=True
)
print(f"Task ID: {result['task_id']}")

# 查询结果
task_result = client.get_task_result(result['task_id'])
if task_result['state'] == 'done':
    print(f"Download URL: {task_result['full_zip_url']}")
```

### 批量解析本地文件

```python
# 批量上传并解析
files = [
    {"name": "doc1.pdf", "data_id": "batch_001"},
    {"name": "doc2.pdf", "data_id": "batch_002"}
]

batch_result = client.batch_upload_parse(
    files=files,
    file_paths=["/path/to/doc1.pdf", "/path/to/doc2.pdf"],
    output_formats=["markdown"]
)

# 查询批量结果
batch_status = client.get_batch_result(batch_result['batch_id'])
```

## API 概述

### 限制说明

| 限制项 | 说明 |
|--------|------|
| 单文件大小 | 最大 200MB |
| 文件页数 | 不超过 600 页 |
| 每日额度 | 2000 页高优先级，超出后优先级降低 |
| URL 限制 | GitHub、AWS 等国外 URL 可能超时 |
| 批量数量 | 单次最多 200 个文件 |

## 可直接使用前的自检

```bash
cd /path/to/mineru-api
python3 -m pip install -r requirements.txt
python3 scripts/parse_local.py --help
python3 scripts/parse_single.py --help
python3 scripts/parse_batch.py --help
```

注意：
- 本仓库中的 `.env` 仅应作为本地私有配置，不应依赖它对其他人可见
- 如果未设置 `MINERU_API_TOKEN`，脚本会直接报错并提示如何传入 Token

### 支持的文件格式

- PDF (`.pdf`)
- Word (`.doc`, `.docx`)
- PowerPoint (`.ppt`, `.pptx`)
- 图片 (`.png`, `.jpg`, `.jpeg`)
- HTML (`.html`) - 需指定 `MinerU-HTML` 模型

### 输出格式

默认输出：Markdown + JSON
可选额外格式：`docx`, `html`, `latex`

## Usage Patterns

### 单文件 URL 解析

```python
# 基础用法
result = client.parse_url("https://example.com/file.pdf")

# 完整参数
result = client.parse_url(
    file_url="https://example.com/file.pdf",
    model_version="vlm",           # pipeline, vlm, MinerU-HTML
    is_ocr=False,                   # 启用 OCR
    enable_formula=True,            # 公式识别
    enable_table=True,              # 表格识别
    language="ch",                  # 文档语言
    output_formats=["docx"],        # 额外输出格式
    page_ranges="1-10,15,20-25",    # 指定页码范围
    data_id="custom_id_001",        # 业务数据 ID
    callback="https://your.callback.url",
    seed="random_seed_for_verify"
)
```

### 批量 URL 解析

```python
files = [
    {"url": "https://example.com/doc1.pdf", "data_id": "id1", "is_ocr": True},
    {"url": "https://example.com/doc2.pdf", "data_id": "id2", "page_ranges": "1-5"}
]

batch = client.batch_url_parse(files=files, model_version="vlm")
```

### 本地文件批量解析

```python
# 准备文件列表
files = [
    {"name": "report.pdf", "data_id": "report_2024", "is_ocr": True},
    {"name": "slides.pptx", "data_id": "presentation_q1"}
]
file_paths = ["/path/to/report.pdf", "/path/to/slides.pptx"]

# 上传并自动解析
result = client.batch_upload_parse(
    files=files,
    file_paths=file_paths,
    model_version="vlm",
    enable_table=True
)

# 轮询等待结果
import time
while True:
    status = client.get_batch_result(result['batch_id'])
    all_done = all(r['state'] == 'done' for r in status['extract_result'])
    if all_done:
        break
    time.sleep(5)
```

### 任务结果查询与下载

```python
# 查询单个任务
task = client.get_task_result("task_id_here")

# 状态: done, pending, running, failed, converting, waiting-file
if task['state'] == 'done':
    # 下载结果压缩包
    client.download_result(task['full_zip_url'], "./output.zip")
elif task['state'] == 'failed':
    print(f"Error: {task['err_msg']}")
elif task['state'] == 'running':
    progress = task['extract_progress']
    print(f"Progress: {progress['extracted_pages']}/{progress['total_pages']}")
```

## Model Versions

| 版本 | 适用场景 | 说明 |
|------|----------|------|
| `pipeline` | 常规文档 | 默认选项，速度较快 |
| `vlm` | 复杂版式 | 效果更好，支持公式/表格 |
| `MinerU-HTML` | HTML 文件 | 解析 HTML 必须指定 |

**推荐**: 一般文档用 `vlm` 获得最佳效果。

## Page Ranges 格式

```python
# 第 2 页
page_ranges="2"

# 第 2 页到第 6 页
page_ranges="2-6"

# 第 2 页、第 4-6 页
page_ranges="2,4-6"

# 第 2 页到倒数第 2 页
page_ranges="2--2"
```

## Error Handling

### 常见错误码

| 错误码 | 说明 | 解决方案 |
|--------|------|----------|
| A0202 | Token 错误 | 检查 Token 格式，确保有 Bearer 前缀 |
| A0211 | Token 过期 | 更换新 Token |
| -500 | 传参错误 | 检查参数类型和 Content-Type |
| -60002 | 文件格式不支持 | 确保文件名有正确后缀 |
| -60005 | 文件大小超限 | 文件需小于 200MB |
| -60006 | 页数超限 | 拆分文件，单文件不超过 600 页 |
| -60008 | 文件读取超时 | 检查 URL 是否可访问 |
| -60018 | 每日任务数达上限 | 次日再试 |

### 回调验证

使用 callback 时，验证请求来自 MinerU:

```python
import hashlib

def verify_callback(checksum: str, uid: str, seed: str, content: str) -> bool:
    expected = hashlib.sha256(f"{uid}{seed}{content}".encode()).hexdigest()
    return checksum == expected
```

## Scripts

| 脚本 | 用途 |
|------|------|
| `scripts/mineru_client.py` | Python API 客户端 |
| `scripts/parse_single.py` | 命令行单文件解析 |
| `scripts/parse_batch.py` | 命令行批量解析 |

### 命令行使用

```bash
# 单文件解析
python3 scripts/parse_single.py --url https://example.com/doc.pdf --formats markdown json --table --formula

# 批量解析
python3 scripts/parse_batch.py file1.pdf file2.pdf --output ./results
```

## References

- **完整 API 文档**: 参见 [references/api_docs.md](references/api_docs.md)
- **输出文件说明**: https://opendatalab.github.io/MinerU/reference/output_files/
- **语言支持列表**: https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
