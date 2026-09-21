# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
AI 对话客户端

走 OpenAI 兼容协议（/v1/chat/completions，事实标准），因此任意兼容厂商都能直接用：
  OpenAI / DeepSeek / Kimi(月之暗面) / 智谱GLM / 通义千问 / 豆包(火山) /
  硅基流动 / OpenRouter / Groq / Together / Fireworks / Mistral / xAI，
  以及本地 Ollama / vLLM / LM Studio / llama.cpp。

换厂商只需改三个值：api_key + api_base + model。
也可以在 config.json 里填 ai.provider（见下方 PROVIDERS 预设表）让引擎自动补全。
"""
import json
import threading
import time
from openai import OpenAI

_client: OpenAI = None
_model: str = ""
_config: dict = {}

# ── 内置厂商预设：config.json 填 ai.provider 即自动补全 api_base / model ──
# 只补「用户没显式填」的字段，显式填写的值永远优先。
PROVIDERS = {
    # 国际
    "openai":      {"api_base": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini"},
    "openrouter":  {"api_base": "https://openrouter.ai/api/v1",
                    "model": "openai/gpt-4o-mini"},
    "groq":        {"api_base": "https://api.groq.com/openai/v1",
                    "model": "llama-3.3-70b-versatile"},
    "together":    {"api_base": "https://api.together.xyz/v1",
                    "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
    "fireworks":   {"api_base": "https://api.fireworks.ai/inference/v1",
                    "model": "accounts/fireworks/models/llama-v3p3-70b-instruct"},
    "mistral":     {"api_base": "https://api.mistral.ai/v1",
                    "model": "mistral-large-latest"},
    "xai":         {"api_base": "https://api.x.ai/v1",
                    "model": "grok-2-latest"},
    # 国内
    "deepseek":    {"api_base": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat", "background_model": "deepseek-chat"},
    "moonshot":    {"api_base": "https://api.moonshot.cn/v1",
                    "model": "moonshot-v1-8k"},
    "zhipu":       {"api_base": "https://open.bigmodel.cn/api/paas/v4",
                    "model": "glm-4-flash"},
    "dashscope":   {"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "model": "qwen-plus"},
    "volces":      {"api_base": "https://ark.cn-beijing.volces.com/api/v3",
                    "model": "doubao-pro-32k"},
    "siliconflow": {"api_base": "https://api.siliconflow.cn/v1",
                    "model": "Qwen/Qwen2.5-7B-Instruct"},
    # 本地（多数本地服务不校验 key，随便填个非空值即可）
    "ollama":      {"api_base": "http://localhost:11434/v1",
                    "model": "qwen2.5", "api_key": "ollama"},
    "vllm":        {"api_base": "http://localhost:8000/v1",
                    "model": "local-model", "api_key": "vllm"},
    "lmstudio":    {"api_base": "http://localhost:1234/v1",
                    "model": "local-model", "api_key": "lm-studio"},
    "llamacpp":    {"api_base": "http://localhost:8080/v1",
                    "model": "local-model", "api_key": "llama-cpp"},
}

# 明显还是占位符的 key（防止照抄模板后一直在报 401）
_PLACEHOLDER_HINTS = ("你的", "填入", "your", "YOUR", "xxxx", "在这里", "sk-xxx")


# ══════════════════════════════════════════════════════════════════════
# 后端熔断器 — BackendBreaker
# ══════════════════════════════════════════════════════════════════════
# 为什么必须在这一层做：模型接口挂掉（key 失效 / 额度耗尽）时，会继续打接口的
# 后台调用方远不止「自主思考引擎」一个。core/scheduler.py 注册的 5 个任务是
# 各自独立跑的（life_engine 每 1s、ferment_release 每 5s、reflection、
# persona_analysis），它们内部触发的九重矛盾博弈、记忆复盘等同样会调 LLM，
# 而 stop_thought_engine() 只清了 autonomous 自己的一个标志，管不到它们。
# 于是出现「一边打印『已暂停自主思考引擎，避免无意义调用与日志刷屏』，
# 一边继续刷 401」——承诺没兑现。
#
# 这里在三个 LLM 入口做全局收口：
#   · background_chat，以及「后台上下文」里发起的 chat / chat_stream → 熔断后直接短路，
#     不浪费额度、不刷日志
#   · 前台 chat（用户可见的那一轮）→ 照常尝试，保住 silent / backend_error 的归因，
#     不会被误判成「人格沉默」
# 修好接口后调用 reload_ai() 即可就地复位，无需重启服务。
_BREAKER_LOCK = threading.Lock()
_BREAKER = {"tripped": False, "reason": "", "since": 0.0, "suppressed": 0}
_BREAKER_WARN_EVERY = 500

# 认证 / 额度 / 封号类错误：重试不会自愈，命中即熔断（不必等失败阈值）
_FATAL_BREAKER_MARKERS = (
    "Authentication Fails", "invalid_api_key", "authentication_error",
    "Insufficient Balance", "insufficient_quota", "account_deactivated",
    "Error code: 401", "Error code: 403",
)

# 日志去重：同一个失败在窗口内只打一条，避免接口挂掉时刷爆日志
_FAIL_LOG_INTERVAL = 300.0
_LAST_FAIL = {"msg": "", "at": 0.0, "repeat": 0}

# 后台上下文标记（thread-local）：由 core/scheduler.py 在执行任务期间打开
_CTX = threading.local()


def in_background_context() -> bool:
    """当前是否处于后台任务上下文（调度器任务内部）。"""
    return bool(getattr(_CTX, "background", False))


class background_context:
    """with background_context(): ... —— 期间发起的 chat() 视为后台调用。

    后台调用在熔断后会被短路；前台调用永远照常尝试，以便
    engine_bridge 仍能把「没回复」归因为 backend_error 而不是人格沉默。
    """

    def __enter__(self):
        self._prev = getattr(_CTX, "background", False)
        _CTX.background = True
        return self

    def __exit__(self, *exc):
        _CTX.background = self._prev
        return False


def backend_breaker() -> dict:
    """当前熔断状态（供 /health、doctor 展示与排障）。"""
    with _BREAKER_LOCK:
        return {"tripped": _BREAKER["tripped"], "reason": _BREAKER["reason"],
                "since": _BREAKER["since"], "suppressed": _BREAKER["suppressed"]}


def reset_backend_breaker() -> bool:
    """解除熔断，返回此前是否处于熔断。修好 key 后由 reload_ai() 调用。"""
    with _BREAKER_LOCK:
        was = _BREAKER["tripped"]
        _BREAKER.update({"tripped": False, "reason": "", "since": 0.0,
                         "suppressed": 0})
    if was:
        print("[AI] 熔断已解除，后台调用恢复")
    return was


def _trip_backend_breaker(exc) -> bool:
    """命中致命错误则熔断；首命中时打一条，之后不再刷屏。"""
    msg = str(exc)
    if not any(m in msg for m in _FATAL_BREAKER_MARKERS):
        return False
    with _BREAKER_LOCK:
        first = not _BREAKER["tripped"]
        _BREAKER.update({"tripped": True, "reason": msg[-300:],
                         "since": time.time()})
    if first:
        print("[AI] ⛔ 模型接口认证/额度不可用，已熔断全部后台调用"
              "（服务保持存活，前台对话仍会尝试以便归因）；"
              "修好 ai.api_key / ai.model 后跑 `soulviaictl reload-ai` 就地恢复。"
              "原因: %s" % msg)
    return True


def _breaker_blocks_background() -> bool:
    """后台调用是否应被熔断挡下（计数被抑制的调用，周期性提示一次）。"""
    with _BREAKER_LOCK:
        if not _BREAKER["tripped"]:
            return False
        _BREAKER["suppressed"] += 1
        n = _BREAKER["suppressed"]
    if n % _BREAKER_WARN_EVERY == 0:
        print("[AI] 熔断中：已抑制 %d 次后台调用（修好接口后自动恢复）" % n)
    return True


def _log_failure(tag: str, exc) -> None:
    """同一个失败在 _FAIL_LOG_INTERVAL 内只输出一条（附重复计数）。"""
    msg = str(exc)
    now = time.time()
    with _BREAKER_LOCK:
        if (msg == _LAST_FAIL["msg"]
                and now - _LAST_FAIL["at"] < _FAIL_LOG_INTERVAL):
            _LAST_FAIL["repeat"] += 1
            return
        repeat = _LAST_FAIL["repeat"] if _LAST_FAIL["msg"] else 0
        _LAST_FAIL.update({"msg": msg, "at": now, "repeat": 0})
    line = "%s: %s" % (tag, msg)
    if repeat:
        line += "（同类错误此前已重复 %d 次）" % repeat
    print(line)


def load_config(config_path: str = "config.json"):
    """加载 AI 配置（优先使用共享配置模块，确保 .env 覆盖生效）"""
    global _config
    try:
        from core import config as shared_cfg
        shared_cfg.load(config_path)
        _config = dict(shared_cfg.get_section("ai"))
    except Exception:
        # 回退：直接读取 config.json
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        _config = dict(cfg.get("ai", {}))

    _finalize_config()


def _finalize_config():
    """套用厂商预设并固定模型名（load_config 与 reload_ai 共用）。"""
    global _model
    _apply_provider_preset()
    _model = _config.get("model", "") or ""
    if not _model:
        print("[AI] 警告: 未配置模型名（config.json 的 ai.model，或环境变量 AI_MODEL）")


def reload_ai(config_path: str = "config.json") -> dict:
    """重新读取 .env / config.json 并重建客户端，不用重启进程。

    常驻服务里改了模型接口（换厂商、换 key、补上缺失的 key）之后必须调它 ——
    core/config.py 的 load() 只跑一次，否则进程里一直是启动时那份配置。
    云端「部署时注入环境变量」的场景同理：注入后调一次即可当场生效。

    失败时保留旧客户端：常驻服务不该因为 .env 里一个拼写错误就整个哑掉，
    自主思考引擎还挂着它。返回值里会说明到底成没成。

    返回 dict: {ok, detail, config_source, provider, model, api_base,
                 retained_previous}
    """
    global _config, _model, _client
    old = (_config, _model, _client)
    source = config_path

    try:
        from core import config as shared_cfg
        shared_cfg.reload(config_path)
        _config = dict(shared_cfg.get_section("ai"))
        source = shared_cfg.dotenv_path() or config_path
    except Exception as exc:
        return {"ok": False, "detail": "重新读取配置失败: %s: %s"
                                       % (type(exc).__name__, exc),
                "config_source": source, "retained_previous": True}

    _finalize_config()

    # 先丢弃旧客户端，再重新初始化：避免换了 key 还在复用旧连接池
    _client = None
    if not init_client():
        _config, _model, _client = old
        return {"ok": False, "detail": "新配置不可用（缺少 api_key 或仍是占位符），"
                                       "已保留原有客户端",
                "config_source": source, "retained_previous": True}

    # 配置重载成功 = 接口可能已修好，就地解除熔断，不必重启服务
    reset_backend_breaker()

    return {"ok": True, "detail": "模型接口已重新加载",
            "config_source": source,
            "provider": _config.get("provider") or "",
            "model": _model,
            "api_base": _config.get("api_base") or ""}


def _apply_provider_preset():
    """按 ai.provider 补全 api_base / model / background_model。

    只在两种情况覆盖：字段为空，或该字段是由旧版 DEEPSEEK_* 变量兜底填的 ——
    这样「从 DeepSeek 换到别的厂商」不会因为 .env 里的残留旧值而连错地址。
    用户显式写在 config.json 或 AI_* 环境变量里的值永远优先。
    """
    name = (_config.get("provider") or "").strip().lower()
    if not name:
        return
    preset = PROVIDERS.get(name)
    if not preset:
        print("[AI] 警告: 未知的 ai.provider=%r。可用值: %s"
              % (name, ", ".join(sorted(PROVIDERS))))
        return
    legacy = set(_config.get("_legacy_env_fields") or [])
    for k, v in preset.items():
        if not _config.get(k) or k in legacy:
            _config[k] = v


def init_client():
    """初始化 AI 客户端（OpenAI 兼容协议）"""
    global _client
    api_key = _config.get("api_key", "") or ""
    api_base = _config.get("api_base", "") or ""

    if not api_key:
        print("[AI] 警告: 未配置 API Key。请在 engine/.env 或 config.json 的 ai.api_key 设置"
              "（支持任意 OpenAI 兼容厂商；本地 Ollama/vLLM 可随便填一个非空值）")
        return False

    if any(h in api_key for h in _PLACEHOLDER_HINTS):
        print("[AI] 警告: API Key 看起来还是占位符（%s…），请填入真实密钥" % api_key[:14])
        return False

    kwargs = {"api_key": api_key}
    if api_base:
        kwargs["base_url"] = api_base
    _client = OpenAI(**kwargs)

    print("[AI] 已接入: provider=%s model=%s base=%s"
          % (_config.get("provider") or "custom",
             _model or _config.get("model") or "(未设置)",
             api_base or "(OpenAI SDK 默认)"))
    return True


def chat(system_prompt: str, user_message: str, temperature: float = None,
          conversation_history: list = None) -> str:
    """发送对话请求，返回 AI 回复文本
    conversation_history: 可选 [(role, content), ...] 列表，注入 messages 数组
                          作为多轮对话上下文，让 LLM 知道之前说了什么
    """
    if _client is None:
        return "（AI 未初始化，请检查 API Key 配置）"

    # 后台上下文 + 已熔断 → 直接放弃；前台调用不受影响
    if in_background_context() and _breaker_blocks_background():
        return ""

    temp = temperature if temperature is not None else _config.get("temperature", 0.85)
    max_tokens = _config.get("max_tokens", 1024)
    timeout = _config.get("timeout_seconds", 60)

    try:
        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for role, content in conversation_history:
                # 兜底：兼容历史上可能出现的 "ai" 角色名
                safe_role = "assistant" if role == "ai" else role
                messages.append({"role": safe_role, "content": content})

        messages.append({"role": "user", "content": user_message})

        response = _client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temp,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        _trip_backend_breaker(e)
        _log_failure("[AI] API 调用失败", e)
        return ""


def chat_stream(system_prompt: str, user_message: str, temperature: float = None,
                 conversation_history: list = None):
    """流式对话请求，yield 文本片段
    conversation_history: 可选 [(role, content), ...] 列表，注入 messages 数组
    """
    if _client is None:
        return

    # 后台上下文 + 已熔断 → 直接放弃；前台调用不受影响
    if in_background_context() and _breaker_blocks_background():
        return

    temp = temperature if temperature is not None else _config.get("temperature", 0.85)
    max_tokens = _config.get("max_tokens", 1024)
    timeout = _config.get("timeout_seconds", 60)

    try:
        messages = [{"role": "system", "content": system_prompt}]

        if conversation_history:
            for role, content in conversation_history:
                # 兜底：兼容历史上可能出现的 "ai" 角色名
                safe_role = "assistant" if role == "ai" else role
                messages.append({"role": safe_role, "content": content})

        messages.append({"role": "user", "content": user_message})

        stream = _client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temp,
            max_tokens=max_tokens,
            timeout=timeout,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        _trip_backend_breaker(e)
        _log_failure("[AI] 流式调用失败", e)
        return


def background_chat(prompt: str, temperature: float = 0.9, max_tokens: int = 80) -> str:
    """轻量后台推理 — 用便宜的 background_model 生成内心意识流。
    不阻塞主对话线程，成本极低（~$0.00001/次）。
    返回空字符串 = 失败/不可用。
    """
    if _client is None:
        return ""

    # 熔断中 → 后台调用直接短路：不浪费额度，也不再刷日志
    if _breaker_blocks_background():
        return ""

    bg_model = _config.get("background_model") or _model
    if not bg_model:
        return ""
    timeout = _config.get("timeout_seconds", 60)

    try:
        response = _client.chat.completions.create(
            model=bg_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        text = response.choices[0].message.content.strip()
        return text[:200]
    except Exception as e:
        _trip_backend_breaker(e)
        _log_failure("[AI·后台] background_chat 失败", e)
        return ""
