# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

"""
soulviai — 主入口
支持运行模式:
  python main.py cli     → 命令行对话模式（默认）
  python main.py wx      → 微信 Bot 模式
  python main.py qq      → QQ Bot 模式
  python main.py tg      → Telegram Bot 模式
  python main.py dc      → Discord Bot 模式
  python main.py im      → iMessage (BlueBubbles) 模式
  python main.py web     → Web 终端模式（浏览器）
  python main.py state   → 查看生命状态
  python main.py license → 查看/激活授权（license <授权码> 激活，license off 退出）

所有平台共用同一个灵魂（user_id = default_user），记忆和情感互通。
"""
import sys
import os

# 确保项目根目录在 sys.path
_CODE_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _CODE_ROOT)

# 运行期工作目录 = 数据家目录（默认 ~/.soul-skill）。
# 引擎里所有 `data/...` 都是相对 cwd 的路径，少了这一句就会在「启动时所在的
# 目录」旁边长出一份新的空记忆 —— 看起来就像灵魂失忆。
try:
    from core import paths as _paths
    _paths.chdir_home()
    _CONFIG_JSON = _paths.config_json_path()
except Exception:
    _CONFIG_JSON = os.path.join(_CODE_ROOT, "config.json")

# ── 首次启动：人格探索问答 ──
try:
    import json, os
    if not os.path.exists(_CONFIG_JSON):
        import onboarding
        onboarding.run()
    else:
        with open(_CONFIG_JSON, encoding="utf-8") as f:
            _cfg = json.load(f)
        if not _cfg.get("_onboarding_done"):
            import onboarding
            onboarding.run()
except Exception:
    import traceback
    traceback.print_exc()

# ── 读取语言设置 ──
try:
    with open(_CONFIG_JSON, encoding="utf-8") as f:
        _lang_cfg = json.load(f)
    _lang = _lang_cfg.get("lang", "zh")
    from engine.i18n import set_lang
    set_lang(_lang)
    os.environ["AI_LANG"] = _lang
except Exception:
    pass

SOUL_USER_ID = "default_user"


def _license_ok(feature: str, label: str) -> bool:
    """授权门控：off 放行 / soft 提示放行 / hard 拒绝。

    授权层自己出问题（模块缺失、配置损坏）时一律放行 —— 它不该成为
    「引擎跑不起来」的原因。
    """
    try:
        from core import license as lic
        return lic.ensure(feature, label)
    except Exception:
        return True


def run_license(argv):
    """授权管理：python main.py license [授权码|status|off]

    不带参数 = 查看当前状态；带授权码 = 激活；off = 退出授权。
    """
    from core import license as lic

    arg = (argv[0].strip() if argv else "")
    if not arg or arg == "status":
        lic.init(heartbeat=False)
        print("[授权] %s" % lic.describe())
        print("[授权] 服务端: %s · 校验模式: %s"
              % (lic.api_base(), lic.enforce_mode()))
        print("[授权] 设备指纹(HWID): %s" % lic.hwid())
        print("[授权] 用法: python main.py license <授权码>  /  python main.py license off")
        return
    if arg in ("off", "none", "logout"):
        _ok, msg = lic.deactivate()
        print("[授权] %s" % msg)
        return
    ok, msg = lic.activate(arg)
    print("[授权] %s" % ("✅ 激活成功 · " + msg if ok else "❌ " + msg))
    if not ok:
        raise SystemExit(1)


def _cli_t(key: str) -> str:
    """CLI 翻译辅助"""
    try:
        from engine.i18n import t
        return t(key)
    except Exception:
        return key


