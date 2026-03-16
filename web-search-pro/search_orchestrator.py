import asyncio
import json
import re
import os
import shutil
import sys
from urllib.parse import quote, urlparse
from urllib.request import urlopen
from urllib.error import URLError

DEFAULT_SEARXNG_URL = "http://localhost:8080/search"
MAX_CONCURRENT_CRAWLS = int(os.environ.get("MAX_CONCURRENT_CRAWLS", "10"))


def normalize_searxng_url(url):
    normalized = (url or DEFAULT_SEARXNG_URL).strip()
    if normalized.endswith("/"):
        normalized = normalized[:-1]
    if not normalized.endswith("/search"):
        normalized = normalized + "/search"
    return normalized


def resolve_lightpanda_path():
    env_path = os.environ.get("LIGHTPANDA_PATH")
    if env_path:
        candidate = os.path.expanduser(env_path)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
        raise FileNotFoundError(
            f"LIGHTPANDA_PATH 指向的文件不可执行: {candidate}"
        )

    candidate = shutil.which("lightpanda")
    if candidate:
        return candidate

    raise FileNotFoundError(
        "未找到 lightpanda。请先安装 lightpanda 并加入 PATH，"
        "或设置 LIGHTPANDA_PATH=/absolute/path/to/lightpanda"
    )


