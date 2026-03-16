#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import shutil
from collections import defaultdict
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, unquote, urlparse, urlunparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from common import parse_json_arg, write_json, write_markdown

REQUIRED_SOURCE_FIELDS = [
    "source_name",
    "metric_name",
    "definition",
    "unit",
    "geography",
    "time_period",
    "published_at",
    "confidence",
    "url",
]

OPTIONAL_SOURCE_FIELDS = [
    "title",
    "snippet",
    "search_query",
    "notes",
    "source_tier",
    "canonical_url",
    "domain",
]

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "source",
    "ref",
    "ref_src",
    "ved",
}

SEARCH_TYPE_RULES = [
    ("news_or_event", ["最新", "消息", "动态", "报道", "news", "update"], 8, 6),
    ("knowledge_or_definition", ["是什么", "定义", "解释", "what is", "definition"], 5, 4),
    ("professional_or_data", ["价格", "走势", "分析", "财报", "数据", "benchmark", "metrics", "data"], 20, 10),
    ("tutorial_or_guide", ["教程", "使用", "怎么", "攻略", "教学", "guide", "tutorial", "how to"], 20, 8),
    ("product_or_review", ["评测", "测评", "推荐", "review"], 10, 6),
]

DEFAULT_SEARCH_COUNT = 8
DEFAULT_READ_COUNT = 5
DEFAULT_BING_URL = "https://cn.bing.com/search?q={query}&count={count}&setlang=zh-Hans"
DEFAULT_GOOGLE_URL = "https://www.google.com/search?q={query}&num={count}&hl=zh-CN"
DEFAULT_AGENT_BROWSER_SESSION = "data-analysis-web-search"
DEFAULT_BROWSER_RUNTIME_ROOT = Path("/tmp/data-analysis-web-search")
DEFAULT_BROWSER_BACKEND_ORDER = ("agent_browser", "chrome_dump_dom", "html_fetch")
DEFAULT_SEARCH_WORKERS = 3
DEFAULT_FETCH_WORKERS = 4
DEFAULT_PER_ENGINE_RESULT_CAP = 10
COMMON_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
}

CHROME_BINARY_CANDIDATES = [
    os.environ.get("DATA_ANALYSIS_CHROME_BINARY"),
    os.environ.get("CHROME_BINARY"),
    shutil.which("google-chrome"),
    shutil.which("google-chrome-stable"),
    shutil.which("chromium"),
    shutil.which("chromium-browser"),
    shutil.which("chrome"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
]

PLAYWRIGHT_BROWSER_PATH_CANDIDATES = [
    os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
    str(Path.home() / "Library/Caches/ms-playwright"),
    str(Path.home() / ".cache/ms-playwright"),
]


def _resolve_playwright_browsers_path() -> str | None:
    for candidate in PLAYWRIGHT_BROWSER_PATH_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return None


def resolve_default_chrome_binary() -> str | None:
    for candidate in CHROME_BINARY_CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return str(path)
    return None


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    clean_query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in TRACKING_QUERY_KEYS]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or parsed.path,
            parsed.params,
            urlencode(clean_query),
            "",
        )
    )


def source_tier_for_domain(domain: str | None, source_name: str | None = None) -> str:
    host = (domain or "").lower()
    name = (source_name or "").lower()
    if any(token in host for token in [".gov", ".gov.cn", "sec.gov", "stats.gov", "gov.uk"]) or any(token in name for token in ["official", "regulator", "statistics bureau", "sec"]):
        return "tier_1_official"
    if any(token in host for token in ["investor", "ir.", "annualreports", "nasdaq", "nyse", "hkex", "sse.com", "szse.cn"]):
        return "tier_1_company_or_exchange"
    if any(token in host for token in ["nature.com", "sciencedirect.com", "arxiv.org", "nber.org", "oecd.org", "worldbank.org", "imf.org"]):
        return "tier_2_research"
    if any(token in host for token in ["reuters.com", "bloomberg.com", "ft.com", "wsj.com", "caixin.com", "stcn.com", "36kr.com"]):
        return "tier_3_media"
    return "tier_4_other"


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_source_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for record in records:
        normalized_record = {field: record.get(field) for field in REQUIRED_SOURCE_FIELDS}
        for field in OPTIONAL_SOURCE_FIELDS:
            normalized_record[field] = record.get(field)
        canonical_url = canonicalize_url(normalized_record.get("url"))
        domain = urlparse(canonical_url or normalized_record.get("url") or "").netloc.lower() or None
        source_tier = normalized_record.get("source_tier") or source_tier_for_domain(domain, normalized_record.get("source_name"))
        completeness = sum(1 for field in REQUIRED_SOURCE_FIELDS if normalized_record.get(field) not in (None, "")) / len(REQUIRED_SOURCE_FIELDS)
        explicit_confidence = _safe_float(normalized_record.get("confidence"))
        tier_score = {
            "tier_1_official": 0.95,
            "tier_1_company_or_exchange": 0.9,
            "tier_2_research": 0.85,
            "tier_3_media": 0.7,
            "tier_4_other": 0.5,
        }[source_tier]
        inferred_confidence = round(min(0.99, max(0.05, 0.6 * tier_score + 0.4 * completeness)), 4)
        normalized_record.update(
            {
                "canonical_url": canonical_url,
                "domain": domain,
                "source_tier": source_tier,
                "completeness": round(completeness, 4),
                "confidence": explicit_confidence if explicit_confidence is not None else inferred_confidence,
                "inferred_confidence": inferred_confidence,
            }
        )
        normalized.append(normalized_record)
    return normalized