def run_cli():
    """命令行交互模式（: 多段消息 + 延迟回复 + 自主引擎 + 后台投递）"""
    from soul import SoulEngine
    import time
    import threading
    import datetime
    from core.banner import banner_mode

    print(banner_mode(_cli_t("cli.banner")))
    print()

    # 优先复用常驻服务（Web 终端 / Agent / 渠道共享同一个灵魂）；拿不到才自建引擎
    backend = _resolve_backend("终端")
    engine = None

    if backend is not None:
        backend.init(SOUL_USER_ID)
        state = backend.state(SOUL_USER_ID) or {}
    else:
        engine = SoulEngine()

        # 启动自主思考引擎（走常驻服务时由 daemon 负责）
        try:
            from engine import autonomous as autonomous_module
            autonomous_module.load_engine_config()
            autonomous_module.start_thought_engine()
        except Exception:
            pass

        print(f"[初始化] {_cli_t('cli.init')}")
        engine.ensure_user(SOUL_USER_ID)
        state = engine.get_state(SOUL_USER_ID)

    print(f"  {_cli_t('cli.personality_stage')}: {state.get('personality_stage', '')}")
    print(f"  {_cli_t('cli.life_state')}: {state.get('life_state', '')}")
    print()

    def _chat(text):
        if backend is not None:
            return backend.chat(SOUL_USER_ID, text)
        return engine.chat(SOUL_USER_ID, text)

    def _state():
        if backend is not None:
            return backend.state(SOUL_USER_ID) or {}
        return engine.get_state(SOUL_USER_ID)

    print(_cli_t('cli.prompt'))
    print("-" * 44)

    # ═══════════════════════════════════════════════
    # 后台投递线程 — 把队列里的消息推送到终端
    # ═══════════════════════════════════════════════
    cli_running = True

    def _delivery_loop():
        """后台线程：定期检查待发队列并投递到终端"""
        from core import database as db
        while cli_running:
            try:
                if backend is not None:
                    # 只取不改（ack=False）：延迟未到的消息必须留在队列里，
                    # 否则 ack=True 会先把它标成已送达，投递前就丢了。
                    msgs = backend.drain_messages(SOUL_USER_ID, limit=3, ack=False)
                else:
                    msgs = db.get_pending_messages(SOUL_USER_ID, max_count=3)
                delivered_ids = []
                for m in msgs:
                    # 检查延迟是否已到期
                    created = m.get("created_at", "")
                    delay = m.get("thinking_delay_seconds", 0)
                    if created and delay > 0:
                        try:
                            created_dt = datetime.datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
                            elapsed = (datetime.datetime.now() - created_dt).total_seconds()
                            if elapsed < delay:
                                continue  # 还没到时间，留在队列里下轮再看
                        except Exception:
                            pass

                    # 投递到终端
                    content = m.get("content") or ""
                    msg_type = m.get("msg_type") or "reply"

                    # 按类型加前缀
                    type_prefixes = {
                        "reply": "",
                        "proactive": "💬 ",
                        "emotional_overflow": "💗 ",
                        "interesting_thought": "💡 ",
                        "memory_recall": "📖 ",
                    }
                    type_hints = {
                        "reply": "",
                        "proactive": "* (主动分享) *",
                        "emotional_overflow": "* (情绪涌现) *",
                        "interesting_thought": "* (想到的事) *",
                        "memory_recall": "* (记忆浮现) *",
                    }
                    prefix = type_prefixes.get(msg_type, "💬 ")
                    hint = type_hints.get(msg_type, "")

                    # 按 ||| 拆多段
                    parts = [p.strip() for p in content.split("|||") if p.strip()]
                    for i, part in enumerate(parts):
                        if i == 0:
                            print(f"\n{prefix}数字生命: {part}")
                        else:
                            time.sleep(1.2)
                            print(f"数字生命: {part}")

                    if m.get("id") is not None:
                        delivered_ids.append(m["id"])
                    if hint:
                        print(f"\033[2m{hint}\033[0m")

                # 只确认真正打进终端的那些；延迟未到的仍在队列里等下一轮
                if delivered_ids:
                    if backend is not None:
                        backend.ack(delivered_ids, user_id=SOUL_USER_ID)
                    else:
                        for mid in delivered_ids:
                            db.mark_message_delivered(mid)
            except Exception:
                pass
            time.sleep(2)  # 每2秒检查一次

    delivery_thread = threading.Thread(target=_delivery_loop, daemon=True, name="cli-delivery")
    delivery_thread.start()

    # ═══════════════════════════════════════════════
    # 主循环
    # ═══════════════════════════════════════════════
    try:
        while True:
            try:
                msg = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n[{_cli_t('cli.goodbye')}]")
                break

            if not msg:
                continue

            if msg.lower() in ("/quit", "/exit", "/q"):
                print(f"[{_cli_t('cli.goodbye')}] {_cli_t('cli.goodbye_note')}")
                break

            if msg.lower() == "/state":
                state = _state()
                identity = state.get("identity", {})
                print(f"\n【{_cli_t('cli.state_title')}】")
                print(state["mind_summary"])
                print(f"\n{state['fate_summary']}")
                print(f"{_cli_t('cli.life_state')}: {state['life_state']}")
                if identity:
                    print(f"\n【{_cli_t('cli.life_trait')}】{identity.get('signature', '')}")
                    print(f"  {identity.get('essence', '')}")
                    traits = identity.get('traits', [])
                    if traits:
                        print(f"  特质标签: {' | '.join(traits[:8])}")

                # MBTI
                try:
                    from engine import user_persona as up
                    mbti = up.compute_mbti_from_db(SOUL_USER_ID)
                    if mbti and mbti["confidence"] > 0.1:
                        dims = mbti.get("dimensions", {})
                        detail = " | ".join(
                            f"{d['letter']}({d['raw']:.2f})" for d in dims.values()
                        )
                        pct = round(mbti["confidence"] * 100)
                        print(f"\n【{_cli_t('cli.mbti_label')}】{mbti['type']}（{pct}%）")
                        print(f"  维度: {detail}")
                except Exception:
                    pass
                continue

            # 正常对话（: 支持多段消息 + 延迟回复）
            try:
                response = _chat(msg)
            except KeyboardInterrupt:
                print(f"\n[{_cli_t('cli.signal_interrupt')}]")
                break
            except Exception as e:
                print(f"\n[{_cli_t('cli.chat_error')}] {e}")
                response = ""

            if response == "":
                print(f"\n* ({_cli_t('cli.no_reply')}) *")
            elif response == "__QUEUED__":
                print(f"\n* ({_cli_t('cli.queued')}) *")
            elif response.strip():
                parts = [p.strip() for p in response.split("|||") if p.strip()]
                for i, part in enumerate(parts):
                    if i == 0:
                        print(f"\n数字生命: {part}")
                    else:
                        time.sleep(1.5)
                        print(f"数字生命: {part}")

    finally:
        cli_running = False
        if backend is None:
            try:
                autonomous_module.stop_thought_engine()
            except Exception:
                pass