class SearchOrchestrator:
    def __init__(self, tasks):
        """
        tasks: [{"query": "...", "limit": 10}, ...]
        """
        self.tasks = tasks
        self.all_results = []
        self.final_reports = []
        self.lightpanda_path = resolve_lightpanda_path()
        self.searxng_url = normalize_searxng_url(os.environ.get("SEARXNG_URL"))

    async def run_search(self, query, limit):
        """并行调用 SearXNG，并以 agent-browser 作为兜底"""
        # 1. 尝试 SearXNG
        results = await self.call_searxng(query)
        
        # 2. 如果结果太少或为空，调用 agent-browser 抓取 Bing 作为兜底
        if len(results) < 3:
            print(f"[*] SearXNG 结果不足 ({len(results)})，正在启动 Bing 兜底...")
            fallback_results = await self.call_bing_fallback(query)
            results.extend(fallback_results)
        
        combined = self.merge_and_rank(results, query, limit)
        return combined

    async def call_searxng(self, query):
        try:
            safe_query = quote(query)
            request_url = f"{self.searxng_url}?q={safe_query}&format=json"
            with urlopen(request_url, timeout=5.0) as response:
                payload = response.read().decode()
            if not payload:
                return []
            data = json.loads(payload)
            return [
                {
                    "title": r["title"],
                    "url": r["url"],
                    "snippet": r.get("content", ""),
                    "source": "SearXNG",
                }
                for r in data.get("results", [])
            ]
        except (URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
            return []

    async def call_bing_fallback(self, query):
        """利用 lightpanda 抓取 Bing 搜索结果页并从 Markdown 中解析真实 URL"""
        proc = None
        try:
            import base64
            
            # 还原为普通搜索，避免加引号导致的搜索算法退化
            safe_query = quote(query)
            url = f"https://www.bing.com/search?q={safe_query}"
            
            cmd = [self.lightpanda_path, "fetch", "--dump", "markdown", "--strip_mode", "js,css", url]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await proc.communicate()
            md_content = stdout.decode(errors='ignore')
            
            # 放宽正则：抓取所有 [标题](URL) 格式的链接
            matches = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', md_content)
            
            results = []
            seen_urls = set()
            for title, raw_url in matches:
                # 尝试解码真实 URL
                real_url = raw_url
                if "bing.com/ck/a" in raw_url:
                    try:
                        u_match = re.search(r'[&?]u=a1([^&]+)', raw_url)
                        if u_match:
                            b64_str = u_match.group(1)
                            b64_str += '=' * (-len(b64_str) % 4)
                            decoded_bytes = base64.urlsafe_b64decode(b64_str)
                            real_url = decoded_bytes.decode('utf-8', errors='ignore')
                    except: pass
                
                # 核心过滤：必须包含关键词之一，且不是 Bing 内部链接
                if real_url in seen_urls: continue
                if any(x in real_url for x in ["bing.com", "microsoft.com", "google.com", "zhihu.com/question", "zhihu.com/topic", "javascript:"]):
                    continue
                
                clean_title = title.replace("\\-", "-").replace("\n", "").strip()
                if len(clean_title) < 4: continue
                
                results.append({
                    "title": clean_title,
                    "url": real_url,
                    "snippet": "",
                    "source": "Bing(NativeDecoded)"
                })
                seen_urls.add(real_url)
            return results
        except Exception:
            return []
        finally:
            if proc and proc.returncode is None:
                try:
                    proc.kill()
                    await proc.wait()
                except: pass

    def merge_and_rank(self, results, query, limit):
        """确定性权重算法：引入强关键词奖励"""
        ranked = []
        seen_urls = set()
        domain_counts = {}
        
        # 提取核心词（去除日期和走势等通用词）
        core_keywords = [w for w in re.findall(r'[\u4e00-\u9fa5]{2,}', query) if w not in ['价格', '走势', '数据', '历史', '变动']]
        years = re.findall(r'20\d{2}', query)
        
        for i, res in enumerate(results):
            url = res['url']
            if url in seen_urls: continue
            domain = urlparse(url).netloc
            count = domain_counts.get(domain, 0)
            if count >= 2: continue
            
            score = 100 - i 
            title_snippet = (res['title'] + res.get('snippet', '')).lower()
            
            # 强核心词匹配奖励：如果包含“碳酸锂”等词，大幅加分 (200分)
            if any(k in title_snippet for k in core_keywords):
                score += 200
            
            # 行业词增强
            boost_keywords = ['price', 'trend', 'report', 'index', '走势', '价格', '报告', '指数', '数据', 'smm', '生意社']
            if any(k in title_snippet for k in boost_keywords):
                score += 30
            
            if any(year in title_snippet for year in years):
                score += 50
                
            res['score'] = score
            ranked.append(res)
            seen_urls.add(url)
            domain_counts[domain] = count + 1

        ranked.sort(key=lambda x: x['score'], reverse=True)
        return ranked[:limit]

    async def crawl_link(self, sem, link):
        """使用 Lightpanda 并发抓取 Markdown"""
        async with sem:
            url = link['url']
            proc = None
            try:
                cmd = [self.lightpanda_path, "fetch", "--dump", "markdown", "--strip_mode", "js,css", url]
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                
                # 设置超时防止卡死
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
                    content = stdout.decode(errors='ignore')
                    if not content or len(content) < 100:
                        content = f"[读取失败或内容过短] {stderr.decode(errors='ignore')}"
                except asyncio.TimeoutError:
                    if proc.returncode is None:
                        try:
                            proc.kill()
                            await proc.wait()
                        except: pass
                    content = "[读取超时]"
                
                return {"title": link['title'], "url": url, "content": content}
            except Exception as e:
                return {"title": link['title'], "url": url, "content": f"[系统错误]: {str(e)}"}
            finally:
                if proc and proc.returncode is None:
                    try:
                        proc.kill()
                        await proc.wait()
                    except: pass

    async def execute(self):
        # 1. 批量搜索
        search_tasks = [self.run_search(t['query'], t['limit']) for t in self.tasks]
        search_results = await asyncio.gather(*search_tasks)
        
        # 合并所有任务的链接并进行全局去重
        all_links = []
        seen_urls = set()
        for sublist in search_results:
            for link in sublist:
                if link['url'] not in seen_urls:
                    all_links.append(link)
                    seen_urls.add(link['url'])

        # 2. 并发爬取 (限制并发数)
        sem = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)
        crawl_tasks = [self.crawl_link(sem, link) for link in all_links]
        self.final_reports = await asyncio.gather(*crawl_tasks)

        # 3. 生成最终报告
        return self.generate_final_markdown()

    def generate_final_markdown(self):
        md = "# 综合搜索增强报告\n\n"
        md += f"本次任务共执行了 {len(self.tasks)} 个搜索指令，爬取了 {len(self.final_reports)} 个独立页面。\n\n"
        
        for i, report in enumerate(self.final_reports):
            md += f"## [{i+1}] {report['title']}\n"
            md += f"- **链接**: {report['url']}\n\n"
            content = report['content']
            # 保留关键内容，但进行适度截断
            if len(content) > 3000:
                content = content[:3000] + "\n\n...(内容已截断，请根据需要进一步深度读取)..."
            md += content + "\n\n"
            md += "---\n\n"
        return md

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            raw_input = sys.argv[1]
            # 支持 JSON 列表或单个查询字符串
            if raw_input.startswith('['):
                input_tasks = json.loads(raw_input)
            else:
                input_tasks = [{"query": raw_input, "limit": 10}]
                
            orchestrator = SearchOrchestrator(input_tasks)
            report = asyncio.run(orchestrator.execute())
            print(report)
        except Exception as e:
            print(f"错误: {str(e)}")
            sys.exit(1)
    else:
        print("用法: python3 search_orchestrator.py '[{\"query\": \"...\", \"limit\": 10}]'")
