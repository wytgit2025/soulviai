# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""授权校验（客户端）：启动校验 + 设备指纹 + 心跳续期 + 按订阅限制功能。

为什么需要
----------
引擎本身可以离线自洽运行（不需要联网也能跑），所以授权层不能变成硬依赖：
断网、服务端挂了、用户没买 —— 任何一种情况都不该让 ta 「开不了机」。
但又要能区分 free / pro，并在用户付费后立刻放开能力。

因此这里的策略是：
  1. 校验失败一律**降级**到 free，而不是报错退出；
  2. 结果落盘缓存（`data/license_session.json`），断网时按宽限期沿用上次结论；
  3. 是否真的阻断由 `license.enforce` 决定（off / soft / hard），默认 soft
     —— 只在界面上提示，不打断用户。

配置（engine/config.json）
---------------------------
    "license": {
      "key": "",                        # 授权码；留空 = free
      "api": "https://api.soulviai.com",  # 授权服务端地址
      "enforce": "soft",                # off / soft / hard
      "timeout_seconds": 5,
      "grace_hours": 72                 # 断网后沿用缓存的宽限期
    }

环境变量优先级更高（方便容器/云端注入，不用改配置文件）：
    SOUL_LICENSE_KEY / SOUL_LICENSE_API / SOUL_LICENSE_ENFORCE
    SOUL_NO_LICENSE=1   完全跳过授权（自用/调试）

用法
----
    from core import license as lic

    lic.init()                       # 启动时一次，会打印一行状态并起心跳
    if lic.ensure("platform.wx"):    # 功能门控
        run_wx()
    print(lic.describe())            # 人类可读的状态串

服务端接口（与 server_py/ 对齐）
-------------------------------
    GET /v1/license?key=&hwid=&version=&platform=&ping=&watermark=
