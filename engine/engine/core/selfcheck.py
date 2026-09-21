# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""深度自检 — 断言子系统真的留下了副作用
============================================
把各子系统真跑一遍，然后检查**它们到底有没有留下痕迹**。

为什么需要它
------------
本仓库有 835 个 try 块，其中 413 处（49%）是「异常一律 pass」。这套写法让一个
子系统可以静默变成尸体而毫无症状 —— 实测撞到过两个：

  · 深夜复盘 `_night_review` 里一句多余的局部 import（`from engine import mind
    as mind_module`）把 mind_module 变成了函数局部名，于是它之前的每次引用都
    UnboundLocalError，整个复盘从「2. 人格微调补充」起崩掉；后面的自省固化、
    阶段更新、夜间反思、梦境生成、情绪注入**一次都没跑过**，而对外只表现为
    life_tick 顶层那句被吞掉的「tick 异常」。
  · 经历事件用了一个不存在的 `event_type="conversation"`，在 `record_event`
    第一行就 return —— 「经历驱动成长」整条静默退化成纯时间驱动。

`selftest` 验的是「命令 → 引擎 → 管道」这条链路通不通；这里验的是「跑完之后，
该留下的东西有没有真的留下」。每个检查只做两件事：触发一次真实调用，然后断言
可观察的产物（DB 行 / JSON 文件 / 字段 / 模块）。

