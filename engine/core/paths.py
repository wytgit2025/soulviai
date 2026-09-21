# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""运行路径：代码根与数据根

技能目录是**代码**（可以拷贝、压缩、分发），`data/` 是 ta 的**记忆**。绑在
一起会发生两类事故，且都不需要经过打包脚本就能触发：

  1. 把技能目录整体拷给别人 / 同步网盘 / 压进 zip —— 记忆连同渠道凭证
     （`data/wx_creds.json`）一起外泄；
  2. 同机并存两份副本 —— 各写各的 data/，心智状态就此分叉。

所以数据落在用户主目录下的固定位置：

    runtime_root()   engine/        代码根：config.json / .venv / requirements
    skill_root()     技能根          config.yaml / scripts / variants
    home_root()      ~/.soulviai    ← 运行期的工作目录
    data_root()      .../data/      ta 的记忆：db / json / flaw

**运行期工作目录就是 home_root()**：引擎里有大量以 cwd 为基准的相对路径
（`data/json/*.json`、`data/db/soulmate.db`），cwd 切过去之后它们全部落进
数据家，一行都不用改。反过来，任何「换个目录启动引擎」的入口都必须调用
`chdir_home()`，否则会就地长出一份新的空记忆 —— 那正是「灵魂失忆」事故。

优先级：`$SOULVIAI_DATA_DIR` > `config.yaml: data_dir` > `~/.soulviai`。
"""
from __future__ import annotations

import os
import shutil

HOME_ENV = "SOULVIAI_DATA_DIR"
CONFIG_ENV = "SOULVIAI_CONFIG"
DEFAULT_HOME_NAME = ".soulviai"
DATA_SUBDIRS = ("db", "json", "flaw")      # 相对 data/，按需自建

_HOME_CACHE = None


# ── 代码根 ───────────────────────────────────────────────────
def runtime_root():
    """引擎目录（含 core/ 的那一层），即 engine/。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def skill_root():
    """技能根目录（engine/ 的上一级）。独立部署时可能不存在。"""
    return os.path.dirname(runtime_root())


def code_file(*parts):
    """代码根下的文件（config.json / requirements.txt / VERSION ...）。"""
    return os.path.join(runtime_root(), *parts)


def config_json_path():
    """引擎的 config.json（模型 Key、渠道凭证、授权都在这里）。

    绝对路径：config.json 是代码的一部分，不该跟着 cwd 跑。
    """
    return code_file("config.json")


# ── config.yaml（技能根那份，与 soulviaictl 同一份）────────────────
def config_path():
    """config.yaml 位置：$SOULVIAI_CONFIG > 技能根那份。

    优先级必须与 soulviaictl / engine_bridge / clients/web 一致。少了 $SOULVIAI_CONFIG
    这一层，用户用备用配置改了 daemon_port 时，CLI 会连新端口，而聊天渠道仍
    固执地去探 8765 —— 两边都以为对方没起服务。
    """
    env = os.environ.get(CONFIG_ENV)
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(skill_root(), "config.yaml")


def _strip_comment(raw):
    """去掉行尾注释：只认「行首或空白之后的 #」，引号内的 # 不算。

    否则 `daemon_token_file: /Volumes/a#b/token` 会被截成 `/Volumes/a` ——
    路径静默变错，比直接报错难查得多。
    """
    quote = ""
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i]
    return raw


def parse_flat_yaml(text):
    """极简 YAML：扁平 `key: value` + # 注释 + 引号字符串。

    语义基准是 scripts/soulviaictl.py 的同名函数（启动器可能跑在连引擎依赖都没装
    的解释器上，所以那边各留一份）。**改这里就要同步改那边**，以及与它并列的
    engine/clients/web.py:_flat_config。
    """
    cfg = {}
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip() or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        # 只有成对的引号才剥：`"it's"` 应得到 `it's`，贪心 strip 会啃成 `its`
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if val.lower() in ("true", "false"):
            cfg[key] = (val.lower() == "true")
        else:
            cfg[key] = val
    return cfg


def read_config():
    """读 config.yaml，返回扁平字典。读不到/坏了都返回 {}（降级仍能跑）。"""
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            return parse_flat_yaml(fh.read())
    except Exception:
        return {}


