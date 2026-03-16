---
name: searxng
description: Search the web using a self-hosted SearXNG instance with bilingual (CN/EN) search support. Privacy-respecting metasearch that aggregates results from multiple engines.
metadata:
  clawdbot:
    config:
      optionalEnv:
        - SEARXNG_URL
---

## 前置要求

需要在本地或服务器上运行 SearXNG。快速 Docker 部署方法：

建议先确认本机具备这些命令：

```bash
docker --version
docker compose version
curl --version
jq --version
```

说明：
- 本仓库不自带可运行的 SearXNG 服务
- 下文中的 `http://localhost:8080` 是默认示例地址，实际可替换成你自己的实例
- 推荐统一通过环境变量 `SEARXNG_URL` 引用实例地址

```bash
mkdir -p ~/Projects/searxng/searxng
cd /path/to/searxng-deploy

# 创建 docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    ports:
      - "8080:8080"
    volumes:
      - ./searxng:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8080/
    restart: unless-stopped
EOF

# 创建启用 JSON API 的 settings.yml
cat > searxng/settings.yml << 'EOF'
use_default_settings: true
server:
  secret_key: "c90a229745fd6e49d6be1fe0b4d156cecfef1773f1bc13fb5c2892a4dc265580"
  bind_address: "0.0.0.0"
  port: 8080
search:
  safe_search: 1
  autocomplete: "google"
  default_lang: "zh-CN"
  formats:
    - html
    - json
EOF

# 启动 SearXNG
docker compose up -d
```

## 环境变量配置

```bash
# 临时设置（推荐先这样测试）
export SEARXNG_URL=http://localhost:8080

# 如需持久化，再写入你的 shell 配置文件
# zsh:
echo 'export SEARXNG_URL=http://localhost:8080' >> ~/.zshrc
source ~/.zshrc
```

## 核心功能：双语搜索（Bilingual Search）

**提示**：为了获得更全面的搜索结果，建议每次搜索时**同时进行中文和英文搜索**。中文搜索捕获本地化和中文资源，英文搜索获取国际前沿和英文资料。

### 快速开始 - 双语搜索函数

将以下函数添加到您的 `.zshrc` 或 `.bashrc`：

```bash
# 双语搜索函数：同时进行中文和英文搜索并合并结果
searxng_bilingual() {
  local query="$*"
  local url="${SEARXNG_URL:-http://localhost:8080}"
  
  echo "🔍 正在进行双语搜索: $query"
  echo "================================"
  
  # 中文搜索 (zh-CN)
  echo "\n🇨🇳 中文搜索结果 (Top 5):"
  local cn_results=$(curl -s "${url}/search?q=$(echo "$query" | sed 's/ /+/g')&language=zh-CN&format=json" | 
    jq -r '.results[:5] | to_entries | .[] | "\(.key+1). [\(.value.score | floor)] \(.value.title)\n   链接: \(.value.url)\n   摘要: \(.value.content // \"无描述\")\n"')
  
  if [ -z "$cn_results" ] || [ "$cn_results" == "null" ]; then
    echo "   暂无中文结果"
  else
    echo "$cn_results"
  fi
  
  # 英文搜索 (en)
  echo "\n🇺🇸 英文搜索结果 (Top 5):"
  local en_results=$(curl -s "${url}/search?q=$(echo "$query" | sed 's/ /+/g')&language=en&format=json" | 
    jq -r '.results[:5] | to_entries | .[] | "\(.key+1). [\(.value.score | floor)] \(.value.title)\n   Link: \(.value.url)\n   Summary: \(.value.content // \"No description\")\n"')
  
  if [ -z "$en_results" ] || [ "$en_results" == "null" ]; then
    echo "   No English results"
  else
    echo "$en_results"
  fi
  
  echo "\n================================"
  echo "✅ 双语搜索完成"
}

# 简化的单语言搜索（保留原功能）
searxng() {
  local query="$*"
  local url="${SEARXNG_URL:-http://localhost:8080}"
  local lang="${SEARXNG_LANG:-zh-CN}"
  
  curl -s "${url}/search?q=$(echo "$query" | sed 's/ /+/g')&language=${lang}&format=json" | \
    jq -r '.results[:10][] | "[\(.score | floor)] \(.title)\n    \(.url)\n    \(.content // \"无描述\")\n"'
}

# 仅中文搜索
searxng_cn() {
  local query="$*"
  local url="${SEARXNG_URL:-http://localhost:8080}"
  
  echo "🇨🇳 中文搜索: $query"
  curl -s "${url}/search?q=$(echo "$query" | sed 's/ /+/g')&language=zh-CN&format=json" | \
    jq -r '.results[:10][] | "[\(.score | floor)] \(.title)\n    \(.url)\n    \(.content // \"无描述\")\n"'
}

# 仅英文搜索
searxng_en() {
  local query="$*"
  local url="${SEARXNG_URL:-http://localhost:8080}"
  
  echo "🇺🇸 English Search: $query"
  curl -s "${url}/search?q=$(echo "$query" | sed 's/ /+/g')&language=en&format=json" | \
    jq -r '.results[:10][] | "[\(.score | floor)] \(.title)\n    \(.url)\n    \(.content // \"No description\")\n"'
}
```