"""

import hashlib
import json
import os
import platform as _platform
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# ────────────────────────────────────────────────────────────
# 常量
# ────────────────────────────────────────────────────────────
TIER_FREE = "free"
TIER_PRO = "pro"
TIER_LIFETIME = "lifetime"

_TIER_RANK = {TIER_FREE: 0, TIER_PRO: 1, TIER_LIFETIME: 2}

DEFAULT_API = "https://api.soulviai.com"
DEFAULT_TIMEOUT = 5.0
DEFAULT_GRACE_HOURS = 72

ENV_KEY = "SOUL_LICENSE_KEY"
ENV_API = "SOUL_LICENSE_API"
ENV_ENFORCE = "SOUL_LICENSE_ENFORCE"
ENV_SKIP = "SOUL_NO_LICENSE"

# ── 功能 → 所需等级（要调价/换免费范围，只改这张表）──
# 不在表里的功能一律放行：新增功能忘了登记不会把免费用户拦在门外。
FEATURE_TIERS = {
    "platform.cli": TIER_FREE,
    "platform.state": TIER_FREE,
    "platform.web": TIER_PRO,       # Web 终端
    "platform.wx": TIER_PRO,        # 微信 iLink Bot
    "platform.qq": TIER_PRO,        # QQ 官方 Bot
    "platform.tg": TIER_PRO,        # Telegram
    "platform.dc": TIER_PRO,        # Discord
    "platform.im": TIER_PRO,        # iMessage
    "engine.autonomous": TIER_PRO,  # 自主思考引擎
}

# ────────────────────────────────────────────────────────────
# 路径
# ────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_ROOT = os.path.dirname(_HERE)                      # engine/
SKILL_ROOT = os.path.dirname(RUNTIME_ROOT)                 # 技能根（可能不存在）
CONFIG_PATH = os.path.join(RUNTIME_ROOT, "config.json")
# 授权缓存是运行数据：跟着数据家目录走，不再写进代码树
from core.paths import data_root                           # noqa: E402

CACHE_PATH = os.path.join(data_root(), "license_session.json")

# ────────────────────────────────────────────────────────────
# 运行期状态
# ────────────────────────────────────────────────────────────
_state = {
    "tier": TIER_FREE,
    "valid": False,
    "reason": "not_checked",
    "source": "none",          # server / cache / default / disabled
    "expires_at": "",          # 服务端给的到期时间（字符串，仅展示）
    "session_expires": 0.0,    # 本地会话到期（epoch 秒，用于离线宽限）
    "activations_used": 0,
    "activations_max": 0,
    "checked_at": 0.0,
    "last_error": "",
}
_lock = threading.Lock()
_hb_thread = None
_hb_stop = threading.Event()
_initialized = False
_hwid_cache = ""
_description_shown = False


# ────────────────────────────────────────────────────────────
# 配置读写
# ────────────────────────────────────────────────────────────
def _read_config() -> dict:
    """读 engine/config.json（每次读盘，保证 activate() 写入后立刻生效）。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_config(data: dict) -> bool:
    """原子写回 config.json（先写临时文件再 replace，避免写坏用户配置）。"""
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        return True
    except Exception as exc:
        _state["last_error"] = str(exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _cfg() -> dict:
    """授权配置：config.json 的 license 段 + 环境变量覆盖。"""
    section = _read_config().get("license") or {}
    if not isinstance(section, dict):
        section = {}
    cfg = {
        "key": (section.get("key") or "").strip(),
        "api": (section.get("api") or DEFAULT_API).strip().rstrip("/"),
        "enforce": (section.get("enforce") or "soft").strip().lower(),
        "timeout": float(section.get("timeout_seconds") or DEFAULT_TIMEOUT),
        "grace_hours": float(section.get("grace_hours") or DEFAULT_GRACE_HOURS),
    }
    for env, field in ((ENV_KEY, "key"), (ENV_API, "api"), (ENV_ENFORCE, "enforce")):
        val = (os.environ.get(env) or "").strip()
        if val:
            cfg[field] = val
    cfg["api"] = cfg["api"].rstrip("/")
    if cfg["enforce"] not in ("off", "soft", "hard"):
        cfg["enforce"] = "soft"
    return cfg


def current_key() -> str:
    return _cfg()["key"]


def api_base() -> str:
    return _cfg()["api"]


def enforce_mode() -> str:
    """off=不校验 / soft=只提示 / hard=真拦截。"""
    if os.environ.get(ENV_SKIP):
        return "off"
    return _cfg()["enforce"]


def version() -> str:
    """技能根 VERSION 文件里的版本号；读不到给 0.0.0。"""
    try:
        with open(os.path.join(SKILL_ROOT, "VERSION"), "r", encoding="utf-8") as fh:
            return fh.read().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


# ────────────────────────────────────────────────────────────
# 设备指纹（HWID）
# ────────────────────────────────────────────────────────────
def _machine_id() -> str:
    """取本机稳定标识：硬件/系统级，重装 python 也不变。"""
    system = _platform.system()
    try:
        if system == "Darwin":
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5)
            for line in (out.stdout or "").splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        elif system == "Linux":
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        mid = fh.read().strip()
                    if mid:
                        return mid
        elif system == "Windows":
            import winreg  # type: ignore
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography") as reg:
                return str(winreg.QueryValueEx(reg, "MachineGuid")[0])
    except Exception:
        pass
    # 兜底：MAC 地址（改了网卡就会变，但总比没有强）
    import uuid
    return "%s-%s" % (uuid.getnode(), _platform.node())


def hwid() -> str:
    """32 位十六进制设备指纹（首次计算后缓存）。"""
    global _hwid_cache
    if _hwid_cache:
        return _hwid_cache
    raw = "%s|%s|%s" % (_platform.system(), _platform.machine(), _machine_id())
    _hwid_cache = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return _hwid_cache


def _watermark() -> str:
    """分发水印（构建时注入），随校验上报，便于事后追溯泄漏副本。"""
    try:
        from core import watermark
        return watermark.recipient() or ""
    except Exception:
        return ""