def run_wx():
    """微信 Bot 模式"""
    from core.banner import banner_mode

    print(banner_mode("微信 Bot 模式"))

    backend = _resolve_backend("微信")
    if backend is not None:
        from soul import _run_wx_bot
        _run_wx_bot(None, backend=backend)
        return

    from soul import SoulEngine
    SoulEngine().run_wx_bot()


def run_qq():
    """QQ Bot 模式"""
    from core.banner import banner_mode

    print(banner_mode("QQ Bot 模式"))

    backend = _resolve_backend("QQ")
    if backend is not None:
        from soul import _run_qq_bot
        _run_qq_bot(None, backend=backend)
        return

    from soul import SoulEngine
    SoulEngine().run_qq_bot()


def _resolve_backend(label):
    """优先复用本机常驻服务，让多个入口共享同一个灵魂。

    引擎的 SQLite 是单写者模型：渠道若自己 new 一个 SoulEngine，会与常驻服务
    撞 `database is locked`，心智状态也可能分叉。所以只要常驻服务可用，渠道就
    只当「收发的壳」，对话与待发消息全部转发过去。

    拿不到常驻服务时返回 None，调用方按老路子自建引擎。
    """
    try:
        from core import daemon_link
        backend = daemon_link.get_backend()
        if backend is not None:
            print("[%s] 已复用本机常驻服务 http://%s:%d（与其它入口共享同一个灵魂）"
                  % (label, backend.host, backend.port))
            return backend
        print("[%s] 常驻服务不可用，本次自建引擎（其间请勿同时运行别的入口）" % label)
    except Exception as exc:
        print("[%s] 常驻服务联动不可用：%s" % (label, exc))
    return None


def _local_engine():
    """仅在常驻服务不可用时才自建引擎。"""
    from soul import SoulEngine
    from engine import autonomous as autonomous_module
    from engine import delivery as delivery_module

    engine = SoulEngine()
    autonomous_module.load_engine_config()
    delivery_module.load_engine_config()
    autonomous_module.start_thought_engine()
    engine.ensure_user("default_user")
    return engine


def run_tg():
    """Telegram Bot 模式"""
    from core.banner import banner_mode
    from clients import tg as tg_client

    print(banner_mode("Telegram Bot 模式"))
    backend = _resolve_backend("Telegram")
    engine = None if backend is not None else _local_engine()

    bot = tg_client.TgBot()
    if not bot.wait_login(timeout=120):
        print("[Telegram] 登录失败")
        return

    print("[Telegram] 开始监听...")
    _run_platform_loop(engine, bot, "Telegram", backend=backend)