# ── 数据根 ───────────────────────────────────────────────────
def home_root():
    """数据家目录（运行时工作目录，`data/` 的上一层）。

    $SOULVIAI_DATA_DIR > config.yaml: data_dir > ~/.soulviai
    data_dir 写相对路径时按技能根解析，免得它跟着 cwd 跑。
    """
    global _HOME_CACHE
    if _HOME_CACHE:
        return _HOME_CACHE

    env = (os.environ.get(HOME_ENV) or "").strip()
    if env:
        _HOME_CACHE = os.path.abspath(os.path.expanduser(env))
        return _HOME_CACHE

    raw = read_config().get("data_dir") or ""
    if isinstance(raw, str):
        raw = raw.strip()
    if raw:
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            path = os.path.join(skill_root(), path)
    else:
        path = os.path.join(os.path.expanduser("~"), DEFAULT_HOME_NAME)
    _HOME_CACHE = os.path.abspath(path)
    return _HOME_CACHE


def reset_home_cache():
    """丢掉缓存（测试、或运行期显式改 SOULVIAI_DATA_DIR 时才需要）。"""
    global _HOME_CACHE
    _HOME_CACHE = None


def data_root():
    """记忆目录：db / json / flaw 都在它下面。"""
    return os.path.join(home_root(), "data")


def data_path(*parts):
    """记忆目录下的文件绝对路径。"""
    return os.path.join(data_root(), *parts)


def home_file(*parts):
    """数据家目录下的文件（token / 日志 / pid 这些运行期状态）。"""
    return os.path.join(home_root(), *parts)


def ensure_home():
    """建好数据家目录骨架，返回 home_root()。"""
    root = home_root()
    for sub in DATA_SUBDIRS:
        os.makedirs(os.path.join(root, "data", sub), exist_ok=True)
    return root


# ── 旧数据迁移（记忆没有备份，所以只复制不删除）────────────────
def legacy_data_dir():
    """旧版把记忆写在代码树里的位置：engine/data。"""
    return os.path.join(runtime_root(), "data")


def migrate_legacy_data(quiet=False, purge=False):
    """把旧版留在 engine/data 的记忆搬到数据家目录。

    只在「新位置还没有记忆」时搬：有 soulmate.db 就认为已经搬过了，不再覆盖
    —— 免得把已经用起来的新记忆冲掉。默认只复制不删除，删源要显式 --purge。
    """
    src, dst = legacy_data_dir(), data_root()
    if os.path.realpath(src) == os.path.realpath(dst):
        return None

    # token 一并带到新位置（只复制、不改旧那份）：常驻服务可能仍念着旧路径的
    # token，复制一份让新老两侧读到同一个值 —— 否则会出现「服务明明在跑，CLI
    # 却报 token 不匹配」，用户还以为是坏了。
    legacy_token = os.path.join(runtime_root(), ".soul-daemon.token")
    new_token = home_file(".soul-daemon.token")
    if os.path.isfile(legacy_token) and not os.path.exists(new_token):
        try:
            os.makedirs(os.path.dirname(new_token), exist_ok=True)
            shutil.copy2(legacy_token, new_token)
        except OSError:
            pass

    if not os.path.isdir(src):
        return None
    if os.path.exists(os.path.join(dst, "db", "soulmate.db")):
        return None

    moved = []
    for name in sorted(os.listdir(src)):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        elif os.path.isfile(s):
            shutil.copy2(s, d)
        else:
            continue
        moved.append(name)
    if not moved:
        return None
    if not quiet:
        print("[soulviai] 已把旧数据搬到 %s（%s）" % (dst, ", ".join(moved)))
        print("[soulviai] 确认对话历史还在之后，可删掉旧目录：%s" % src)
    if purge:
        shutil.rmtree(src, ignore_errors=True)
    return moved


def chdir_home(migrate=True):
    """切到数据家目录：运行期一切相对路径都从这里展开。

    所有非「已在正确目录」的引擎入口都要先调它（缺这一句就会就地长出一份
    空记忆）。返回 home_root()。
    """
    ensure_home()
    if migrate:
        migrate_legacy_data()
    root = home_root()
    os.chdir(root)
    return root