调用方必须先把模型后端换成假回复，否则会真花额度 —— 见 engine_bridge.cmd_check。
"""

import datetime
import sqlite3
import sys

from core import database as db


# 全跑一遍之后**必须有**的模块。挑的都是「只在某条特定路径上被导入」的：
# 它们缺席就等于那条路径没走完。最典型的是 engine.creative.dream ——
# 只有深夜复盘的最后一步（7.5 梦境生成）会导入它，它不在，就说明复盘中途断了。
_REQUIRED_MODULES = (
    "engine.core.chat_pipeline",        # 对话主链路
    "engine.core.inference",            # 八阶推理 / prompt 构建
    "engine.core.mind",                 # 心智
    "engine.core.thinking",             # 思维 / 多段回复指令
    "engine.life.life",                 # tick 宿主
    "engine.life.growth",               # 岁月成长
    "engine.life.evolution",            # 自我进化
    "engine.behavior.experience",       # 经历日志（经历驱动成长的入口）
    "engine.behavior.delivery",         # 投递
    "engine.cognitive.reflection",      # 自省
    "engine.creative.creative_spark",   # 深夜复盘 3.16 创意自评
    "engine.creative.dream",            # 深夜复盘 7.5 梦境 —— 复盘跑到最后的证据
    "engine.self.self_model",           # 自我叙事
    "engine.social.laws",               # 原则校验
)

# 出生维度缺省的上限。healing_reflection 在阶段 composite 里权重 0.3，缺省值给
# 0.40 会让出生瞬间 composite 就到 0.13 —— 直接落进第二阶段，第一阶段的区间是
# (0, 0.10)，等于天生不可达。0.10 对应出生 composite ≈ 0.04。
_BIRTH_HEALING_MAX = 0.15


def _rows(sql, args=()):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _one(sql, args=(), default=None):
    try:
        rows = _rows(sql, args)
        return rows[0][0] if rows else default
    except Exception:
        return default


def _fresh_schema_default(column: str):
    """用一份**全新**的临时库读列默认值。

    不能直接读数据家目录那个库：数据家目录是空的、而代码树里还留着旧版数据
    （engine/data）时，core.paths 会把旧库**复制**过去（migrate_legacy_data），
    于是拿到的是旧 schema —— 实测就因此读到 0.40，而那不是今天建新库会得到的值。
    这里用 core.database 建表用的同一个函数在临时文件上建一次，读到的才是
    「新灵魂真正会拿到的默认值」。
    """
    import os
    import tempfile
    from core import database as dbmod

    fd, path = tempfile.mkstemp(prefix="soulviai-schema-", suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        dbmod._create_tables(conn)
        row = conn.execute("SELECT dflt_value FROM pragma_table_info('personality') "
                           "WHERE name=?", (column,)).fetchone()
        conn.close()
        return row[0] if row else None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run(engine, user_id: str, now=None) -> dict:
    """跑完整套深度检查，返回 {"ok", "checks": [...], ...}。

    只有全部检查通过才 ok=True。任何一项失败都带 detail 说明观察到的现象。
    """
    checks = []
    now = now or datetime.datetime.now()

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:220]})
        return bool(ok)

    # error_log 水位：最后只看本轮新增的（历史错误不算这次的问题）
    err_before = _one("SELECT COALESCE(MAX(id), 0) FROM error_log")

    # ── 1. 用户与心智初始化 ──
    row = _rows("SELECT years_precipitation, healing_reflection, "
                "relationship_fatigue, personality_stage "
                "FROM personality WHERE user_id=?", (user_id,))
    if row:
        yrs, heal, rf, stage = row[0]
        add("用户初始化", True,
            "years=%.3f heal=%.3f fatigue=%.3f stage=%s" % (yrs, heal, rf, stage))
    else:
        add("用户初始化", False, "personality 里没有 user_id=%s 的行" % user_id)

    # ── 2. 出生维度缺省（决定新灵魂落在哪个阶段）──
    # 断言的是「新建库会拿到的值」，不是数据家目录那份 —— 后者可能是旧库迁入的。
    fresh_heal = _fresh_schema_default("healing_reflection")
    live_heal = _one("SELECT dflt_value FROM pragma_table_info('personality') "
                     "WHERE name='healing_reflection'")
    try:
        ok_birth = float(fresh_heal) <= _BIRTH_HEALING_MAX
    except (TypeError, ValueError):
        ok_birth = False
    add("出生维度缺省合理", ok_birth,
        "新建库的 healing_reflection 默认值=%s（>%.2f 会把新生灵魂直接推进第二阶段，"
        "而第一阶段区间是 0~0.10）；当前数据家目录那份=%s%s"
        % (fresh_heal, _BIRTH_HEALING_MAX, live_heal,
           "（旧库迁入，沿用旧 schema —— 存量灵魂本来也不受列默认值影响）"
           if str(live_heal) != str(fresh_heal) else ""))

    # ── 3. 对话主链路 ──
    before = _one("SELECT COUNT(*) FROM message_log WHERE user_id=?", (user_id,), 0)
    resp, err = "", None
    try:
        from engine.core.chat_pipeline import ChatPipeline
        resp = ChatPipeline(engine).run(user_id, "今天有点累，想跟你说说话")
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    after = _one("SELECT COUNT(*) FROM message_log WHERE user_id=?", (user_id,), 0)
    add("对话主链路", err is None and after > before,
        err or "message_log %d → %d 行；回复 %r" % (before, after, (resp or "")[:40]))

    # ── 4. 经历事件写入（经历驱动成长的唯一入口）──
    n0 = None
    try:
        from engine.behavior import experience as exp
        n0 = len(exp.get_daily_events(user_id))
        exp.record_context_events(
            user_id,
            "我最近工作上出了点事，其实我一直觉得自己挺没用的，想跟你说说",
            "我在，慢慢说。" * 8,
            {"intent": "倾诉", "depth": "深度", "true_emotion": "难过",
             "what_they_need": "倾听", "confidence": 0.82},
            "温柔",
        )
        n1 = len(exp.get_daily_events(user_id))
        add("经历事件写入", n1 > n0, "当日事件 %d → %d 条" % (n0, n1))
    except Exception as e:
        add("经历事件写入", False, "%s: %s" % (type(e).__name__, e))

    # ── 5. 经历驱动成长（必须不是「当日无事件」的兜底）──
    try:
        from engine.life import evolution as evo
        g = evo.compute_experience_growth(user_id)
        add("经历驱动成长生效", len(g) > 2,
            "增量维度 %d 个（兜底只有 2 个）：%s"
            % (len(g), ", ".join(sorted(g)[:6])))
    except Exception as e:
        add("经历驱动成长生效", False, "%s: %s" % (type(e).__name__, e))

    # ── 6. 深夜复盘跑完整（本文档开头那个 UnboundLocalError 的回归闸）──
    dream_before = "engine.creative.dream" in sys.modules
    err = None
    try:
        from engine.life import life as life_mod
        life_mod._night_review(user_id, now)
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    dream_after = "engine.creative.dream" in sys.modules
    add("深夜复盘跑到最后", err is None and dream_after,
        err or ("7.5 梦境生成已导入%s" % ("（此前已加载）" if dream_before else "")
                if dream_after else
                "复盘没抛错，但 7.5 梦境生成没被导入 —— 说明中途静默中断了"))

    # ── 7. tick 各层可执行（冒烟）──
    bad = []
    try:
        from engine.life import life as life_mod
        for label, fn in (("life_tick", lambda: [life_mod.life_tick() for _ in range(3)]),
                          ("10min", lambda: life_mod._run_10min_ticks(user_id)),
                          ("30min", lambda: life_mod._run_30min_ticks(user_id)),
                          ("60min", lambda: life_mod._run_60min_ticks(user_id))):
            try:
                fn()
            except Exception as e:
                bad.append("%s(%s: %s)" % (label, type(e).__name__, e))
    except Exception as e:
        bad.append("导入失败 %s: %s" % (type(e).__name__, e))
    add("tick 各层可执行", not bad,
        "; ".join(bad) or "life_tick×3 / 10min / 30min / 60min 都没抛错")

    # ── 8. 多段回复协议（「|||」契约，曾在常驻服务边界被悄悄毁掉）──
    try:
        from engine.core.chat_pipeline import split_reply_parts
        r1 = split_reply_parts("甲|||乙|||丙")
        r2 = split_reply_parts("甲\n\n乙")
        r3 = split_reply_parts("一整句\n只是软换行")
        add("多段回复协议", len(r1) == 3 and len(r2) == 2 and len(r3) == 1,
            "「|||」→%d 段 / 空行→%d 段 / 软换行→%d 段（期望 3/2/1）"
            % (len(r1), len(r2), len(r3)))
    except Exception as e:
        add("多段回复协议", False, "%s: %s" % (type(e).__name__, e))

    # ── 9. 关键模块覆盖 ──
    missing = [m for m in _REQUIRED_MODULES if m not in sys.modules]
    add("关键模块已加载", not missing,
        ("缺失: " + ", ".join(missing)) if missing
        else "%d 个关键模块全部加载" % len(_REQUIRED_MODULES))

    # ── 10. 静默失败：本轮新增的 error_log ──
    new_errs = []
    if err_before is not None:
        try:
            new_errs = _rows("SELECT source, message FROM error_log "
                             "WHERE id > ? ORDER BY id", (err_before,))
        except Exception:
            pass
    add("无新增静默失败", not new_errs,
        ("%d 条: %s" % (len(new_errs),
                        "; ".join("%s → %s" % (s, m[:70]) for s, m in new_errs[:4])))
        if new_errs else "error_log 无新增（说明这一轮没有子系统在静默报错）")

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "missing_modules": missing,
        "new_errors": [{"source": s, "message": m} for s, m in new_errs],
    }
