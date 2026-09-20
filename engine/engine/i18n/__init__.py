# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""i18n 支持 — 多语言文本映射。

译文数据在同目录的 `strings.json`（结构：`{语言代码: {key: 译文}}`），
本文件只放逻辑：语言检测、fallback 链、维度名/相位名转换。

Go 侧 JSON 翻译键保持一致。
自动根据浏览器/环境检测语言。
"""

import json
import os


# ── 语言显示名 ──
_LANG_NAMES = {
    "zh": "简体中文",
    "zh_tw": "繁體中文",
    "en": "English",
    "ko": "한국어",
    "th": "ไทย",
    "ja": "日本語",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
    "de": "Deutsch",
    "ru": "Русский",
    "ar": "العربية",
    "hi": "हिन्दी",
}

_LANG_ORDER = ["zh", "zh_tw", "en", "ko", "th", "ja", "es", "fr", "pt", "de", "ru", "ar", "hi"]

# ── 方言 → 父语言 fallback ──
_LANG_PARENT = {
    "zh_tw": "zh",
}


def lang_names() -> dict:
    return dict(_LANG_NAMES)


def lang_order() -> list:
    return list(_LANG_ORDER)


# ── 翻译表（数据住在 strings.json，不住在代码里）──
# 1206 条译文曾让这个文件长到 1234 行，逻辑被压在末尾：改一句译文要翻过整个数据块，
# diff 里译文改动和逻辑改动也混在一起（review 时看不出哪边变了）。
# 拆出去之后，加语言 / 改译文只动 json，代码文件回到「只有逻辑」的体量。
_STRINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "strings.json")


def _load_strings(path=_STRINGS_PATH):
    """读 strings.json。

    缺失或损坏时返回 {}：这只影响译文，不该把引擎整个拖垮 ——
    t() 会逐级 fallback（指定语言 → 方言父语言 → en → zh），最后返回 key 本身，
    界面降级成 key 可见总好过启动失败。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_I18N = _load_strings()

_LANG = os.environ.get("AI_LANG", "zh")


def set_lang(lang: str):
    global _LANG
    _LANG = lang


def get_lang() -> str:
    return _LANG


def _http_accept_lang() -> str:
    """实时读取 HTTP Accept-Language 环境变量（每次调用检测，而非模块加载时缓存）"""
    return os.environ.get("HTTP_ACCEPT_LANGUAGE", "")


def detect(lang_str: str = None) -> str:
    """检测语言。支持: zh/zh_tw/en/ko/th/ja/es/fr/pt/de/ru/ar/hi"""
    s = (lang_str or _http_accept_lang() or _LANG).lower()
    for code, prefixes in {
        "zh_tw": ["zh_tw", "zh-tw", "zh_hant", "zh-hant", "cht", "chinese (traditional)"],
        "zh": ["zh", "chinese"],
        "en": ["en", "english"],
        "ko": ["ko", "korean", "한국"],
        "th": ["th", "thai", "ไทย"],
        "ja": ["ja", "japanese", "日本語"],
        "es": ["es", "spanish", "español"],
        "fr": ["fr", "french", "français"],
        "pt": ["pt", "portuguese", "português"],
        "de": ["de", "german", "deutsch"],
        "ru": ["ru", "russian", "русский"],
        "ar": ["ar", "arabic", "العربية"],
        "hi": ["hi", "hindi"],
    }.items():
        for p in prefixes:
            if s.startswith(p):
                return code
    return "zh"


def t(key: str, lang: str = None) -> str:
    """按 key 返回翻译文本。fallback 链: 指定语言 → (方言父语言) → 英文 → 中文 → key"""
    lang = lang or detect()
    table = _I18N.get(lang, {})
    val = table.get(key)
    if val is not None:
        return val
    # 方言 fallback：zh_tw → zh
    parent = _LANG_PARENT.get(lang)
    if parent:
        val = _I18N.get(parent, {}).get(key)
        if val is not None:
            return val
    if lang != "en":
        val = _I18N.get("en", {}).get(key)
        if val is not None:
            return val
    val = _I18N.get("zh", {}).get(key)
    if val is not None:
        return val
    return key


def mind_dim_name(dim: str, lang: str = None) -> str:
    """心智维度名 → 指定语言翻译"""
    return t(f"mind.{dim}", lang)


def phase_name(phase: str, lang: str = None) -> str:
    """生命相位名 → 指定语言翻译"""
    key_map = {
        "活跃": "life.phase_active", "发呆": "life.phase_zoning",
        "疲惫": "life.phase_tired", "独处": "life.phase_alone",
        "emo": "life.phase_emo", "自愈": "life.phase_heal",
    }
    key = key_map.get(phase)
    if key:
        return t(key, lang)
    return phase
