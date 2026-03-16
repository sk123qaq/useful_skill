---
name: web-search-pro
description: >
  使用高性能 Orchestrator 脚本进行网络搜索。支持多短语并发搜索、自动化权重筛选、以及使用 Lightpanda 批量读取网页 Markdown 内容。
metadata: {"clawdbot":{"emoji":"🔍","requires":{"bins":["python3","lightpanda"]}}}
---

# Web Search Pro (Optimized)

通过 `search_orchestrator.py` 脚本实现的一键式、高性能搜索工具。

## 前置条件

这个 skill 想要被其他人直接使用，至少需要满足以下条件：

1. 已安装 `python3`
2. 已安装 `lightpanda` 二进制，并满足以下任一条件：
   - `lightpanda` 已加入系统 `PATH`
   - 或显式设置 `LIGHTPANDA_PATH=/absolute/path/to/lightpanda`
3. 建议提供可访问的 SearXNG 实例：
   - 默认读取 `SEARXNG_URL`
   - 未设置时默认使用 `http://localhost:8080/search`
   - 如果 SearXNG 不可用，脚本会尝试使用 Bing 页面作为兜底搜索源

说明：
- `search_orchestrator.py` 仅依赖 Python 标准库，不需要额外 `pip install`
- 本仓库中的 `lightpanda/` 目录是 skill 说明，不包含 `lightpanda` 可执行文件本体

## 环境变量

```bash
# 如果 lightpanda 不在 PATH 中，必须设置
export LIGHTPANDA_PATH=/absolute/path/to/lightpanda

# 可选：指定你自己的 SearXNG 实例
export SEARXNG_URL=http://localhost:8080/search

# 可选：控制并发抓取数
export MAX_CONCURRENT_CRAWLS=10
```

## 快速自检

```bash
# 检查 lightpanda 是否可用
command -v lightpanda

# 如果通过环境变量指定，也可以直接检查
test -x "$LIGHTPANDA_PATH" && echo "lightpanda ok"

# 检查 SearXNG 是否可访问（可选但推荐）
curl "${SEARXNG_URL:-http://localhost:8080/search}?q=test&format=json"
```

## 核心能力
1. **并发搜索**：同时支持多个搜索短语。
2. **确定性筛选**：自动执行域名去重、关键词权重增强、时间窗口匹配。
3. **极速读取**：利用 `lightpanda` 并发生成网页的 Markdown 格式，无需 Agent 介入筛选细节。

## 任务分级标准 (建议)

| 级别 | 适用场景 | 建议配置 |
| :--- | :--- | :--- |
| **L1: 基础认知** | 定义、简单事实查询 | 1 个查询短语, limit: 5 |
| **L2: 分析对比** | 新闻动态、产品横评 | 2 个查询短语, limit: 10 |
| **L3: 深度研报** | 历史趋势、行业深度调查 | 3+ 个查询短语, limit: 15 |

## 调用指令

Agent 应构造一个包含搜索任务的 JSON 数组，并运行主控脚本。推荐先进入当前 skill 目录后再执行：

```bash
cd /path/to/web-search-pro

# L3 示例：调查碳酸锂价格走势
python3 search_orchestrator.py '[
  {"query": "碳酸锂 2021-2022 价格走势", "limit": 10},
  {"query": "碳酸锂 2023-2024 价格走势", "limit": 10},
  {"query": "碳酸锂 2025 至今价格数据分析", "limit": 10}
]'
```

也支持单个查询字符串：

```bash
cd /path/to/web-search-pro
python3 search_orchestrator.py "OpenAI GPT-5 release date"
```

如果 `lightpanda` 不在 PATH 中：

```bash
cd /path/to/web-search-pro
LIGHTPANDA_PATH=/absolute/path/to/lightpanda python3 search_orchestrator.py "中国 AI Agent 工具"
```

## 确定性筛选逻辑 (由脚本自动执行)
- **Domain Diversity**: 同一域名最多保留 2 个结果。
- **Keyword Boost**: 匹配行业词（价格、报告、走势等）权重 +30。
- **Time Window**: 标题包含查询中的年份（如 2021）权重 +50。
- **Auto-Crawl**: 筛选后的 Top N 自动交由 Lightpanda 爬取。

## 容错处理
- 单个链接失败或超时（15s）会自动跳过，不中断整体任务。
- 搜索源降级：优先使用 SearXNG API；若不可用，则尝试 Bing 页面兜底。
- 如果缺少 `lightpanda`，脚本会在启动时报出明确错误，而不是隐式依赖作者本机路径。
