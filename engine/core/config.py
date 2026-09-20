# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""共享配置加载器
统一从 config.json 读取，供各模块使用
支持 .env 环境变量覆盖敏感配置（API Key 等）
"""
import json
import os
import threading

_data: dict = {}
_lock = threading.Lock()
_loaded = False

# reload() 用：记住「.env 到底往 os.environ 里塞了什么」。
# python-dotenv 默认不覆盖已存在的变量，上一次加载留下的旧值会把新写的值
# 挡在外面 —— 所以回滚时必须逐个还原，否则改了 .env 也不会生效。
_env_baseline: dict = None      # 首次加载 .env 之前的 os.environ 快照
_env_injected: dict = {}        # {变量名: .env 写入的值}，回滚时只动这些
_dotenv_path: str = ""          # 实际加载到的 .env 路径


def _load_dotenv():
    """加载 .env 文件（优先于 config.json 的敏感字段）

    顺带记下本次到底注入了哪些变量，供 reload() 回滚。
    """
    global _env_baseline, _env_injected, _dotenv_path
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[Config] python-dotenv 未安装，跳过 .env 加载")
        return ""

    if _env_baseline is None:
        _env_baseline = dict(os.environ)

    env_paths = [
        ".env",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
    ]
    for p in env_paths:
        if not os.path.exists(p):
            continue
        before = dict(os.environ)
        # override 保持默认 False：真实注入的环境变量永远优先于 .env 文件
        load_dotenv(p)
        _env_injected = {k: v for k, v in os.environ.items() if before.get(k) != v}
        _dotenv_path = os.path.abspath(p)
        return _dotenv_path

    _env_injected = {}
    _dotenv_path = ""
    return ""


def _rollback_dotenv():
    """撤销上一次 .env 注入，把 os.environ 还原到外部环境原貌。

    只动「.env 引入的」变量：平台/用户显式注入的环境变量原样保留。

    还要比对值有没有被动过 —— 如果某个变量在 .env 加载之后又被平台或运行期
    代码改写了，那它已经不归 .env 管，回滚时跳过，否则会把别人设的值抹掉。
    """
    global _env_injected
    for k, injected_value in _env_injected.items():
        if os.environ.get(k) != injected_value:
            continue
        if _env_baseline is not None and k in _env_baseline:
            os.environ[k] = _env_baseline[k]
        else:
            os.environ.pop(k, None)
    _env_injected = {}


def _read_config(config_path: str) -> dict:
    """读一次 .env + config.json 并套用环境变量覆盖，返回新配置。

    只返回、不碰全局 —— 由调用方原子替换，避免 reload 期间其它线程读到空配置。
    """
    _load_dotenv()
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 用环境变量覆盖敏感配置字段
    _apply_env_overrides(data)
    return data


def load(config_path: str = "config.json"):
    """加载配置文件（线程安全，仅加载一次）"""
    global _data, _loaded
    with _lock:
        if _loaded:
            return
        _data = _read_config(config_path)
        _loaded = True


def reload(config_path: str = "config.json"):
    """重新读取 .env 与 config.json，让改动在运行中的进程里生效。

    load() 只跑一次（_loaded 为 True 就直接返回），所以常驻服务改了 .env
    之后必须显式调这个 —— 否则进程里一直是启动时那份配置，
    表现出来就是「配置明明改了，服务照样报 401」。

    这里的回滚不是可选项：.env 在上一次加载时已经把值写进了 os.environ，
    python-dotenv 默认不覆盖，不回滚的话新值永远读不进来。
    """
    global _data, _loaded
    with _lock:
        _rollback_dotenv()
        _data = _read_config(config_path)
        _loaded = True


def dotenv_path() -> str:
    """实际生效的 .env 路径；没有则为空串（供 reload 结果回显）。"""
    return _dotenv_path


# ── 模型接口环境变量（按优先级从高到低，首个命中的生效）──
# 引擎走 OpenAI 兼容协议，因此任意兼容厂商（OpenAI / DeepSeek / Kimi / GLM /
# 通义 / 豆包 / 硅基流动 / OpenRouter / Groq / Ollama / vLLM ...）都能直接用，
# 只需换 api_key + api_base + model 三个值。
# 通用名 AI_* 优先，其次 OpenAI SDK 惯例名，最后保留 DEEPSEEK_* 以兼容旧配置。
_AI_KEY_ENVS = ("AI_API_KEY", "OPENAI_API_KEY")
_AI_BASE_ENVS = ("AI_API_BASE", "AI_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE")
_AI_MODEL_ENVS = ("AI_MODEL", "OPENAI_MODEL")
_AI_BG_MODEL_ENVS = ("AI_BACKGROUND_MODEL",)
# 厂商预设名（填了会按 core/ai.py 的 PROVIDERS 自动补全 api_base / model）
_AI_PROVIDER_ENVS = ("AI_PROVIDER", "LLM_PROVIDER")
# 旧版变量名（最低优先级）。注意：当 AI_PROVIDER 生效时，这些字段允许被预设覆盖，
# 否则会出现「换成了 moonshot 但 base_url 还停在 deepseek」这种隐蔽错配。
_LEGACY_KEY_ENVS = ("DEEPSEEK_API_KEY",)
_LEGACY_BASE_ENVS = ("DEEPSEEK_API_BASE",)
_LEGACY_MODEL_ENVS = ("DEEPSEEK_MODEL",)
_LEGACY_BG_MODEL_ENVS = ("DEEPSEEK_BACKGROUND_MODEL",)
# 记录哪些字段由旧版变量填充，供 core/ai.py 的 provider 预设判断可否覆盖
_LEGACY_MARK = "_legacy_env_fields"


def _first_env(names):
    """返回 names 中第一个已设置且非空的环境变量值。"""
    for n in names:
        v = os.getenv(n)
        if v and v.strip():
            return v.strip()
    return ""


def _apply_env_overrides(data: dict):
    """把环境变量注入配置。

    优先级（高 → 低）：
      1. 通用环境变量 AI_* / OPENAI_*
      2. 厂商预设（AI_PROVIDER → core/ai.py 的 PROVIDERS）
      3. 旧版环境变量 DEEPSEEK_*
      4. config.json 里显式写的值

    这也是「云端不填 key」的那条路：平台注入 AI_API_KEY/AI_API_BASE/AI_MODEL
    即可，配置文件里什么都不用写。
    """
    ai_cfg = data.setdefault("ai", {})

    provider = _first_env(_AI_PROVIDER_ENVS)
    if provider:
        ai_cfg["provider"] = provider

    # ① 通用环境变量
    for envs, key in ((_AI_KEY_ENVS, "api_key"),
                      (_AI_BASE_ENVS, "api_base"),
                      (_AI_MODEL_ENVS, "model")):
        v = _first_env(envs)
        if v:
            ai_cfg[key] = v
    bg = _first_env(_AI_BG_MODEL_ENVS)
    if bg:
        ai_cfg["background_model"] = bg

    # ② 旧版变量兜底，并记录来源（provider 预设可覆盖这些来源的字段）
    legacy = []
    for envs, key in ((_LEGACY_KEY_ENVS, "api_key"),
                      (_LEGACY_BASE_ENVS, "api_base"),
                      (_LEGACY_MODEL_ENVS, "model")):
        if not ai_cfg.get(key):
            v = _first_env(envs)
            if v:
                ai_cfg[key] = v
                legacy.append(key)
    if not ai_cfg.get("background_model"):
        v = _first_env(_LEGACY_BG_MODEL_ENVS)
        if v:
            ai_cfg["background_model"] = v
            legacy.append("background_model")
    if legacy:
        ai_cfg[_LEGACY_MARK] = legacy

    wx_cfg = data.get("wx_bot", {})
    if os.getenv("WX_BOT_TOKEN"):
        wx_cfg["bot_token"] = os.getenv("WX_BOT_TOKEN")
    if os.getenv("WX_ILINK_BOT_ID"):
        wx_cfg["ilink_bot_id"] = os.getenv("WX_ILINK_BOT_ID")
    if os.getenv("WX_ILINK_USER_ID"):
        wx_cfg["ilink_user_id"] = os.getenv("WX_ILINK_USER_ID")

    qq_cfg = data.get("qq_bot", {})
    if os.getenv("QQ_APP_ID"):
        qq_cfg["app_id"] = os.getenv("QQ_APP_ID")
    if os.getenv("QQ_CLIENT_SECRET"):
        qq_cfg["client_secret"] = os.getenv("QQ_CLIENT_SECRET")

    # 天气无需密钥：由调用方通过 `chat --env "上海 小雨 24°C"` 注入，
    # 见 engine/social/sensors.py 的 set_external_context()。


def get(section: str, key: str, default=None):
    """读取指定 section 下的 key"""
    if not _loaded:
        load()
    return _data.get(section, {}).get(key, default)


def get_section(section: str) -> dict:
    """读取整个 section，如果是空字符串则返回整个配置"""
    if not _loaded:
        load()
    if section == "":
        return _data
    return _data.get(section, {})
