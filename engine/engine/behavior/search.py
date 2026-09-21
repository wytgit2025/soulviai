# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""联网搜索模块
当理解层判断需要事实性信息时触发，搜索实时信息。
后端按顺序尝试：Bing（cn.bing.com）→ 搜狗 → Bing 国际站（www.bing.com），
全部免 API Key、静默降级，谁先凑够 2 条就停。
自带缓存：同查询 2 小时内复用结果（内存 + data/json/search_cache.json）。

磁盘那份是必需的：`soulviaictl chat` 每次调用都是一个新进程，纯内存缓存对它
恒不命中 —— 等于每条消息都真联网。同一模式的实现在 social/env_source.py，
两份缓存刻意保持一致的行为。

为什么 Bing 排第一：cn.bing.com 返回的是完整网页搜索结果，实测 0.23s / 10 条，境内可达。

为什么第二源是搜狗而不是百度：实测百度 www.baidu.com/s 返回的是 1438 字节的「百度
安全验证」页（HTTP 状态码仍是 200），先访问首页拿 BAIDUID 等 Cookie 也一样被拦，
零条可解析结果，是死源。搜狗的标题与摘要质量都很好，但连续请求几次就会 302 到
sogou.com/antispider/，属于「能用但需要降温」的备源，所以排在 Bing 后面当兜底，
被拦时由熔断器冷掉。

DuckDuckGo 已移除：它连的 api.duckduckgo.com 是「词条摘要」接口而不是搜索接口，对
「杭州天气」这类事务型查询设计上就不返回东西；真能做通用搜索的 html.duckduckgo.com
境内又不可达。实测两次都是 8 秒超时（4s+4s）后 0 条，等于让用户白等 8 秒换一个
「没搜到」。它原来的兜底位改由 Bing 国际站顶上 —— 同一套结果结构，解析器直接复用。

头条排除：so.toutiao.com 能出结果，但单次响应 1.8MB（Bing 的 19 倍）、标题内嵌在
JSON 里要二次解析，代价远高于收益。

