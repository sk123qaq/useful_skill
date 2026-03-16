# 外部研究规则

## 何时启用外部研究

当本地数据不足，而你又需要下面这些补充信息时，再启用外部研究：

- 指标定义
- 行业基准值
- 行业背景或监管背景
- 会影响解读的近期事件
- 来源交叉验证

默认入口是 `scripts/source_research_adapter.py`。  
`web-search-pro` 只作为可选协同 skill 存在，不是 `data_analysis` 的硬依赖实现。

## 必须收集的结构化字段

外部研究结果至少要包含：

- `source_name`
- `metric_name`
- `definition`
- `unit`
- `geography`
- `time_period`
- `published_at`
- `confidence`
- `url`

## 来源质量优先级

优先顺序如下：

1. 官方机构或监管口径
2. 公司 IR、交易所公告、正式披露
3. 研究论文、白皮书、行业报告
4. 有公信力的媒体
5. 社区、论坛、博客

## 适配器工作流

优先使用 `scripts/source_research_adapter.py`，它有三种模式：

1. 规划模式

```bash
python3 scripts/source_research_adapter.py --query "中国 SaaS ARPU benchmark 2025" --metric-name "ARPU" --geography "China" --time-period "2025"
```

这会返回一份结构化研究请求包，既可以直接给人看，也可以交给其他搜索 skill 协同执行。

2. 闭环执行模式

```bash
python3 scripts/source_research_adapter.py \
  --query "中国 SaaS ARPU benchmark 2025" \
  --metric-name "ARPU" \
  --geography "China" \
  --time-period "2025" \
  --execute \
  --output-dir outputs/research-run
```

执行行为说明：

- 会并行尝试 `Bing`、`Google`
- `Bing` 和 `Google` 会按顺序尝试这些后端：
  1. `agent-browser`
  2. `Chrome --headless --dump-dom`
  3. 直接抓取 HTML 搜索结果页
- 如果沙箱阻断了 Unix socket，`agent-browser` 会被快速跳过，然后自动切到下一个后端
- 选中的页面会并行抓取，减少端到端等待时间

3. 标准化模式

```bash
python3 scripts/source_research_adapter.py --input-json raw_sources.json
```

这会完成去重、来源分层、置信度推断，以及冲突字段标记。

## 与 `web-search-pro` 的关系

- `data_analysis` 的主流程不依赖 `web-search-pro` 才能运行
- `source_research_adapter.py` 自己就能完成规划、搜索、抓取和标准化
- 如果仓库里同时有 `web-search-pro`，可以把它当成额外协同能力
- 即使 `web-search-pro` 的内部实现继续变化，也不应该直接阻断 `data_analysis` 的主分析流程