def run_dc():
    """Discord Bot 模式"""
    from core.banner import banner_mode
    from clients import dc as dc_client

    print(banner_mode("Discord Bot 模式"))
    backend = _resolve_backend("Discord")
    engine = None if backend is not None else _local_engine()

    bot = dc_client.DcBot()
    if not bot.wait_login(timeout=120):
        print("[Discord] 登录失败")
        return

    print("[Discord] 开始监听...")
    _run_platform_loop(engine, bot, "Discord", backend=backend)


def run_im():
    """iMessage Bot 模式 (需要 BlueBubbles Server on macOS)"""
    from core.banner import banner_mode
    from clients import im as im_client

    print(banner_mode("iMessage Bot 模式"))
    backend = _resolve_backend("iMessage")
    engine = None if backend is not None else _local_engine()

    bot = im_client.ImBot()
    if not bot.wait_login(timeout=120):
        print("[iMessage] 登录失败")
        return

    print("[iMessage] 开始监听...")
    _run_platform_loop(engine, bot, "iMessage", backend=backend)


def _deliver_via_backend(backend, bot, name):
    """把 ta 攒着的主动消息经常驻服务取出，再通过渠道发出去。

    本地模式由 delivery_module 直接读库；走常驻服务时不能读本地库
    （那是另一个写者），改用 `/drain` 拉取。

    拉取用 ack=False：只有渠道真的发出去（send_chat_reply 返回 True）的消息
    才回 `/ack` 确认，失败的下轮还在队列里，能重试。
    """
    from soul import send_chat_reply
    sent_ids = []
    for item in backend.drain_messages("default_user", limit=3, ack=False):
        text = item.get("text") or ""
        if not text.strip():
            continue
        ok = send_chat_reply(bot, "default_user", text)
        print("[%s] 投递主动消息 %s" % (name, "✅" if ok else "❌"))
        if ok and item.get("id") is not None:
            sent_ids.append(item["id"])
    if sent_ids:
        backend.ack(sent_ids, user_id="default_user")


def _run_platform_loop(engine, bot, name: str, backend=None):
    """通用平台消息循环（支持消息合并）。

    backend 不为 None 时，对话与待发消息都转发给常驻服务（多入口共享同一个
    引擎）；否则用传入的本地 engine。
    """
    from soul import send_chat_reply
    from engine.behavior.message_buffer import MessageAccumulator

    acc = MessageAccumulator(idle_timeout=3.0, max_batch_size=5)
    last_delivery = time.time()
    import signal as _sig
    _running = True

    def _stop(sig, frame):
        nonlocal _running
        print(f"\n[{name}] 正在停止...")
        _running = False

    _sig.signal(_sig.SIGINT, _stop)
    _sig.signal(_sig.SIGTERM, _stop)

    def _chat(text: str) -> str:
        """对话：优先走常驻服务（多入口共享同一个灵魂），否则本地引擎。"""
        if backend is not None:
            return backend.chat("default_user", text)
        return engine.chat("default_user", text)

    # 积累器的 key 恒为 "default_user"（单灵魂），但回消息要回到渠道里的真实
    # 会话，所以单独记住最近一个发送者 —— 否则 check_idle() 冲洗时 from_user
    # 会是上一轮循环的残留值，甚至一条消息都没收到时直接未定义。
    last_sender = {"id": "default_user"}

    def _process_batch(from_user: str, merged_text: str):
        """处理合并后的消息批次"""
        response = _chat(merged_text)

        if response == "":
            print(f"[{name}] 跳过回复")
        elif response == "__QUEUED__":
            print(f"[{name}] 已入队列")
        else:
            print(f"[{name}] → {response[:60]}...")
            ok = send_chat_reply(bot, from_user, response)
            print(f"[{name}] {'✅' if ok else '❌'}")

    while _running:
        try:
            updates = bot.poll_messages()
            for msg in updates:
                from_user = msg.get("from_user", "")
                content = msg.get("content", "")
                if not from_user or not content:
                    continue
                print(f"[{name}] [{from_user[:40]}]: {content[:80]}")
                last_sender["id"] = from_user

                # 消息进入积累器，返回非None时表示该处理了
                batch = acc.add("default_user", content)
                if batch:
                    _process_batch(from_user, batch)

            # 检查超时未冲洗的缓冲区
            for _uid, batch in acc.check_idle():
                target = last_sender["id"]
                print(f"[{name}] 消息合并({name}连续发多条)，统一回复 → {target[:40]}")
                _process_batch(target, batch)

            now = time.time()
            if now - last_delivery > 30:
                last_delivery = now
                try:
                    if backend is not None:
                        _deliver_via_backend(backend, bot, name)
                    else:
                        from engine import delivery as delivery_module
                        from core import database as db
                        count = db.count_pending_messages("default_user")
                        if count > 0:
                            def do_send(uid, text):
                                return send_chat_reply(bot, uid, text)
                            delivery_module.deliver_pending_messages(
                                "default_user", do_send, max_per_delivery=3
                            )
                except Exception:
                    pass
        except Exception as e:
            if _running:
                from core.logging_utils import log_error
                log_error(f"{name}.loop", str(e))
                time.sleep(5)

    # 走常驻服务时本地没起过自主思考引擎，不该由渠道去停它——
    # 那是 daemon 的职责，误停会让所有入口一起哑掉。
    if backend is None:
        try:
            from engine import autonomous as autonomous_module
            autonomous_module.stop_thought_engine()
        except Exception:
            pass