反爬的教训是「200 不等于成功」。所以每个后端解析后都要过 _looks_blocked()，拦截页
一律当失败 —— 否则会把一份空结果当有效搜索缓存两个小时，熔断器也永远不会生效。
"""
import urllib.request
import urllib.parse
import re
import time
import html
import hashlib
import json
import os
import threading

# ── 搜索缓存（内存 + 磁盘；磁盘用于跨进程复用）──
_search_cache = {}
_CACHE_TTL_SECONDS = 7200  # 2小时
_CACHE_MAX = 100
_CACHE_PARTS = ("json", "search_cache.json")
_cache_lock = threading.RLock()
_disk_loaded = False

# ── 后端熔断 ──
# 某个后端连续失败后先冷掉一段时间，避免每次都白等它的超时（搜狗撞上 antispider、
# Bing 超时都会走到这里）。注意这是进程内存态，重启即归零。
_BACKEND_FAILS = {}          # name -> (连续失败次数, 最近失败时间)
_BACKEND_MAX_FAILS = 2
_BACKEND_COOLDOWN = 600      # 10 分钟
_HTTP_TIMEOUT = 4            # 单个后端超时；搜索在对话主链路上，不能太久
_UA_DESKTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/120.0 Safari/537.36")

# 反爬拦截的两种形态。只看状态码一个都认不出来 —— 两种都是 HTTP 200。
_BLOCK_URL_PARTS = ("/antispider", "wappass.baidu.com", "/verify", "/captcha",
                    "/sorry/", "security_check")
_BLOCK_MARKERS = ("百度安全验证", "antispider", "请输入验证码", "滑动验证",
                  "人机验证", "Verify you are human")

# 搜狗的推荐位 / 相关搜索块，混在 <h3> 里但不是自然结果
_SOGOU_NOISE = ("其他人还搜了", "相关搜索", "大家还在搜", "相关资讯")


def _looks_blocked(text: str, final_url: str = "") -> bool:
    """判断这次请求是不是被反爬拦了。

    要查两处，因为拦截有两种形态、且都是 HTTP 200：

      · 最终 URL —— 搜狗被拦会 302 到 sogou.com/antispider/?antip=web_sh2，
        返回一个 5439 字节的正经页面，正文里挑不出任何异常字样；
      · 正文特征 —— 百度直连返回 1438 字节的「百度安全验证」页，URL 不变。

    两种如果都当成成功，就会把一份空结果当有效搜索缓存两小时，还会让熔断器
    一直以为这个后端是好的、每次都去白等它。
    """
    if final_url and any(p in final_url for p in _BLOCK_URL_PARTS):
        return True
    if not text:
        return True
    low = text.lower()
    return any(m.lower() in low for m in _BLOCK_MARKERS)


def _backend_ok(name: str) -> bool:
    fails, last = _BACKEND_FAILS.get(name, (0, 0.0))
    if fails < _BACKEND_MAX_FAILS:
        return True
    return (time.time() - last) > _BACKEND_COOLDOWN


def _mark_backend(name: str, ok: bool):
    if ok:
        _BACKEND_FAILS.pop(name, None)
        return
    fails, _ = _BACKEND_FAILS.get(name, (0, 0.0))
    _BACKEND_FAILS[name] = (fails + 1, time.time())


def load_engine_config():
    pass


# ── 磁盘缓存：让「一次进程说一句话」的 soulviaictl chat 也能复用结果 ──

def _cache_path() -> str:
    try:
        from core import paths as _paths
        return _paths.data_path(*_CACHE_PARTS)
    except Exception:
        return ""


def _load_disk_cache():
    """进程内第一次搜索时把磁盘缓存搬进内存（只做一次）。"""
    global _disk_loaded
    with _cache_lock:
        if _disk_loaded:
            return
        _disk_loaded = True
    path = _cache_path()
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    now = time.time()
    fresh = {}
    for key, item in data.items():
        if not isinstance(item, dict) or not item.get("result"):
            continue
        try:
            if (now - float(item.get("time") or 0)) < _CACHE_TTL_SECONDS:
                fresh[key] = item
        except Exception:
            continue
    if fresh:
        with _cache_lock:
            _search_cache.update(fresh)


def _save_disk_cache():
    path = _cache_path()
    if not path:
        return
    try:
        with _cache_lock:
            snapshot = dict(_search_cache)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass


# engine_bridge._api_error() 会在本轮引擎输出里按子串找下面这些词，命中就把一次
# 正常对话报成 status=backend_error。`[搜索]` 前缀挡不住它 —— 它看的是整行。
# 所以失败原因只保留异常类型名，命中这些词的一律换成中性说法。
# social/env_source.py 的 `[环境]` 日志出于同一个原因做过同样规避。
_LOG_UNSAFE = ("timeout", "timed out", "connection", "unreachable", "401",
               "api key", "rate limit", "ratelimit", "quota", "balance")


def _safe_reason(exc) -> str:
    """异常摘要（剥掉会被误判成「模型后端故障」的 ASCII 报错词）。"""
    name = type(exc).__name__
    return "网络层异常" if any(w in name.lower() for w in _LOG_UNSAFE) else name


def no_result_notice(query: str) -> str:
    """「查了但没查到」时该注入的文本。

    调用方是 `search(q) or no_result_notice(q)`，返回值必须非空。原因在推理层：
    搜索结果注入是 `if search_result:`，空字符串等于什么都没发生 ——
    模型分不清「没搜」和「搜了没搜到」，于是对时效性事实照答不误（编造）。
    给一句明确的「没查到」，比给空字符串安全得多。
    """
    q = (query or "").strip()
    return ("【实时搜索: %s】\n"
            "（已经联网查过，但没有取到可用结果。这件事你没有可靠依据："
            "不确定就直说不知道、或让对方补充，不要编造。）" % q)


def search(query: str, max_results: int = 5) -> str:
    """联网搜索，返回可注入 prompt 的摘要文本。

    结果压缩到 500 字以内；同查询 2 小时内直接返回缓存（内存 + 磁盘）。
    没取到任何**带摘要**的结果时返回空字符串 —— 需要「已查但没查到」的语义时，
    调用方自行用 no_result_notice() 兜底。
    """
    if not query or not query.strip():
        return ""

    _load_disk_cache()

    cache_key = hashlib.md5(query.strip().encode()).hexdigest()
    with _cache_lock:
        cached = _search_cache.get(cache_key)
        if cached and (time.time() - cached["time"]) < _CACHE_TTL_SECONDS:
            print(f"[搜索] 缓存命中: {query}")
            return cached["result"]

    try:
        results = _collect_results(query, max_results)
        if not results:
            return ""

        summary = _summarize_results(results, query)
        if not summary:
            return ""

        with _cache_lock:
            _search_cache[cache_key] = {"result": summary, "time": time.time()}
            if len(_search_cache) > _CACHE_MAX:
                oldest = min(_search_cache, key=lambda k: _search_cache[k]["time"])
                del _search_cache[oldest]
        _save_disk_cache()
        return summary
    except Exception as exc:
        print(f"[搜索] 本轮未取到结果（{_safe_reason(exc)}）")
        return ""


def _collect_results(query: str, max_results: int = 5) -> list:
    """按后端顺序凑结果：Bing → 搜狗 → Bing 国际站，凑够 2 条就停。

    某个后端连续失败会被熔断冷掉（见 _backend_ok），不会每次都白等它的超时。
    """
    results = []
    seen = set()

    for name, fetch in (("bing", _bing_cn_search), ("sogou", _sogou_search),
                        ("bing-intl", _bing_intl_search)):
        if len(results) >= 2:
            break
        if not _backend_ok(name):
            continue
        got = fetch(query, max_results)
        _mark_backend(name, bool(got))
        for item in got:
            title = item.get("title")
            if title and title not in seen:
                seen.add(title)
                results.append(item)

    return results[:max_results]


def _bing_search(query: str, max_results: int = 5,
                 host: str = "cn.bing.com") -> list:
    """Bing 搜索（免 Key，主源）。host 决定走境内加速域名还是国际站。

    解析 `<li class="b_algo">` 结果块；结构变了或撞上验证页就返回空列表，
    由上层静默降级，不会抛出去。
    """
    if max_results <= 0:
        return []
    try:
        url = "https://%s/search?q=%s" % (host, urllib.parse.quote(query))
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA_DESKTOP,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            final_url = resp.geturl()
            content = resp.read().decode("utf-8", "replace")
    except Exception:
        return []
    if _looks_blocked(content, final_url):
        return []

    results = []
    for block in re.findall(r'<li class="b_algo".*?</li>', content, re.DOTALL):
        if len(results) >= max_results:
            break
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        if not title_match:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(2))).strip()
        if not title:
            continue
        snippet = ""
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
        if snippet_match:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1)))
            snippet = " ".join(snippet.split())
        results.append({
            "title": title,
            "snippet": snippet,
            "url": title_match.group(1),
        })
    return results


def _bing_cn_search(query: str, max_results: int = 5) -> list:
    """境内直连的 Bing 加速域名，主源（实测 0.23s / 10 条）。"""
    return _bing_search(query, max_results, "cn.bing.com")


def _bing_intl_search(query: str, max_results: int = 5) -> list:
    """Bing 国际站，接替 DuckDuckGo 原来的兜底位。

    换域名比换引擎划算：结果结构一模一样，解析器直接复用，不用再维护第二个解析器。
    实测国际站 0.44s / 10 条，可直连 —— 如果只是 cn.bing.com 这个域名被挡，它能顶上。
    """
    return _bing_search(query, max_results, "www.bing.com")


def _sogou_search(query: str, max_results: int = 5) -> list:
    """搜狗网页搜索（免 Key，国内第二源）。

    按 `<h3>` 切块：每块里头一个 `<a>` 是标题与链接，紧随的 space-txt 是摘要。
    不用「整块匹配 <div class="vrwrap">」是因为那个 div 是嵌套的，非贪婪匹配
    容易截在半路；按 h3 切则天然对齐一条结果。
    """
    if max_results <= 0:
        return []
    try:
        url = "https://www.sogou.com/web?query=%s" % urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA_DESKTOP,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            final_url = resp.geturl()
            content = resp.read().decode("utf-8", "replace")
    except Exception:
        return []
    if _looks_blocked(content, final_url):
        return []

    results = []
    for chunk in re.split(r"<h3", content)[1:]:
        if len(results) >= max_results:
            break
        link = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.DOTALL)
        if not link:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip()
        if not title or any(n in title for n in _SOGOU_NOISE):
            continue
        snippet = ""
        snip = re.search(
            r'class="[^"]*(?:space-txt|text-layout)[^"]*"[^>]*>(.*?)</div>',
            chunk, re.DOTALL)
        if snip:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snip.group(1)))
            snippet = " ".join(snippet.split())
        results.append({
            "title": title,
            "snippet": snippet,
            "url": link.group(1),
        })
    return results


def _summarize_results(results: list, query: str) -> str:
    """把搜索结果压缩为简洁的注入文本。

    只保留**带摘要**的结果：解析出来的条目可能全是光秃秃的标题（反爬拦截页的
    残留、或结果结构变了只抓到 h3），那种注入等于告诉模型「我查到了」却什么
    都没给 —— 比空字符串更坏，因为调用方的 `or no_result_notice()` 兜不住它。
    一条摘要都没有时返回空字符串，交给上层走「没查到」的分支。
    """
    if not results:
        return ""

    lines = []
    for r in results[:4]:
        snippet = " ".join((r.get("snippet") or "").split())[:120]
        if not snippet:
            continue
        title = (r.get("title") or "").strip()[:40]
        lines.append("%d. %s: %s" % (len(lines) + 1, title, snippet))

    if not lines:
        return ""

    text = "【实时搜索: %s】\n%s" % (query, "\n".join(lines))
    if len(text) > 500:
        text = text[:497] + "..."

    return text