### 使用示例

```bash
# 双语搜索（推荐）- 同时获取中文和英文结果
searxng_bilingual "Python 机器学习教程"
searxng_bilingual "OpenAI GPT-5 release date"

# 单语言搜索
searxng "人工智能最新进展"           # 使用默认语言（zh-CN）
searxng_cn "新能源汽车政策"          # 仅中文
searxng_en "stable diffusion tutorial"  # 仅英文
```

## API 使用指南

下面所有 `curl` 示例都可以优先替换成：

```bash
BASE_URL="${SEARXNG_URL:-http://localhost:8080}"
```

### 基础搜索参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `q` | 搜索关键词（**必填**） | `q=人工智能` |
| `language` | 语言/地区 | `zh-CN`, `en`, `ja`, `de-DE` |
| `format` | 输出格式 | `json`, `html`, `rss` |
| `categories` | 搜索分类 | `general`, `images`, `news`, `videos`, `it`, `science` |
| `time_range` | 时间筛选 | `day`, `week`, `month`, `year` |
| `pageno` | 页码 | `1`, `2`, `3` |
| `safesearch` | 安全搜索 | `0`(关), `1`(中), `2`(严格) |

### 双语搜索 API 示例

```bash
#!/bin/bash
# 保存为 bilingual_search.sh

QUERY="$1"
URL="${SEARXNG_URL:-http://localhost:8080}"

# 并行执行中英文搜索（速度更快）
echo "Searching in both Chinese and English..."

# 使用后台进程并行执行
(curl -s "${URL}/search?q=${QUERY}&language=zh-CN&format=json&categories=general" > /tmp/cn_results.json)&
(curl -s "${URL}/search?q=${QUERY}&language=en&format=json&categories=general" > /tmp/en_results.json)&

wait

echo "\n🇨🇳 中文结果 (Top 3):"
cat /tmp/cn_results.json | jq -r '.results[:3][] | "• \(.title)\n  \(.url)\n"'

echo "\n🇺🇸 English Results (Top 3):"
cat /tmp/en_results.json | jq -r '.results[:3][] | "• \(.title)\n  \(.url)\n"'

# 清理临时文件
rm -f /tmp/cn_results.json /tmp/en_results.json
```

## 按分类搜索

```bash
# 一般网页搜索（默认）
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&categories=general&format=json"

# 图片搜索
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&categories=images&format=json"

# 新闻搜索（适合双语新闻对比）
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&categories=news&time_range=week&format=json"

# IT/技术文档
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&categories=it&format=json"

# 科学/学术
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&categories=science&format=json"

# 视频
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&categories=videos&format=json"
```

