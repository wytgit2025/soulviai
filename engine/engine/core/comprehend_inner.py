# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""
Phase 1+2 合并优化 — 理解层+内心OS二合一
将原两次 LLM 调用合并为一次，降低约50%延迟。
同时输出结构化理解 + 内心独白。

设计权衡：
- 温度取值 0.7（介于理解层 0.3 和内心OS 0.9 之间）
- 理解精度略有损失，但通过 JSON parsing + fallback 保障稳定性
- 内心OS 创造性略有降低，但可接受
"""
import json
import re
import hashlib
import functools
import time
from core import ai as ai_module

# ── 理解缓存 ──
_COMPREHEND_CACHE = {}
_CACHE_TTL = 60  # 缓存有效期60秒
_CACHE_MAX_SIZE = 50


def _get_cache_key(user_message: str, context_hash: str = "") -> str:
    """生成缓存key：基于消息内容+上下文哈希"""
    raw = f"{user_message}|{context_hash}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> tuple:
    """从缓存读取，过期则返回None"""
    entry = _COMPREHEND_CACHE.get(key)
    if not entry:
        return None
    if time.time() - entry["time"] > _CACHE_TTL:
        del _COMPREHEND_CACHE[key]
        return None
    return entry["value"]


def _cache_set(key: str, value: tuple):
    """写入缓存，超限时淘汰最旧的"""
    if len(_COMPREHEND_CACHE) >= _CACHE_MAX_SIZE:
        oldest = min(_COMPREHEND_CACHE.keys(),
                     key=lambda k: _COMPREHEND_CACHE[k]["time"])
        del _COMPREHEND_CACHE[oldest]
    _COMPREHEND_CACHE[key] = {"value": value, "time": time.time()}

# ── 合并版 Prompt（一次输出两部分） ──
_COMBINED_PROMPT = """你是「深度理解+内心独白」双模块协同分析器。
分析用户消息，同时输出两部分内容。

【输出格式】严格按以下分隔线产出：

---COMPREHEND---
{"intent":"闲聊/倾诉/求助/提问/撒娇/敷衍/试探/分享",
 "surface_emotion":"开心/难过/生气/平静/焦虑/兴奋/无所谓",
 "true_emotion":"真实情绪（可能与字面不同）",
 "what_they_need":"倾听/安慰/建议/陪伴/空间/认同/幽默缓解",
 "need_search":true/false,
 "search_query":"中文关键词15字内，不需要则为空",
 "memory_keys":["关键词1","关键词2"],
 "depth":"浅聊/中度/深度",
 "confidence":0.0~1.0}

---INNER_OS---
（第一人称内心独白。不设防、不修饰、不克制。委屈就说委屈，想念就说想念。
一句话或一段话，50字以内。不要括号动作描写。）