def _record_key(record: dict[str, Any]) -> tuple[str, str]:
    metric_name = str(record.get("metric_name") or "").strip().lower()
    canonical_url = str(record.get("canonical_url") or record.get("url") or "").strip().lower()
    return metric_name, canonical_url


def deduplicate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for record in normalize_source_records(records):
        key = _record_key(record)
        if key not in best_by_key:
            best_by_key[key] = record
            continue
        existing = best_by_key[key]
        existing_score = existing.get("completeness", 0) + float(existing.get("confidence") or 0)
        candidate_score = record.get("completeness", 0) + float(record.get("confidence") or 0)
        if candidate_score > existing_score:
            best_by_key[key] = record
    return list(best_by_key.values())


def detect_source_conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in deduplicate_records(records):
        grouped[str(record.get("metric_name"))].append(record)
    for metric_name, metric_records in grouped.items():
        for field in ("definition", "unit", "geography", "time_period"):
            values = {str(record.get(field)).strip() for record in metric_records if record.get(field) not in (None, "")}
            if len(values) > 1:
                conflicts.append({"metric_name": metric_name, "field": field, "values": sorted(values)})
    return conflicts


def summarize_source_package(records: list[dict[str, Any]]) -> dict[str, Any]:
    deduped = deduplicate_records(records)
    conflicts = detect_source_conflicts(deduped)
    metric_summary: dict[str, Any] = defaultdict(lambda: {"count": 0, "domains": set(), "tiers": set()})
    for record in deduped:
        metric_name = str(record.get("metric_name") or "unknown")
        metric_summary[metric_name]["count"] += 1
        if record.get("domain"):
            metric_summary[metric_name]["domains"].add(record["domain"])
        if record.get("source_tier"):
            metric_summary[metric_name]["tiers"].add(record["source_tier"])
    return {
        "record_count_raw": len(records),
        "record_count_deduplicated": len(deduped),
        "records": deduped,
        "conflicts": conflicts,
        "metrics": {
            metric_name: {
                "count": summary["count"],
                "domains": sorted(summary["domains"]),
                "tiers": sorted(summary["tiers"]),
            }
            for metric_name, summary in metric_summary.items()
        },
    }