## 高级筛选技巧

### 时间范围筛选（重要）

```bash
# 获取最新中文资讯
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=AI新闻&language=zh-CN&time_range=day&format=json"

# 获取本周英文技术动态
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=machine learning&language=en&time_range=week&format=json"

# 获取月度对比数据
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=经济数据&language=zh-CN&time_range=month&format=json"
```

### 多引擎指定搜索

```bash
# 仅使用 Google 和 Bing
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=query&engines=google,bing&format=json"

# 学术搜索（Wikipedia + Wolfram + 学术引擎）
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=quantum computing&categories=science&format=json"
```

## 快速自检

```bash
curl "${SEARXNG_URL:-http://localhost:8080}/search?q=test&format=json" | jq '.results[:1]'
```

## 响应格式说明

```json
{
  "query": "搜索词",
  "number_of_results": 1000000,
  "results": [
    {
      "title": "结果标题",
      "url": "https://example.com",
      "content": "结果摘要描述...",
      "engines": ["google", "bing"],
      "score": 15.5,
      "category": "general"
    }
  ]
}
```

**字段说明：**
- `title`: 结果标题
- `url`: 链接地址
- `content`: 摘要/描述
- `engines`: 返回此结果的搜索引擎数组
- `score`: 相关性评分（越高越好）
- `category`: 结果分类

## Docker 管理

```bash
# 启动 SearXNG
cd /path/to/searxng-deploy && docker compose up -d

# 停止
docker compose down

# 查看日志
docker compose logs -f searxng

# 重启
docker compose restart

# 更新镜像
docker compose pull && docker compose up -d
```

## 故障排除

**问题：容器无法启动**
```bash
docker compose logs searxng
# 检查端口冲突：lsof -i :8080
```

**问题：JSON 格式不工作**
确保 `settings.yml` 中已启用：`formats: [html, json]`

**问题：搜索结果为空**
- 某些引擎可能被限速，检查日志中的错误
- 尝试更换 `language` 参数
- 检查网络连接

**问题：中文搜索结果质量差**
- 确保 `language=zh-CN` 参数已设置
- 尝试添加 `&engines=baidu,google,bing` 指定中文友好引擎

## 为什么使用 SearXNG？

- **🔒 隐私保护**：无跟踪、无广告、无数据收集
- **🌐 双语支持**：轻松实现中英文并行搜索，信息更全面
- **🔍 聚合搜索**：结合 70+ 搜索引擎的结果
- **🏠 自托管**：数据保留在本地，完全可控
- **⚡ API 支持**：JSON 输出，便于自动化和集成
- **💰 免费开源**：无需 API 密钥，无速率限制

## 最佳实践

1. **默认使用双语搜索**：`searxng_bilingual` 函数确保不遗漏重要信息
2. **技术搜索用英文**：编程、AI 等技术领域，英文结果通常更全面
3. **本地信息用中文**：新闻、政策、本地服务等优先使用中文
4. **设置时间筛选**：技术类搜索建议添加 `time_range=month` 获取最新信息
5. **结果去重**：双语搜索可能产生重复结果，建议根据 `url` 字段去重
```

### 主要优化点总结：

1. **双语搜索提示**：在文档显著位置添加提示，建议用户默认进行两次搜索（中+英）
2. **新增函数**：
   - `searxng_bilingual`: 自动进行中英文双重搜索，结果分区显示
   - `searxng_cn`: 仅中文搜索
   - `searxng_en`: 仅英文搜索
3. **并行搜索脚本**：使用后台进程 `&` 和 `wait` 实现中英文请求并行，提升速度
4. **简化表格**：将原有过长的参数表格精简为最实用的 7 个核心参数
5. **视觉区分**：使用 🇨🇳/🇺🇸 国旗 emoji 区分中英文搜索结果
6. **实用建议**：在"最佳实践"中明确指导何时用中文、何时用英文搜索