规则：
- "我没事"+"最近都好"+"随便"连续出现 = 隐忍/赌气
- 对方倾诉心事 → need=倾听
- 仅明确事实问题才 need_search=true
- 内心OS可以矛盾："好想ta…但也好气"
- 内心OS可以有傲娇、嘴硬、脆弱"""
def load_engine_config():
    pass


def comprehend_and_os(user_message: str,
                      recent_context: list = None,
                      mind_state: str = "",
                      memory_context: str = "",
                      comprehension_only: bool = False) -> tuple:
    """合并理解层+内心OS：一次LLM调用产出两个结果。
    
    返回: (comprehension_dict, inner_os_text)
    
    如果 comprehension_only=True，跳过内心OS（用于缓存命中场景）。
    """# 缓存查找
    context_parts = []
    if recent_context:
        context_parts.append("|".join(recent_context[-2:]))
    ctx_hash = hashlib.md5("|".join(context_parts).encode("utf-8")).hexdigest()[:8] if context_parts else ""
    cache_key = _get_cache_key(user_message, ctx_hash)
    cached = _cache_get(cache_key)
    if cached and comprehension_only:
        return cached

    # 构建输入上下文
    context_lines = []
    if recent_context and len(recent_context) >= 1:
        context_lines.append("【最近对话】")
        for i, msg in enumerate(recent_context[-3:]):
            context_lines.append(f"对方: {msg}")
        context_lines.append("")

    # 心智状态注入（影响内心OS方向）
    if mind_state:
        context_lines.append(f"【你的状态】{mind_state}")

    # 记忆上下文注入
    if memory_context and "暂无" not in memory_context:
        mem_short = memory_context.replace("\n", " ")[:100]
        context_lines.append(f"【想起来的事】{mem_short}")

    context_lines.append(f"\n【当前消息】\n对方: {user_message}")

    user_prompt = "\n".join(context_lines)

    # 如果只需要理解（缓存命中时），用低温度快速理解
    if comprehension_only:
        # 使用简化的理解 Prompt
        temp_system = _COMBINED_PROMPT.split("---INNER_OS---")[0].strip()
        try:
            raw = ai_module.chat(temp_system, user_prompt, temperature=0.3)
            comp = _parse_comprehension(raw)
            if comp:
                return comp, ""
        except Exception:
            pass
        return _fallback_comprehension(user_message), ""

    # 正常模式：一次调用，双输出
    try:
        raw_response = ai_module.chat(
            system_prompt=_COMBINED_PROMPT,
            user_message=user_prompt,
            temperature=0.7,  # 折中温度
        )

        comp = _parse_comprehension(raw_response)
        ios = _parse_inner_os(raw_response)

        if comp is None:
            comp = _fallback_comprehension(user_message)

        # 写入缓存
        if comp.get("confidence", 0) > 0.4:
            _cache_set(cache_key, (comp, ios))

        return comp, ios

    except Exception as e:
        print(f"[合并层] LLM调用失败: {e}")
        return _fallback_comprehension(user_message), ""


def _parse_comprehension(raw: str) -> dict:
    """从合并输出中提取理解JSON"""# 先找 ---COMPREHEND--- 分隔符
    comp_match = re.search(r'---COMPREHEND---\s*\n?(\{.*?\})', raw, re.DOTALL | re.IGNORECASE)
    if comp_match:
        try:
            data = json.loads(comp_match.group(1))
            return _normalize_comprehension(data)
        except (json.JSONDecodeError, TypeError):
            pass

    # 回退：直接找JSON块
    json_match = re.search(r'\{[^{}]*("intent"|"true_emotion")[^{}]*\}', raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            return _normalize_comprehension(data)
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _parse_inner_os(raw: str) -> str:
    """从合并输出中提取内心OS"""# 找 ---INNER_OS--- 分隔符
    ios_match = re.search(r'---INNER_OS---\s*\n?(.*?)(?:$|---)', raw, re.DOTALL | re.IGNORECASE)
    if ios_match:
        text = ios_match.group(1).strip()
        if text:
            return text[:100]

    # 回退：找完整的合并输出，尝试以分隔符分割
    # 如果找不到标记，说明LLM可能只输出了内心OS
    if "---COMPREHEND---" not in raw and len(raw.strip()) > 5:
        return raw.strip()[:100]

    return ""


def _normalize_comprehension(data: dict) -> dict:
    """标准化理解结果为统一格式"""
    return {
        "intent": data.get("intent", "闲聊"),
        "surface_emotion": data.get("surface_emotion", "中性"),
        "true_emotion": data.get("true_emotion", "中性"),
        "what_they_need": data.get("what_they_need", "陪伴"),
        "need_search": data.get("need_search", False),
        "search_query": data.get("search_query", ""),
        "memory_keys": data.get("memory_keys", []),
        "depth": data.get("depth", "中度"),
        "confidence": float(data.get("confidence", 0.5)),
    }


# ── LRU 缓存层：高频短消息缓存理解结果 ──

def _msg_key(msg: str) -> str:
    """生成消息哈希（归一化后）"""# 去空白、统一标点
    normalized = re.sub(r'\s+', '', msg.strip())
    # 截断防碰撞
    return hashlib.md5(normalized.encode()).hexdigest()


@functools.lru_cache(maxsize=128)
def _cached_short_comprehend(msg_hash: str) -> tuple:
    """不可缓存实际结果（因为上下文不同），这里只做占位。
    实际缓存逻辑在 comprehend_and_os 函数中处理。"""
    return None


# ── 简单意图规则引擎（跳过LLM的快速通道）──

_SHORTCUT_RULES = {
    "嗯": {"intent": "敷衍", "emotion": "平静", "need": "空间", "depth": "浅聊"},
    "好的": {"intent": "闲聊", "emotion": "中性", "need": "陪伴", "depth": "浅聊"},
    "好": {"intent": "敷衍", "emotion": "中性", "need": "空间", "depth": "浅聊"},
    "哈哈": {"intent": "分享", "emotion": "开心", "need": "陪伴", "depth": "浅聊"},
    "谢谢": {"intent": "闲聊", "emotion": "中性", "need": "陪伴", "depth": "浅聊"},
    "在吗": {"intent": "试探", "emotion": "中性", "need": "陪伴", "depth": "浅聊"},
    "晚安": {"intent": "闲聊", "emotion": "温柔", "need": "陪伴", "depth": "浅聊"},
    "早安": {"intent": "闲聊", "emotion": "温柔", "need": "陪伴", "depth": "浅聊"},
}


def shortcut_comprehend(msg: str):
    """快速通道：超短消息用规则引擎直接判定，跳过LLM。
    返回None表示需要走LLM完整理解。
    """
    msg = msg.strip()
    if len(msg) <= 3 and msg in _SHORTCUT_RULES:
        rule = _SHORTCUT_RULES[msg]
        return {
            "intent": rule["intent"],
            "surface_emotion": rule["emotion"],
            "true_emotion": rule["emotion"],
            "what_they_need": rule["need"],
            "need_search": False,
            "search_query": "",
            "memory_keys": [],
            "depth": rule["depth"],
            "confidence": 0.85,  # 规则匹配置信度高
        }
    return None


def _fallback_comprehension(user_message: str) -> dict:
    """回退理解方案：基于关键词规则
    （与 comprehend.py 原版保持一致）
    """
    msg = user_message.strip()

    if "?" in msg or "吗" in msg or "怎么" in msg or "什么" in msg:
        intent = "提问"
    elif len(msg) <= 3:
        intent = "敷衍"
    elif any(kw in msg for kw in ["烦", "累", "难过", "不开心", "emo"]):
        intent = "倾诉"
    elif any(kw in msg for kw in ["帮我", "怎么办", "建议", "你觉得"]):
        intent = "求助"
    elif any(kw in msg for kw in ["哈哈", "笑死", "好好笑", "逗"]):
        intent = "分享"
    else:
        intent = "闲聊"

    if any(kw in msg for kw in ["哈哈", "开心", "好棒", "太好", "nice"]):
        surface = "开心"
    elif any(kw in msg for kw in ["烦", "累", "难过", "不开心", "emo", "哭"]):
        surface = "难过"
    elif any(kw in msg for kw in ["生气", "火大", "气死", "无语"]):
        surface = "生气"
    else:
        surface = "平静"

    if intent == "倾诉":
        need = "倾听"
    elif intent == "求助":
        need = "建议"
    elif intent == "敷衍":
        need = "空间"
    else:
        need = "陪伴"

    need_search = intent == "提问" and len(msg) > 10

    words = re.findall(r'[\u4e00-\u9fff]{2,4}', msg)
    stopwords = {"什么", "怎么", "为什么", "是不是", "有没有", "能不能",
                 "这个", "那个", "可以", "不过", "还是", "如果", "因为", "所以"}
    memory_keys = [w for w in words if w not in stopwords][:3]

    return {
        "intent": intent,
        "surface_emotion": surface,
        "true_emotion": surface,
        "what_they_need": need,
        "need_search": need_search,
        "search_query": msg[:20] if need_search else "",
        "memory_keys": memory_keys,
        "depth": "中度",
        "confidence": 0.4,
    }