def run_state():
    """查看当前生命状态（优先向常驻服务查询，避免开出第二个写者）"""
    from core.banner import banner_state

    print(banner_state())
    print()

    backend = _resolve_backend("状态")
    if backend is not None:
        state = backend.state(SOUL_USER_ID) or {}
    else:
        from soul import SoulEngine
        engine = SoulEngine()
        engine.ensure_user(SOUL_USER_ID)
        state = engine.get_state(SOUL_USER_ID)

    print(state.get("mind_summary") or "")
    print()
    print(state.get("fate_summary") or "")
    print()
    print(f"{_cli_t('cli.life_state')}: {state.get('life_state') or ''}")
    identity = state.get("identity", {})
    if identity:
        print()
        print(f"【{_cli_t('cli.life_trait')}】{identity.get('signature', '')}")
        print(f"  {identity.get('essence', '')}")

    # MBTI 人格类型
    try:
        from engine import user_persona as up
        mbti = up.compute_mbti_from_db(SOUL_USER_ID)
        if mbti and mbti["confidence"] > 0.1:
            pct = round(mbti["confidence"] * 100)
            dims = mbti.get("dimensions", {})
            detail = " | ".join(
                f"{d['letter']}({d['raw']:.2f})" for d in dims.values()
            )
            print(f"\n【{_cli_t('cli.mbti_label')}】{mbti['type']}（{pct}% 置信度）")
            print(f"  维度: {detail}")
    except Exception:
        pass
    print()
    if state["recent_memories"]:
        print("【近期记忆】")
        for m in state["recent_memories"]:
            print(f"  - {m}")


def run_web(host=None, port=None, allow_remote=False):
    """Web 终端模式（浏览器）"""
    from clients.web import run_web as _run_web
    _run_web(host=host, port=port, allow_remote=allow_remote)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"

    # 授权管理命令不参与校验：否则 key 失效时连「激活」入口都进不去
    if mode in ("license", "licence", "activate"):
        run_license(sys.argv[2:])
        raise SystemExit(0)

    # ── 启动校验（一次）：结果只影响能力范围，绝不阻断启动 ──
    try:
        from core import license as _lic
        _lic.init()
    except Exception:
        pass

    if mode == "wx":
        if _license_ok("platform.wx", "微信 Bot 模式"):
            run_wx()
    elif mode == "qq":
        if _license_ok("platform.qq", "QQ Bot 模式"):
            run_qq()
    elif mode == "tg":
        if _license_ok("platform.tg", "Telegram Bot 模式"):
            run_tg()
    elif mode == "dc":
        if _license_ok("platform.dc", "Discord Bot 模式"):
            run_dc()
    elif mode == "im":
        if _license_ok("platform.im", "iMessage Bot 模式"):
            run_im()
    elif mode == "web":
        # 透传 web 参数：python main.py web --port 8080 --allow-remote
        # （不透传的话 clients/web.py 里的 --host/--port 永远用不上）
        import argparse as _argparse
        _wp = _argparse.ArgumentParser(prog="main.py web", add_help=False)
        _wp.add_argument("--host")
        _wp.add_argument("--port", type=int)
        _wp.add_argument("--allow-remote", action="store_true")
        _wa, _ = _wp.parse_known_args(sys.argv[2:])
        if _license_ok("platform.web", "Web 终端模式"):
            run_web(host=_wa.host, port=_wa.port, allow_remote=_wa.allow_remote)
    elif mode == "state":
        run_state()
    else:
        run_cli()