def render_source_markdown(records: list[dict[str, Any]]) -> str:
    normalized = deduplicate_records(records)
    lines = [
        "| Source | Metric | Definition | Unit | Geography | Period | Confidence | Tier | URL |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in normalized:
        lines.append(
            "| {source_name} | {metric_name} | {definition} | {unit} | {geography} | {time_period} | {confidence} | {source_tier} | {url} |".format(
                **{key: record.get(key, "") or "" for key in [*REQUIRED_SOURCE_FIELDS, "source_tier"]}
            )
        )
    return "\n".join(lines)


def _extract_years(text: str | None) -> list[str]:
    if not text:
        return []
    years = re.findall(r"(?:19|20)\d{2}", text)
    return sorted(set(years))


def classify_search_request(config: dict[str, Any]) -> dict[str, Any]:
    query = str(config.get("query", "")).strip()
    lowered = query.lower()
    search_type = "general"
    search_count = DEFAULT_SEARCH_COUNT
    read_count = DEFAULT_READ_COUNT
    for candidate_type, keywords, candidate_search_count, candidate_read_count in SEARCH_TYPE_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            search_type = candidate_type
            search_count = candidate_search_count
            read_count = candidate_read_count
            break
    query_years = _extract_years(query)
    if not query_years and any(token in lowered for token in ["latest", "recent", "最新", "近期"]):
        query_years = ["2026"]
    return {
        "search_type": search_type,
        "search_count": int(config.get("search_count", search_count)),
        "read_count": int(config.get("read_count", read_count)),
        "query_years": query_years,
    }


def build_research_request(config: dict[str, Any]) -> dict[str, Any]:
    query = config["query"]
    metric_name = config.get("metric_name")
    geography = config.get("geography")
    time_period = config.get("time_period")
    purpose = config.get("purpose", "metric_definition_and_benchmarking")
    structured_fields = REQUIRED_SOURCE_FIELDS
    search_strategy = classify_search_request(config)

    prompt_parts = [
        f"Research this query for a structured data-analysis workflow: {query}",
        "Return only structured source candidates for data analysis.",
        f"Capture fields: {', '.join(structured_fields)}.",
        "Prefer official, regulator, exchange, IR, or research sources before media.",
        "Deduplicate near-identical URLs and note conflicting metric definitions or units.",
        "When sandboxed, prefer sandbox-compatible browser search or direct Bing/Google SERP extraction before giving up.",
        f"Search type: {search_strategy['search_type']}.",
        f"Search result budget: {search_strategy['search_count']}.",
        f"Read budget: {search_strategy['read_count']}.",
    ]
    if metric_name:
        prompt_parts.append(f"Metric focus: {metric_name}.")
    if geography:
        prompt_parts.append(f"Geography: {geography}.")
    if time_period:
        prompt_parts.append(f"Time period: {time_period}.")
    if search_strategy["query_years"]:
        prompt_parts.append(f"Time matching years: {', '.join(search_strategy['query_years'])}.")
    prompt_parts.append(f"Purpose: {purpose}.")

    search_keywords = [query]
    if metric_name:
        search_keywords.append(metric_name)
    if geography:
        search_keywords.append(geography)
    if time_period:
        search_keywords.append(time_period)

    prompt = " ".join(prompt_parts)

    return {
        "query": query,
        "metric_name": metric_name,
        "geography": geography,
        "time_period": time_period,
        "purpose": purpose,
        "search_keywords": [item for item in search_keywords if item],
        "structured_fields": structured_fields,
        "preferred_source_order": [
            "official_or_regulator",
            "company_ir_or_exchange",
            "research_or_whitepaper",
            "reputable_media",
            "other",
        ],
        "search_strategy": search_strategy,
        "external_research_driver": "source_research_adapter",
        "optional_collaboration_skill": "web-search-pro",
        "collaboration_prompt": prompt,
        "research_prompt": prompt,
        "web_search_pro_prompt": prompt,
    }


def build_web_search_request(config: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for older callers."""

    return build_research_request(config)


def _url_request(url: str, timeout: float = 10.0) -> Request:
    headers = dict(COMMON_BROWSER_HEADERS)
    return Request(url, headers=headers)


def _should_bypass_proxy(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _open_url(url: str, timeout: float = 10.0):
    request = _url_request(url, timeout=timeout)
    if _should_bypass_proxy(url):
        opener = build_opener(ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urlopen(request, timeout=timeout)


def _run_command(command: list[str], timeout: float = 20.0, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "returncode": None}
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}


def _record_latency(payload: dict[str, Any], started_at: float) -> dict[str, Any]:
    payload["latency_seconds"] = round(time.perf_counter() - started_at, 3)
    return payload


def _browser_runtime_root(config: dict[str, Any]) -> Path:
    return Path(config.get("browser_runtime_root") or DEFAULT_BROWSER_RUNTIME_ROOT)


def _ensure_browser_runtime(root: Path) -> dict[str, str]:
    home = root / "home"
    tmpdir = root / "tmp"
    state = home / ".agent-browser"
    cache = home / ".cache"
    config = home / ".config"
    for path in [root, home, tmpdir, state, cache, config]:
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["TMPDIR"] = str(tmpdir)
    env["XDG_STATE_HOME"] = str(state)
    env["XDG_CACHE_HOME"] = str(cache)
    env["XDG_CONFIG_HOME"] = str(config)
    playwright_browsers_path = _resolve_playwright_browsers_path()
    if playwright_browsers_path:
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", playwright_browsers_path)
    return env


def _probe_unix_socket_support(root: Path) -> tuple[bool, str | None]:
    probe_dir = root / "socket-probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_path = probe_dir / f"agent-browser-{os.getpid()}-{time.time_ns()}.sock"
    sock = None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(probe_path))
        return True, None
    except Exception as exc:
        return False, str(exc)
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        try:
            probe_path.unlink()
        except OSError:
            pass


def _agent_browser_base_command(session: str | None = None, profile: str | None = None) -> list[str]:
    command = ["agent-browser"]
    if session:
        command.extend(["--session", session])
    if profile:
        command.extend(["--profile", profile])
    return command


def _build_search_url(engine: str, query: str, count: int) -> str:
    encoded_query = urlencode({"q": query})[2:]
    if engine == "bing":
        return DEFAULT_BING_URL.format(query=encoded_query, count=count)
    if engine == "google":
        return DEFAULT_GOOGLE_URL.format(query=encoded_query, count=count)
    raise ValueError(f"Unsupported search engine: {engine}")


def _normalize_search_items(raw_items: list[dict[str, Any]], engine: str, backend: str) -> list[dict[str, Any]]:
    results = []
    for item in raw_items:
        url_value = canonicalize_url(item.get("url"))
        if not url_value:
            continue
        domain = urlparse(url_value).netloc.lower() or None
        title = str(item.get("title") or "").strip() or None
        snippet = str(item.get("snippet") or "").strip() or None
        results.append(
            {
                "engine": engine,
                "backend": backend,
                "title": title,
                "url": url_value,
                "snippet": snippet,
                "published_at": item.get("published_at"),
                "source_name": domain or title,
                "domain": domain,
            }
        )
    return results


def _extract_google_result_url(href: str | None) -> str | None:
    if not href:
        return None
    href = unescape(href)
    if href.startswith("/url?"):
        parsed = urlparse(href)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        href = params.get("q") or params.get("url") or ""
    if href.startswith("http://") or href.startswith("https://"):
        host = urlparse(href).netloc.lower()
        if "google." in host and "/search" in href:
            return None
        return href
    return None


def _parse_bing_serp_html(raw_html: str, count: int, backend: str) -> list[dict[str, Any]]:
    items = []
    blocks = re.findall(r'(?is)<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>', raw_html)
    for block in blocks:
        anchor = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not anchor:
            continue
        snippet_match = re.search(r'(?is)<div[^>]*class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>', block)
        items.append(
            {
                "title": _clean_html_text(anchor.group(2)),
                "url": unescape(anchor.group(1)),
                "snippet": _clean_html_text(snippet_match.group(1)) if snippet_match else None,
                "published_at": _extract_date(_clean_html_text(block)),
            }
        )
        if len(items) >= count:
            break
    return _normalize_search_items(items, engine="bing", backend=backend)


def _parse_google_serp_html(raw_html: str, count: int, backend: str) -> list[dict[str, Any]]:
    items = []
    seen_urls: set[str] = set()
    for href, inner_html in re.findall(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', raw_html):
        target_url = _extract_google_result_url(href)
        if not target_url:
            continue
        title_match = re.search(r"(?is)<h3[^>]*>(.*?)</h3>", inner_html)
        if not title_match:
            continue
        title = _clean_html_text(title_match.group(1))
        if not title or target_url in seen_urls:
            continue
        snippet = _clean_html_text(inner_html)
        if snippet.startswith(title):
            snippet = snippet[len(title) :].strip(" :-")
        items.append({"title": title, "url": target_url, "snippet": snippet or None, "published_at": None})
        seen_urls.add(target_url)
        if len(items) >= count:
            break
    return _normalize_search_items(items, engine="google", backend=backend)


def _parse_serp_html(raw_html: str, engine: str, backend: str, count: int) -> list[dict[str, Any]]:
    if engine == "bing":
        return _parse_bing_serp_html(raw_html, count=count, backend=backend)
    if engine == "google":
        return _parse_google_serp_html(raw_html, count=count, backend=backend)
    raise ValueError(f"Unsupported search engine: {engine}")


def _agent_browser_eval_script(engine: str, count: int) -> str:
    if engine == "bing":
        return (
            "JSON.stringify(Array.from(document.querySelectorAll('li.b_algo')).slice(0,"
            f"{count}"
            ").map((item) => ({"
            "title: item.querySelector('h2 a')?.innerText || null,"
            "url: item.querySelector('h2 a')?.href || null,"
            "snippet: item.querySelector('.b_caption p')?.innerText || null"
            "})))"
        )
    if engine == "google":
        return (
            "JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map((anchor) => {"
            "const rawHref = anchor.getAttribute('href') || '';"
            "let href = rawHref;"
            "if (rawHref.startsWith('/url?')) {"
            "  try { href = new URL(rawHref, location.origin).searchParams.get('q') || rawHref; } catch (e) {}"
            "}"
            "const title = anchor.querySelector('h3')?.innerText || null;"
            "const snippet = anchor.closest('div')?.innerText || null;"
            "return { title, url: href, snippet };"
            "}).filter((item) => item.title && item.url && /^https?:/i.test(item.url)).slice(0,"
            f"{count}"
            "))"
        )
    raise ValueError(f"Unsupported search engine: {engine}")


def search_serp_via_agent_browser(query: str, count: int, engine: str, config: dict[str, Any]) -> dict[str, Any]:
    runtime_root = _browser_runtime_root(config)
    socket_ok, socket_error = _probe_unix_socket_support(runtime_root)
    if not socket_ok:
        return {
            "engine": engine,
            "backend": "agent_browser",
            "available": False,
            "error": f"Sandbox does not allow agent-browser Unix sockets: {socket_error}",
            "results": [],
        }

    env = _ensure_browser_runtime(runtime_root)
    auto_close_browser = "browser_session" not in config
    session = str(config.get("browser_session") or f"{DEFAULT_AGENT_BROWSER_SESSION}-{engine}-{int(time.time() * 1000)}")
    command_prefix = _agent_browser_base_command(session=session)
    search_url = _build_search_url(engine, query, count=count)

    try:
        open_result = _run_command([*command_prefix, "open", search_url], timeout=25.0, env=env)
        if not open_result["ok"]:
            return {"engine": engine, "backend": "agent_browser", "available": False, "error": open_result["stderr"] or open_result["stdout"], "results": []}

        _run_command([*command_prefix, "wait", "1200"], timeout=6.0, env=env)
        eval_result = _run_command([*command_prefix, "eval", _agent_browser_eval_script(engine, count)], timeout=25.0, env=env)
        if not eval_result["ok"]:
            return {"engine": engine, "backend": "agent_browser", "available": False, "error": eval_result["stderr"] or eval_result["stdout"], "results": []}

        try:
            raw_results = json.loads(eval_result["stdout"].strip() or "[]")
        except json.JSONDecodeError:
            return {"engine": engine, "backend": "agent_browser", "available": False, "error": f"{engine} result extraction returned invalid JSON.", "results": []}
        if isinstance(raw_results, str):
            try:
                raw_results = json.loads(raw_results or "[]")
            except json.JSONDecodeError:
                return {"engine": engine, "backend": "agent_browser", "available": False, "error": f"{engine} result extraction returned stringified invalid JSON.", "results": []}
        if not isinstance(raw_results, list):
            return {"engine": engine, "backend": "agent_browser", "available": False, "error": f"{engine} result extraction returned unsupported payload type.", "results": []}
        results = _normalize_search_items(raw_results, engine=engine, backend="agent_browser")
        if not results:
            return {
                "engine": engine,
                "backend": "agent_browser",
                "available": False,
                "error": f"{engine} page loaded, but no parseable search results were extracted.",
                "results": [],
            }
        return {"engine": engine, "backend": "agent_browser", "available": True, "error": None, "results": results}
    finally:
        if auto_close_browser:
            _run_command(["agent-browser", "close"], timeout=10.0, env=env)


def search_serp_via_chrome_dump_dom(query: str, count: int, engine: str, config: dict[str, Any]) -> dict[str, Any]:
    chrome_binary = str(config.get("chrome_binary") or resolve_default_chrome_binary() or "")
    if not chrome_binary or not Path(chrome_binary).exists():
        return {
            "engine": engine,
            "backend": "chrome_dump_dom",
            "available": False,
            "error": "Chrome binary not found. Set config.chrome_binary or DATA_ANALYSIS_CHROME_BINARY/CHROME_BINARY.",
            "results": [],
        }
    runtime_root = _browser_runtime_root(config)
    user_data_dir = runtime_root / f"chrome-{engine}"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    command = [
        chrome_binary,
        "--headless=new",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--no-first-run",
        f"--user-data-dir={user_data_dir}",
        "--dump-dom",
        _build_search_url(engine, query, count=count),
    ]
    result = _run_command(command, timeout=float(config.get("chrome_timeout", 20.0)))
    if not result["ok"]:
        return {"engine": engine, "backend": "chrome_dump_dom", "available": False, "error": result["stderr"] or result["stdout"] or "Chrome dump-dom failed.", "results": []}
    html = result["stdout"].strip()
    if not html:
        return {"engine": engine, "backend": "chrome_dump_dom", "available": False, "error": "Chrome dump-dom returned empty HTML.", "results": []}
    parsed = _parse_serp_html(html, engine=engine, backend="chrome_dump_dom", count=count)
    if not parsed:
        return {
            "engine": engine,
            "backend": "chrome_dump_dom",
            "available": False,
            "error": f"{engine} page loaded in Chrome, but no parseable search results were found.",
            "results": [],
        }
    return {"engine": engine, "backend": "chrome_dump_dom", "available": True, "error": None, "results": parsed}


def search_serp_via_html_fetch(query: str, count: int, engine: str, timeout: float = 12.0) -> dict[str, Any]:
    search_url = _build_search_url(engine, query, count=count)
    try:
        with _open_url(search_url, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return {"engine": engine, "backend": "html_fetch", "available": False, "error": str(exc), "results": []}
    parsed = _parse_serp_html(html, engine=engine, backend="html_fetch", count=count)
    if not parsed:
        return {
            "engine": engine,
            "backend": "html_fetch",
            "available": False,
            "error": f"{engine} HTML fetch succeeded, but no parseable search results were found.",
            "results": [],
        }
    return {"engine": engine, "backend": "html_fetch", "available": True, "error": None, "results": parsed}


def search_serp_from_fixture(engine: str, count: int, fixture_path: str) -> dict[str, Any]:
    try:
        html = Path(fixture_path).read_text()
    except Exception as exc:
        return {"engine": engine, "backend": "fixture_html", "available": False, "error": str(exc), "results": []}
    parsed = _parse_serp_html(html, engine=engine, backend="fixture_html", count=count)
    return {"engine": engine, "backend": "fixture_html", "available": True, "error": None, "results": parsed}


def _search_backend_order(config: dict[str, Any]) -> list[str]:
    value = config.get("browser_backend_order")
    if isinstance(value, list) and value:
        return [str(item) for item in value]
    return list(DEFAULT_BROWSER_BACKEND_ORDER)


def search_web_engine(query: str, count: int, engine: str, config: dict[str, Any]) -> dict[str, Any]:
    attempts = []
    fixture_path = config.get(f"{engine}_html_fixture")
    if fixture_path:
        started_at = time.perf_counter()
        payload = search_serp_from_fixture(engine, count=count, fixture_path=str(fixture_path))
        payload = _record_latency(payload, started_at)
        payload["attempts"] = [{"backend": payload["backend"], "available": payload["available"], "error": payload.get("error")}]
        return payload

    for backend in _search_backend_order(config):
        started_at = time.perf_counter()
        if backend == "agent_browser":
            payload = search_serp_via_agent_browser(query, count=count, engine=engine, config=config)
        elif backend == "chrome_dump_dom":
            payload = search_serp_via_chrome_dump_dom(query, count=count, engine=engine, config=config)
        elif backend == "html_fetch":
            payload = search_serp_via_html_fetch(query, count=count, engine=engine, timeout=float(config.get("search_timeout", 12.0)))
        else:
            payload = {"engine": engine, "backend": backend, "available": False, "error": f"Unsupported backend: {backend}", "results": []}
        payload = _record_latency(payload, started_at)
        attempts.append({"backend": backend, "available": payload["available"], "error": payload.get("error"), "latency_seconds": payload.get("latency_seconds")})
        if payload.get("available"):
            payload["attempts"] = attempts
            return payload
    return {"engine": engine, "backend": None, "available": False, "error": "All browser backends failed.", "results": [], "attempts": attempts}


def _time_match_score(candidate: dict[str, Any], request: dict[str, Any]) -> float:
    years = request.get("search_strategy", {}).get("query_years", [])
    haystack = " ".join(str(candidate.get(field) or "") for field in ["title", "url", "snippet", "published_at"]).lower()
    if not years:
        return 0.0
    if any(year in haystack for year in years):
        return 0.15
    return 0.0


def _selection_score(candidate: dict[str, Any], request: dict[str, Any]) -> float:
    tier = source_tier_for_domain(candidate.get("domain"), candidate.get("source_name"))
    tier_weight = {
        "tier_1_official": 1.0,
        "tier_1_company_or_exchange": 0.95,
        "tier_2_research": 0.85,
        "tier_3_media": 0.7,
        "tier_4_other": 0.45,
    }[tier]
    title = str(candidate.get("title") or "").lower()
    snippet = str(candidate.get("snippet") or "").lower()
    metric = str(request.get("metric_name") or "").lower()
    geography = str(request.get("geography") or "").lower()
    specificity = 0.0
    if metric and metric in f"{title} {snippet}":
        specificity += 0.12
    if geography and geography in f"{title} {snippet}":
        specificity += 0.08
    return round(tier_weight + specificity + _time_match_score(candidate, request), 4)


def select_candidate_links(results: list[dict[str, Any]], request: dict[str, Any]) -> list[dict[str, Any]]:
    per_domain_count: dict[str, int] = defaultdict(int)
    selected: list[dict[str, Any]] = []
    deduped: dict[str, dict[str, Any]] = {}
    for result in results:
        canonical_url = canonicalize_url(result.get("url"))
        if not canonical_url:
            continue
        if canonical_url in deduped:
            continue
        result = dict(result)
        result["url"] = canonical_url
        result["canonical_url"] = canonical_url
        result["selection_score"] = _selection_score(result, request)
        result["source_tier"] = source_tier_for_domain(result.get("domain"), result.get("source_name"))
        deduped[canonical_url] = result

    for result in sorted(deduped.values(), key=lambda item: item["selection_score"], reverse=True):
        domain = result.get("domain") or "__unknown__"
        if per_domain_count[domain] >= 2:
            continue
        selected.append(result)
        per_domain_count[domain] += 1
        if len(selected) >= int(request["search_strategy"]["read_count"]):
            break
    return selected


def _clean_html_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<title.*?>(.*?)</title>", r"\n\1\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_page_text(url: str, timeout: float = 12.0, max_chars: int = 12000) -> dict[str, Any]:
    try:
        with _open_url(url, timeout=timeout) as response:
            body = response.read(max_chars * 4).decode("utf-8", errors="ignore")
    except Exception as exc:
        return {"url": url, "available": False, "error": str(exc), "title": None, "text": None, "excerpt": None}
    title_match = re.search(r"(?is)<title.*?>(.*?)</title>", body)
    title = unescape(title_match.group(1)).strip() if title_match else None
    text = _clean_html_text(body)[:max_chars]
    excerpt = text[:1200] if text else None
    return {"url": url, "available": True, "error": None, "title": title, "text": text, "excerpt": excerpt}


def _extract_unit(text: str | None, metric_name: str | None) -> str | None:
    haystack = f"{metric_name or ''} {text or ''}".lower()
    if "%" in haystack or "rate" in haystack or "转化率" in haystack or "留存率" in haystack:
        return "%"
    for token in ["cny/user", "usd/user", "cny", "usd", "元/人", "次/人", "times/user"]:
        if token in haystack:
            return token
    return None


def _extract_date(text: str | None) -> str | None:
    if not text:
        return None
    for pattern in [
        r"((?:19|20)\d{2}-\d{2}-\d{2})",
        r"((?:19|20)\d{2}/\d{2}/\d{2})",
        r"((?:19|20)\d{2}\.\d{2}\.\d{2})",
        r"((?:19|20)\d{2}年\d{1,2}月\d{1,2}日)",
        r"((?:19|20)\d{2}年\d{1,2}月)",
    ]:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def heuristic_source_record(candidate: dict[str, Any], request: dict[str, Any], page_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    text = page_bundle.get("text") if page_bundle else None
    snippet = candidate.get("snippet") or (page_bundle.get("excerpt") if page_bundle else None)
    title = candidate.get("title") or (page_bundle.get("title") if page_bundle else None)
    domain = candidate.get("domain")
    metric_name = request.get("metric_name") or request.get("query")
    definition = snippet or title or request.get("query")
    time_period = request.get("time_period")
    if not time_period:
        years = _extract_years(f"{title or ''} {snippet or ''} {text or ''}")
        time_period = years[0] if years else None
    published_at = candidate.get("published_at") or _extract_date(f"{title or ''} {snippet or ''} {text or ''}")
    notes = []
    if page_bundle and not page_bundle.get("available"):
        notes.append(f"Page fetch failed: {page_bundle.get('error')}")
    if not request.get("metric_name"):
        notes.append("Metric name inferred from query because no explicit metric_name was provided.")
    if snippet and len(str(snippet)) < 60 and text:
        definition = text[:240]
    source_name = candidate.get("source_name") or domain or title
    return {
        "source_name": source_name,
        "metric_name": metric_name,
        "definition": str(definition).strip()[:320] if definition else None,
        "unit": _extract_unit(f"{title or ''} {snippet or ''} {text or ''}", metric_name),
        "geography": request.get("geography"),
        "time_period": time_period,
        "published_at": published_at,
        "confidence": None,
        "url": candidate.get("url"),
        "title": title,
        "snippet": snippet,
        "search_query": request.get("query"),
        "notes": " ".join(notes) if notes else None,
        "source_tier": candidate.get("source_tier"),
        "canonical_url": candidate.get("canonical_url"),
        "domain": domain,
    }


def _search_job_specs(request: dict[str, Any], config: dict[str, Any], search_count: int) -> list[tuple[str, Any]]:
    specs: list[tuple[str, Any]] = []
    per_engine_count = min(search_count, int(config.get("per_engine_result_cap", DEFAULT_PER_ENGINE_RESULT_CAP)))
    if not config.get("skip_bing", False):
        specs.append(("bing", lambda: search_web_engine(request["query"], count=per_engine_count, engine="bing", config=config)))
    if not config.get("skip_google", False):
        specs.append(("google", lambda: search_web_engine(request["query"], count=per_engine_count, engine="google", config=config)))
    return specs


def _execute_search_jobs(job_specs: list[tuple[str, Any]], max_workers: int) -> list[dict[str, Any]]:
    if not job_specs:
        return []
    payloads: list[dict[str, Any]] = []

    def _timed_job(job_factory: Any) -> dict[str, Any]:
        started_at = time.perf_counter()
        payload = job_factory()
        if "latency_seconds" not in payload:
            payload = _record_latency(payload, started_at)
        return payload

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(job_specs))) as executor:
        future_to_name = {
            executor.submit(_timed_job, job_factory): engine_name
            for engine_name, job_factory in job_specs
        }
        for future in concurrent.futures.as_completed(future_to_name):
            engine_name = future_to_name[future]
            try:
                payload = future.result()
            except Exception as exc:
                payload = {"engine": engine_name, "available": False, "error": str(exc), "results": []}
            payloads.append(payload)
    payloads.sort(key=lambda item: ["bing", "google"].index(item["engine"]) if item.get("engine") in {"bing", "google"} else 99)
    return payloads


def _fetch_pages_in_parallel(candidates: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    timeout = float(config.get("page_fetch_timeout", 12.0))
    max_chars = int(config.get("page_fetch_max_chars", 12000))
    workers = max(1, int(config.get("max_fetch_workers", DEFAULT_FETCH_WORKERS)))
    ordered_results: list[dict[str, Any] | None] = [None] * len(candidates)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(candidates))) as executor:
        future_to_index = {
            executor.submit(fetch_page_text, candidate["url"], timeout, max_chars): index
            for index, candidate in enumerate(candidates)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                ordered_results[index] = future.result()
            except Exception as exc:
                ordered_results[index] = {
                    "url": candidates[index]["url"],
                    "available": False,
                    "error": str(exc),
                    "title": None,
                    "text": None,
                    "excerpt": None,
                }
    return [item for item in ordered_results if item is not None]


def execute_web_search_request(config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    request = build_research_request(config)
    search_strategy = request["search_strategy"]
    search_count = int(search_strategy["search_count"])
    raw_result_payloads: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    execution_log: list[str] = []

    offline_search_results = config.get("search_results")
    search_results_path = config.get("search_results_json")
    if search_results_path:
        offline_search_results = json.loads(Path(search_results_path).read_text())

    if offline_search_results:
        raw_result_payloads.append({"engine": "offline_fixture", "available": True, "error": None, "results": offline_search_results})
        all_candidates.extend(offline_search_results)
        execution_log.append("Used offline search-results fixture instead of live external-research execution.")
    else:
        search_payloads = _execute_search_jobs(
            _search_job_specs(request, config, search_count),
            max_workers=max(1, int(config.get("max_search_workers", DEFAULT_SEARCH_WORKERS))),
        )
        raw_result_payloads.extend(search_payloads)
        for payload in search_payloads:
            all_candidates.extend(payload.get("results", []))
            backend = payload.get("backend") or "multi"
            if payload.get("available"):
                execution_log.append(
                    f"{payload['engine']} returned {len(payload.get('results', []))} results via {backend} in {payload.get('latency_seconds', 0)}s."
                )
            else:
                execution_log.append(f"{payload['engine']} unavailable via {backend}: {payload.get('error')}")

    selected_candidates = select_candidate_links(all_candidates, request)
    execution_log.append(f"Selected {len(selected_candidates)} links after tier/diversity/time matching.")

    fetched_pages: list[dict[str, Any]] = []
    heuristic_records = []
    fetch_pages = not config.get("skip_page_fetch", False)
    page_bundles_by_url: dict[str, dict[str, Any]] = {}
    if fetch_pages:
        fetched_pages = _fetch_pages_in_parallel(selected_candidates, config)
        page_bundles_by_url = {bundle["url"]: bundle for bundle in fetched_pages}
        execution_log.append(
            f"Fetched {len(fetched_pages)} selected page(s) with up to {min(max(1, int(config.get('max_fetch_workers', DEFAULT_FETCH_WORKERS))), max(1, len(selected_candidates)))} worker(s)."
        )
    for candidate in selected_candidates:
        page_bundle = None
        if fetch_pages:
            page_bundle = page_bundles_by_url.get(candidate["url"])
        heuristic_records.append(heuristic_source_record(candidate, request, page_bundle))

    normalized_package = summarize_source_package(heuristic_records)
    markdown_table = render_source_markdown(heuristic_records)

    report = {
        "request": request,
        "engine_results": raw_result_payloads,
        "selected_candidates": selected_candidates,
        "fetched_pages": fetched_pages,
        "heuristic_records": heuristic_records,
        "normalized_package": normalized_package,
        "execution_log": execution_log,
        "limitations": [
            "Structured source fields are heuristic unless a downstream agent reviews the extracted candidates.",
            "Live search depends on network availability and may degrade to HTML SERP parsing when browser automation is blocked.",
            "Sandboxed environments may block Unix sockets, which disables agent-browser and forces alternate backends.",
            "Search-engine HTML structure changes can reduce Bing/Google extraction quality until selectors are updated.",
        ],
    }

    if output_dir is not None:
        write_json(output_dir / "research_request.json", request)
        write_json(output_dir / "research_engine_results.json", raw_result_payloads)
        write_json(output_dir / "research_selected_candidates.json", selected_candidates)
        write_json(output_dir / "research_fetched_pages.json", fetched_pages)
        write_json(output_dir / "research_heuristic_records.json", heuristic_records)
        write_json(output_dir / "research_sources.json", normalized_package)
        write_markdown(output_dir / "research_sources.md", markdown_table)
        write_json(output_dir / "research_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan, execute, and normalize external research for the data-analysis skill.")
    parser.add_argument("--query", help="Research query to convert into a structured external-research request.")
    parser.add_argument("--metric-name")
    parser.add_argument("--geography")
    parser.add_argument("--time-period")
    parser.add_argument("--purpose")
    parser.add_argument("--input-json", help="Path to raw source records JSON.")
    parser.add_argument("--config-json", help="Inline JSON for planning or execution mode.")
    parser.add_argument("--markdown", action="store_true", help="Render markdown table for normalized records.")
    parser.add_argument("--execute", action="store_true", help="Run the full closed-loop research workflow.")
    parser.add_argument("--output-dir", help="Optional directory to write research artifacts.")
    parser.add_argument("--search-results-json", help="Offline fixture for search result candidates.")
    parser.add_argument("--skip-bing", action="store_true")
    parser.add_argument("--skip-google", action="store_true")
    parser.add_argument("--skip-page-fetch", action="store_true")
    args = parser.parse_args()

    if args.query or args.config_json:
        config = parse_json_arg(args.config_json)
        if args.query:
            config["query"] = args.query
        if args.metric_name:
            config["metric_name"] = args.metric_name
        if args.geography:
            config["geography"] = args.geography
        if args.time_period:
            config["time_period"] = args.time_period
        if args.purpose:
            config["purpose"] = args.purpose
        if args.search_results_json:
            config["search_results_json"] = args.search_results_json
        if args.skip_bing:
            config["skip_bing"] = True
        if args.skip_google:
            config["skip_google"] = True
        if args.skip_page_fetch:
            config["skip_page_fetch"] = True
        if "query" not in config:
            raise ValueError("Planning mode requires a query.")
        if args.execute:
            output_dir = Path(args.output_dir) if args.output_dir else None
            report = execute_web_search_request(config, output_dir=output_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(build_research_request(config), ensure_ascii=False, indent=2))
        return 0

    if args.input_json:
        records = json.loads(Path(args.input_json).read_text())
        if args.markdown:
            print(render_source_markdown(records))
        else:
            print(json.dumps(summarize_source_package(records), ensure_ascii=False, indent=2))
        return 0

    raise ValueError("Provide either --query/--config-json or --input-json.")


if __name__ == "__main__":
    raise SystemExit(main())