# ────────────────────────────────────────────────────────────
# 与服务端通信
# ────────────────────────────────────────────────────────────
def _get_json(url: str, timeout: float):
    """返回 (status_code, body_dict)；网络异常返回 (0, {})。"""
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "soul-skill/%s" % version())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            return exc.code, {}
    except Exception as exc:
        _state["last_error"] = str(exc)
        return 0, {}


def _apply_result(body: dict, source: str):
    """把服务端返回写进运行期状态。"""
    tier = (body.get("tier") or TIER_FREE).lower()
    if tier not in _TIER_RANK:
        tier = TIER_FREE
    ttl_hours = float(body.get("session_ttl_hours") or 0)
    with _lock:
        _state.update({
            "tier": tier if body.get("valid") else TIER_FREE,
            "valid": bool(body.get("valid")),
            "reason": body.get("reason") or ("ok" if body.get("valid") else "invalid"),
            "source": source,
            "expires_at": body.get("expires_at") or "",
            "session_expires": (time.time() + ttl_hours * 3600) if ttl_hours else 0.0,
            "activations_used": int(body.get("activations_used") or 0),
            "activations_max": int(body.get("activations_max") or 0),
            "checked_at": time.time(),
        })


def check(ping: int = 0, silent: bool = False) -> dict:
    """向服务端校验一次。

    ping=0 → 启动校验（服务端会据此绑定 HWID）
    ping=1 → 心跳（只续期，不新增激活数）

    返回状态字典；任何失败都不会抛异常。
    """
    cfg = _cfg()
    params = {
        "key": cfg["key"] or TIER_FREE,
        "hwid": hwid(),
        "version": version(),
        "platform": "%s-%s" % (_platform.system().lower(), _platform.machine().lower()),
        "ping": str(1 if ping else 0),
    }
    wm = _watermark()
    if wm:
        params["watermark"] = wm

    url = "%s/v1/license?%s" % (cfg["api"], urllib.parse.urlencode(params))
    code, body = _get_json(url, cfg["timeout"])

    if code == 200 and body:
        _apply_result(body, "server")
        _save_cache()
        return status()

    if code in (401, 403):
        # 服务端明确拒绝：key 无效 / 过期 / 被撤销 —— 这是权威结论，不再沿用缓存
        _apply_result({"valid": False, "tier": TIER_FREE,
                       "reason": body.get("reason") or "rejected"}, "server")
        _save_cache()
        return status()

    # 网络不通或服务端异常：沿用缓存 + 宽限期，避免「服务器一抖用户就掉级」
    return _fallback_to_cache(reason="offline" if code == 0 else "server_error",
                              silent=silent)


def _fallback_to_cache(reason: str, silent: bool = False) -> dict:
    """断网兜底：缓存在宽限期内就沿用上次结论，否则降到 free。

    缓存必须与「同一个授权码 + 同一台设备」绑定才采信 —— 否则改了 key、
    或者把 data/ 整个拷到另一台机器，都会拿旧结论冒充新授权。
    """
    cache = _read_cache()
    cfg = _cfg()
    now = time.time()
    fresh = ((cache.get("key_tail") or "") == (current_key() or "")[-6:]
             and (cache.get("hwid") or "") == hwid())
    expires = float(cache.get("session_expires") or 0) if fresh else 0
    cached_tier = (cache.get("tier") or TIER_FREE).lower() if fresh else TIER_FREE
    within = expires > 0 and now < expires

    if cached_tier in _TIER_RANK and within:
        with _lock:
            _state.update({
                "tier": cached_tier,
                "valid": bool(cache.get("valid")),
                "reason": reason,
                "source": "cache",
                "expires_at": cache.get("expires_at") or "",
                "session_expires": expires,
                "activations_used": int(cache.get("activations_used") or 0),
                "activations_max": int(cache.get("activations_max") or 0),
                "checked_at": now,
            })
    elif cached_tier in _TIER_RANK and expires > 0 and \
            now < expires + cfg["grace_hours"] * 3600:
        # 会话过期但在宽限期内：给一天一提示的软处理，不直接砍权限
        with _lock:
            _state.update({
                "tier": cached_tier,
                "valid": bool(cache.get("valid")),
                "reason": "grace",
                "source": "cache",
                "expires_at": cache.get("expires_at") or "",
                "session_expires": expires,
                "activations_used": int(cache.get("activations_used") or 0),
                "activations_max": int(cache.get("activations_max") or 0),
                "checked_at": now,
            })
        if not silent:
            print("[授权] 离线且会话已过期，宽限期内沿用上次授权（%s）"
                  % _state["tier"])
    else:
        with _lock:
            _state.update({
                "tier": TIER_FREE, "valid": False, "reason": reason,
                "source": "default", "session_expires": 0.0, "checked_at": now,
            })
    return status()


