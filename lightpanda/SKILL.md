---
name: lightpanda
description: 使用 Lightpanda 轻量级无头浏览器进行网页抓取、启动 CDP 服务器或 MCP 服务。当需要抓取网页内容（HTML/Markdown/语义树）、启动 headless browser CDP 服务器供其他工具连接、或作为 MCP 服务器与 AI 助手集成时使用此 skill。
---

# Lightpanda Skill

轻量级无头浏览器工具，用于网页抓取、CDP 服务器和 MCP 服务。

## 前置条件

本 skill 目录只包含说明文档，不包含 `lightpanda` 可执行文件本体。其他人想直接使用时，需要先完成以下任一方式：

1. 安装 `lightpanda` 并加入系统 `PATH`
2. 或在命令中显式写出二进制绝对路径

快速自检：

```bash
command -v lightpanda
lightpanda --help
```

## 工具简介

Lightpanda 是一个用 Zig 编写的高性能无头浏览器，具有以下特点：
- 极低的内存占用
- 支持 JavaScript 执行
- 支持 CDP (Chrome DevTools Protocol)
- 支持 MCP (Model Context Protocol)

## 使用场景

- 抓取网页内容（HTML/Markdown/语义树）
- 启动 CDP 服务器供其他工具连接
- 作为 MCP 服务器与 AI 助手集成

## 命令详解

### fetch - 抓取网页

抓取指定 URL 的内容，支持多种输出格式。

**基本用法：**
```bash
lightpanda fetch https://example.com
```

**常用选项：**

| 选项 | 说明 | 示例 |
|------|------|------|
| `--dump` | 输出格式：`html`/`markdown`/`semantic_tree`/`semantic_tree_text` | `--dump markdown` |
| `--strip_mode` | 移除指定标签组：`js`/`css`/`ui`/`full` | `--strip_mode js,css` |
| `--with_base` | 添加 `<base>` 标签 | `--with_base` |
| `--with_frames` | 包含 iframe 内容 | `--with_frames` |
| `--obey_robots` | 遵守 robots.txt | `--obey_robots` |
| `--http_proxy` | 设置 HTTP 代理 | `--http_proxy http://proxy:8080` |
| `--log_level` | 日志级别：debug/info/warn/error/fatal | `--log_level info` |

**示例：**
```bash
# 抓取并输出 Markdown
lightpanda fetch --dump markdown https://lightpanda.io/

# 抓取并清理 JS 和 CSS
lightpanda fetch --dump html --strip_mode js,css https://example.com

# 抓取语义树（适合 AI 处理）
lightpanda fetch --dump semantic_tree_text https://example.com
```

### serve - 启动 CDP 服务器

启动 WebSocket CDP 服务器，供其他工具（如 Puppeteer、Playwright）连接。

**基本用法：**
```bash
lightpanda serve
```

**常用选项：**

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--host` | 服务器主机 | `127.0.0.1` |
| `--port` | 服务器端口 | `9222` |
| `--timeout` | 空闲超时时间（秒） | `10` |
| `--cdp_max_connections` | 最大并发连接数 | `16` |
| `--cdp_max_pending_connections` | 等待队列大小 | `128` |

**示例：**
```bash
# 在 9222 端口启动 CDP 服务器
lightpanda serve --host 127.0.0.1 --port 9222

# 增加超时时间和连接数
lightpanda serve --timeout 60 --cdp_max_connections 32
```

### mcp - 启动 MCP 服务器

启动 MCP (Model Context Protocol) 服务器，通过 stdio 与 AI 助手通信。

**基本用法：**
```bash
lightpanda mcp
```

**说明：**
- MCP 服务器通过标准输入输出与客户端通信
- 适用于与 Claude Desktop、OpenClaw 等支持 MCP 的工具集成
- 支持所有 HTTP 相关的配置选项

## HTTP 配置选项（全局）

以下选项适用于所有命令：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--http_max_concurrent` | 最大并发 HTTP 请求数 | `10` |
| `--http_max_host_open` | 单主机最大连接数 | `4` |
| `--http_connect_timeout` | 连接超时（毫秒） | `0`（无限制） |
| `--http_timeout` | 请求超时（毫秒） | `10000` |
| `--http_max_response_size` | 最大响应大小 | 无限制 |
| `--insecure_disable_tls_host_verification` | 禁用 TLS 主机验证 | - |

## 输出格式说明

### html
原始 HTML 内容，可选择清理指定标签。

### markdown
转换为 Markdown 格式，便于阅读和后续处理。

### semantic_tree
语义树结构，保留页面的语义信息（标题、段落、列表等）。

### semantic_tree_text
纯文本形式的语义树，适合直接输入给 LLM。

## 最佳实践

1. **抓取文章页面**：使用 `--dump markdown --strip_mode js,css,ui` 获得干净的 Markdown
2. **批量抓取**：配合 `--http_max_concurrent` 控制并发
3. **尊重网站**：使用 `--obey_robots` 遵守 robots.txt
4. **调试问题**：使用 `--log_level debug` 查看详细日志

## 注意事项

- Lightpanda 是单二进制文件，无需额外依赖
- 本仓库中的 `lightpanda/` 目录不是二进制安装包
- 默认不遵守 robots.txt，如需遵守请显式添加 `--obey_robots`
- CDP 服务器默认 10 秒超时，长时间任务请调整 `--timeout`
