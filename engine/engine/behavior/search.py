# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""联网搜索模块
当理解层判断需要事实性信息时触发，搜索实时信息。
使用 DuckDuckGo 免费搜索（无需API Key），静默降级。
新增缓存层：同查询2小时内复用结果。
"""
import urllib.request
import urllib.parse
import json
import re
import time
import html
import hashlib

# ── 搜索缓存（内存级，进程重启清空）──
_search_cache = {}
_CACHE_TTL_SECONDS = 7200  # 2小时


def load_engine_config():
    pass


def search(query: str, max_results: int = 5) -> str:
    """联网搜索，返回可注入 prompt 的摘要文本。
    搜索结果会被压缩到 500 字以内。
    同查询2小时内直接返回缓存。
    """
    if not query or not query.strip():
        return ""

    # 缓存查一下
    cache_key = hashlib.md5(query.strip().encode()).hexdigest()
    cached = _search_cache.get(cache_key)
    if cached and (time.time() - cached["time"]) < _CACHE_TTL_SECONDS:
        print(f"[搜索] 缓存命中: {query}")
        return cached["result"]

    try:
        results = _duckduckgo_search(query, max_results)
        if not results:
            return ""

        # 压缩为摘要
        summary = _summarize_results(results, query)

        # 存入缓存
        if summary:
            _search_cache[cache_key] = {"result": summary, "time": time.time()}
            # 限制缓存大小
            if len(_search_cache) > 100:
                oldest = min(_search_cache, key=lambda k: _search_cache[k]["time"])
                del _search_cache[oldest]

        return summary
    except Exception as e:
        print(f"[搜索] 失败: {e}")
        return ""


def _duckduckgo_search(query: str, max_results: int = 5) -> list:
    """
    DuckDuckGo 搜索 (无 API Key 方案)
    使用 DDG 的 instant answer API + HTML 搜索页
    """
    results = []
    encoded_query = urllib.parse.quote(query)

    # 尝试 DuckDuckGo Instant Answer API
    try:
        url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "SoulMate/8.1"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # 提取摘要
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("Heading", query),
                    "snippet": data.get("AbstractText", ""),
                    "url": data.get("AbstractURL", ""),
                })
            # 提取关联主题
            for topic in data.get("RelatedTopics", [])[:max_results - len(results)]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                        "snippet": topic.get("Text", ""),
                        "url": topic.get("FirstURL", ""),
                    })
    except Exception:
        pass

    # 如果 DDG API 结果不够，尝试 HTML 搜索页
    if len(results) < 2:
        try:
            html_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            req = urllib.request.Request(html_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) SoulMate/8.1"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                html_content = resp.read().decode("utf-8")
                # 提取搜索结果片段
                snippets = re.findall(
                    r'class="result__snippet"[^>]*>(.*?)</a>',
                    html_content, re.DOTALL
                )
                titles = re.findall(
                    r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>',
                    html_content, re.DOTALL
                )
                for i, (title, snippet) in enumerate(zip(titles, snippets)):
                    if i >= max_results - len(results):
                        break
                    clean_title = re.sub(r'<[^>]+>', '', title).strip()
                    clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                    results.append({
                        "title": html.unescape(clean_title),
                        "snippet": html.unescape(clean_snippet),
                        "url": "",
                    })
        except Exception:
            pass

    return results[:max_results]


def _summarize_results(results: list, query: str) -> str:
    """将搜索结果压缩为简洁的注入文本"""
    if not results:
        return ""

    lines = [f"【实时搜索: {query}】"]

    for i, r in enumerate(results[:4]):
        title = r.get("title", "")[:40]
        snippet = r.get("snippet", "")[:120]
        if snippet:
            lines.append(f"{i+1}. {title}: {snippet}")

    text = "\n".join(lines)
    if len(text) > 500:
        text = text[:497] + "..."

    return text