# ────────────────────────────────────────────────────────────
# 缓存
# ────────────────────────────────────────────────────────────
def _read_cache() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_cache():
    data = dict(_state)
    data["hwid"] = hwid()
    data["key_tail"] = (current_key() or "")[-6:]
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────
# 心跳
# ────────────────────────────────────────────────────────────
def _heartbeat_interval() -> float:
    """按服务端给的会话 TTL 定心跳间隔（取一半，最少 1 小时）。"""
    with _lock:
        expires = _state["session_expires"]
    ttl = (expires - time.time()) if expires else 0
    if ttl <= 0:
        return 3600.0
    return max(3600.0, ttl / 2)


def _heartbeat_loop():
    """后台线程：定期心跳续期；失败退避重试，不打扰用户。"""
    fails = 0
    while not _hb_stop.is_set():
        wait = _heartbeat_interval() if fails == 0 else min(600.0 * fails, 3600.0)
        if _hb_stop.wait(wait):
            return
        st = check(ping=1, silent=True)
        if st["valid"] and st["source"] == "server":
            fails = 0
            continue
        fails += 1
        if fails in (1, 3):
            print("[授权] 心跳失败（%s），%d 分钟后重试" % (st["reason"], int(wait // 60)))


def start_heartbeat():
    """启动心跳线程（幂等）。"""
    global _hb_thread
    if _hb_thread is not None and _hb_thread.is_alive():
        return
    _hb_stop.clear()
    _hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True,
                                  name="license-heartbeat")
    _hb_thread.start()


def stop_heartbeat():
    _hb_stop.set()


# ────────────────────────────────────────────────────────────
# 对外查询
# ────────────────────────────────────────────────────────────
def status() -> dict:
    with _lock:
        return dict(_state)


def tier() -> str:
    return status()["tier"]


def is_pro() -> bool:
    return _TIER_RANK.get(tier(), 0) >= _TIER_RANK[TIER_PRO]


def has(feature: str) -> bool:
    """纯查询：当前等级是否包含该功能（不打印、不阻断）。"""
    need = FEATURE_TIERS.get(feature, TIER_FREE)
    return _TIER_RANK.get(tier(), 0) >= _TIER_RANK.get(need, 0)


def ensure(feature: str, label: str = "") -> bool:
    """功能门控：可以继续返回 True，否则 False。

    enforce=off   → 永远放行
    enforce=soft  → 放行但提示（默认，避免误伤老用户）
    enforce=hard  → 拒绝，由调用方决定如何退出
    """
    mode = enforce_mode()
    if mode == "off" or has(feature):
        return True

    need = FEATURE_TIERS.get(feature, TIER_FREE)
    name = label or feature
    print("[授权] %s 需要 %s 授权（当前：%s）" % (name, need, tier()))
    if mode == "hard":
        print("[授权] 当前为强制模式（license.enforce=hard），已停止该功能。")
        print("[授权] 激活：python main.py license <授权码>")
        return False
    print("[授权] 当前为提示模式（license.enforce=soft），功能继续可用；"
          "如需强制限制请把 config.json 的 license.enforce 改为 hard。")
    return True


def describe() -> str:
    """一行人类可读状态，用于 /license、启动 banner 等。"""
    st = status()
    if enforce_mode() == "off":
        return "授权校验已关闭（SOUL_NO_LICENSE=1）"
    parts = ["等级 %s" % st["tier"]]
    if st["expires_at"]:
        parts.append("有效期至 %s" % st["expires_at"])
    if st["activations_max"]:
        parts.append("设备 %d/%d" % (st["activations_used"], st["activations_max"]))
    if st["source"] == "cache":
        parts.append("离线沿用缓存")
    if not st["valid"]:
        parts.append("原因 %s" % st["reason"])
    key = current_key()
    parts.append("授权码 %s" % ("****" + key[-6:] if key else "未填写"))
    parts.append("HWID %s" % hwid()[:12])
    return " · ".join(parts)


# ────────────────────────────────────────────────────────────
# 生命周期
# ────────────────────────────────────────────────────────────
def init(heartbeat: bool = True) -> dict:
    """启动时调用一次：校验 → 打印一行状态 → 起心跳。

    任何异常都被吞掉并降级为 free —— 授权层不该成为启动失败的原因。
    """
    global _initialized
    if _initialized:
        return status()
    _initialized = True

    try:
        check(ping=0)
    except Exception as exc:                     # 兜底：绝不让它挡住启动
        _state["last_error"] = str(exc)
        _fallback_to_cache(reason="check_failed", silent=True)

    st = status()
    if enforce_mode() == "off":
        print("[授权] 已跳过校验（SOUL_NO_LICENSE=1）")
    elif st["valid"]:
        print("[授权] %s" % describe())
    elif st["source"] == "cache":
        print("[授权] 无法连接授权服务，沿用本地缓存：%s" % describe())
    else:
        print("[授权] 免费模式（%s）· 需要 Pro 的方法可用 `python main.py license <授权码>` 激活"
              % (st["reason"] if st["reason"] != "ok" else "未填写授权码"))

    if heartbeat and st["valid"] and enforce_mode() != "off":
        start_heartbeat()
    return st


def refresh(silent: bool = False) -> dict:
    """手动重新校验（例如激活之后）。"""
    st = check(ping=0, silent=silent)
    if st["valid"]:
        start_heartbeat()
    return st


def activate(key: str) -> tuple:
    """写入授权码并立即校验，返回 (成功, 说明)。"""
    key = (key or "").strip()
    if not key:
        return False, "授权码为空"
    if len(key) < 8:
        return False, "授权码格式不对（太短）"

    data = _read_config()
    section = data.get("license")
    if not isinstance(section, dict):
        section = {}
    section["key"] = key
    section.setdefault("api", DEFAULT_API)
    section.setdefault("enforce", "soft")
    data["license"] = section
    if not _write_config(data):
        return False, "写入 config.json 失败：%s" % _state["last_error"]

    st = check(ping=0, silent=True)
    if st["valid"]:
        start_heartbeat()
        return True, describe()
    return False, "校验未通过：%s（%s）" % (st["reason"], describe())


def deactivate() -> tuple:
    """清空授权码，回到 free。"""
    data = _read_config()
    section = data.get("license")
    if isinstance(section, dict) and "key" in section:
        section["key"] = ""
        data["license"] = section
        _write_config(data)
    stop_heartbeat()
    with _lock:
        _state.update({"tier": TIER_FREE, "valid": False, "reason": "deactivated",
                       "source": "default", "session_expires": 0.0})
    try:
        os.remove(CACHE_PATH)
    except OSError:
        pass
    return True, "已退出授权，回到免费模式"


if __name__ == "__main__":
    # 自检：python3 -m core.license
    init(heartbeat=False)
    print("等级   :", tier())
    print("是否Pro:", is_pro())
    print("说明   :", describe())
    print("HWID   :", hwid())
    print("服务端 :", api_base())
    print("模式   :", enforce_mode())
