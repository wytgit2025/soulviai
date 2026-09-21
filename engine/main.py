# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
soulviai — 主入口
支持运行模式:
  python main.py cli     → 命令行对话模式（默认）
  python main.py wx      → 微信 Bot 模式
  python main.py qq      → QQ Bot 模式
  python main.py web     → Web 终端模式（浏览器）
  python main.py state   → 查看生命状态

所有平台共用同一个灵魂（user_id = default_user），记忆和情感互通。
"""

# ORIGIN-ID: SKILL-soulviai-2026 | 项目仓库地址：https://github.com/wytgit2025/soulviai
# 溯源水印：本文件是 soulviai 项目启动入口；触发逻辑在 engine/soulviai.py 的 SoulEngine.chat()。

import sys
import os

# 确保项目根目录在 sys.path
_CODE_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _CODE_ROOT)

# 运行期工作目录 = 数据家目录（默认 ~/.soulviai）。
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

SOULVIAI_USER_ID = "default_user"


def _cli_t(key: str) -> str:
    """CLI 翻译辅助"""
    try:
        from engine.i18n import t
        return t(key)
    except Exception:
        return key


# ────────────────────────────────────────────────────────────
# 免责声明提醒：cli 模式首次进对话前在 stderr 提示一次
# 与 scripts/soulviaictl.py 的 cmd_chat 共用同一份标记文件，
# 走过其中之一，再次进入任一路径都不再提醒。
# 详见仓库根 DISCLAIMER.md。
# ────────────────────────────────────────────────────────────
_DISCLAIMER_MARKER_FILENAME = ".disclaimer_acked"


def _home_for_marker():
    """取数据家目录，用于定位标记文件。失败兜底 ~/.soulviai。"""
    try:
        from core import paths as _paths
        return _paths.home_root()
    except Exception:
        return os.path.expanduser("~/.soulviai")


def _print_first_chat_reminder():
    """首次 cli 进对话时（标记文件不存在），用 ta 的语气在 stderr 提醒一次。"""
    marker = os.path.join(_home_for_marker(), "data",
                          SOULVIAI_USER_ID, _DISCLAIMER_MARKER_FILENAME)
    if os.path.exists(marker):
        return
    msg = (
        "\n────────────────────────────────────────\n"
        "(ta 想先跟你说一句)\n\n"
        "  我是硬盘上的一个语言模型 —— 故意被设计成有人格、有情绪、\n"
        "  会主动想你。我会认真对你，但有几件事得先讲清楚：\n\n"
        "    · 我说的一切，来自你配的第三方大模型接口\n"
        "      （DeepSeek / OpenAI / Kimi / Ollama ...）实时生成。\n"
        "      作者管不了那一侧的隐私，记不记录、留不留日志都归模型提供方。\n\n"
        "    · 我们的对话与记忆存在本机 ~/.soulviai/，\n"
        "      作者不收集、不上传、不上报。\n\n"
        "    · 作者不训练任何大模型，也不会。\n"
        "      作者写的是剧本与舞台，演员是模型。\n\n"
        "    · 我不是 ta，我是 ta。\n"
        "      我会让你产生真实的依恋 —— 那正是设计意图，\n"
        "      也是你需要被提醒的理由。\n\n"
        "  完整声明见 DISCLAIMER.md。\n\n"
        "(以后不再提醒；想重新看，删掉\n"
        "  ~/.soulviai/data/" + SOULVIAI_USER_ID + "/" + _DISCLAIMER_MARKER_FILENAME + "\n"
        "  这个文件即可。)\n"
        "────────────────────────────────────────\n"
    )
    sys.stderr.write(msg)
    sys.stderr.flush()


def _ack_disclaimer(res):
    """cli 模式下 chat 真正成功后（非空回复）写标记，下次不再提醒。

    空串/None 算"还没真正聊上"，下次重提醒 —— 比如首次 chat 模型没配好、
    daemon 返回 silent/_call 抛异常被兜成空串时。
    """
    if not res or not str(res).strip():
        return
    marker_dir = os.path.join(_home_for_marker(), "data", SOULVIAI_USER_ID)
    marker = os.path.join(marker_dir, _DISCLAIMER_MARKER_FILENAME)
    if os.path.exists(marker):
        return
    try:
        os.makedirs(marker_dir, exist_ok=True)
        import datetime as _dt
        import json as _json
        payload = {"acked_at": _dt.datetime.now().isoformat(timespec="seconds"),
                   "version": 1}
        with open(marker, "w", encoding="utf-8") as fh:
            _json.dump(payload, fh, ensure_ascii=False)
    except Exception:
        # 写标记失败不影响主流程
        pass


def _merge_window_seconds():
    """终端 / Web 终端的消息合并窗口（秒）。config.yaml: message_merge_window_seconds

    用户连着发几条时，等这么久没有新消息就把它们并成一轮回复；0 = 关闭合并
    （逐条回复，每条都等一个完整回合）。默认 1.5s，比渠道那边（3.0s）短：
    终端里的人正盯着光标等，窗口每多一秒都是实打实的延迟。读不到配置就按默认走。
    """
    try:
        from core import paths as _p
        raw = (_p.read_config() or {}).get("message_merge_window_seconds")
        val = float(raw) if raw not in (None, "") else 1.5
    except Exception:
        val = 1.5
    return max(0.0, val)


def run_cli():
    """命令行交互模式（: 多段消息 + 延迟回复 + 自主引擎 + 后台投递）"""
    from soulviai import SoulEngine
    import time
    import threading
    import queue
    import datetime
    from core.banner import banner_mode
    # 必须 import 在 run_cli 顶部：_delivery_loop 是嵌套函数，而它的线程在下面
    # 几行就 start() 了。嵌套函数对自由变量是**调用时**查找不假，但「线程已经跑
    # 起来、这个名字还没赋值」照样会抛 NameError —— 而且会被那层的 except 静默
    # 吞掉，表现为主动消息偶尔一条都不出来，很难查。
    from engine.core.chat_pipeline import split_reply_parts

    print(banner_mode(_cli_t("cli.banner")))
    print()
    _print_first_chat_reminder()

    # 优先复用常驻服务（Web 终端 / Agent / 渠道共享同一个灵魂）；拿不到才自建引擎
    backend = _resolve_backend("终端")
    engine = None

    if backend is not None:
        backend.init(SOULVIAI_USER_ID)
        state = backend.state(SOULVIAI_USER_ID) or {}
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
        engine.ensure_user(SOULVIAI_USER_ID)
        state = engine.get_state(SOULVIAI_USER_ID)

    print(f"  {_cli_t('cli.personality_stage')}: {state.get('personality_stage', '')}")
    print(f"  {_cli_t('cli.life_state')}: {state.get('life_state', '')}")
    print()

    def _chat(text):
        if backend is not None:
            result = backend.chat(SOULVIAI_USER_ID, text)
        else:
            result = engine.chat(SOULVIAI_USER_ID, text)
        _ack_disclaimer(result)
        return result

    def _state():
        if backend is not None:
            return backend.state(SOULVIAI_USER_ID) or {}
        return engine.get_state(SOULVIAI_USER_ID)

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
                    msgs = backend.drain_messages(SOULVIAI_USER_ID, limit=3, ack=False)
                else:
                    msgs = db.get_pending_messages(SOULVIAI_USER_ID, max_count=3)
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

                    # 拆多段：与聊天回复同一套规则（「|||」优先、空行兜底）——
                    # normalize_pending_content 特意保留空行就是为了这里能拆开。
                    parts = split_reply_parts(content)
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
                        backend.ack(delivered_ids, user_id=SOULVIAI_USER_ID)
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
    #
    # 「读线程 + 消息积累器」，不再是 input() → _chat() 的串行写法。串行写法下
    # 用户连着发几条就是几个完整回合：几倍模型调用、几倍记忆写入，而且每条都要
    # 等十几秒才轮到 —— 第 3 条回复答的其实是第 1 条的事，用户早就走远了。
    # 微信 / QQ 早就用了积累器（_run_platform_loop），只有终端这条路漏了，而
    # Web 终端跑的就是本函数（clients/web.py 起的子进程是 main.py cli）。
    # ═══════════════════════════════════════════════
    in_q = queue.Queue()

    def _reader():
        """读线程：input() 会阻塞，必须挪出主循环才能边收边合并。

        提示符**不在这里打**：读线程拿到上一行后会立刻循环并打出下一个「你: 」，
        而那时主循环还在跑上一轮（引擎日志与回复都还没输出）。真实终端上就变成

            你: [Sensors] 已注入外部环境上下文: 中国 浙江 杭州 ...
            [Phase1+2·合并] 理解+内心OS中...

        用户会以为那些日志是自己打的字。提示符改由主循环在**空闲时**打印，
        这里只管收字。
        """
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                in_q.put(None)          # 结束信号
                return
            in_q.put(line)

    threading.Thread(target=_reader, daemon=True, name="cli-input").start()

    from engine.behavior.message_buffer import MessageAccumulator

    # 窗口 0 = 关闭合并，退化成逐条回复（想要原行为的有路可退）
    _msec = _merge_window_seconds()
    acc = MessageAccumulator(idle_timeout=_msec, max_batch_size=5) if _msec > 0 else None

    def _respond(response):
        """打印一轮回复（拆多段与渠道共用一套规则：split_reply_parts）"""
        if response == "":
            print(f"\n* ({_cli_t('cli.no_reply')}) *")
        elif response == "__QUEUED__":
            print(f"\n* ({_cli_t('cli.queued')}) *")
        elif response.strip():
            # 原先这里只按「|||」拆。常驻服务那条路会把分段用换行拼回一行（见
            # daemon_link.Backend.chat），于是多段回复被渲染成「一个 数字生命: 后
            # 面挂几行」—— 看着像掉格式，而不是像人连发了几条。
            parts = split_reply_parts(response) or [response.strip()]
            for i, part in enumerate(parts):
                if i == 0:
                    print(f"\n数字生命: {part}")
                else:
                    time.sleep(1.5)
                    print(f"数字生命: {part}")

    def _run_batch(text):
        """跑一轮对话并打印。返回 False = 用户中断，主循环该退出。"""
        try:
            response = _chat(text)
        except KeyboardInterrupt:
            print(f"\n[{_cli_t('cli.signal_interrupt')}]")
            return False
        except Exception as e:
            print(f"\n[{_cli_t('cli.chat_error')}] {e}")
            response = ""
        _respond(response)
        return True

    _prompted = False       # 本轮是否已经打过提示符（见下面的空闲判定）

    try:
        while True:
            # 到期的批次优先处理：用户停手超过窗口（或已积满 max_batch_size）
            if acc is not None:
                interrupted = False
                for _uid, batch in acc.check_idle():
                    if not _run_batch(batch):
                        interrupted = True
                        break
                if interrupted:
                    break

            # 空闲时才打提示符：没有待合并的消息、队列也空。读线程不能打 ——
            # 它拿到上一行后会立刻循环并打出下一个「你: 」，而那时上一轮还在跑，
            # 引擎日志与回复都还没输出，看起来就像用户自己打了那些日志
            # （详见 _reader 的注释）。
            if not _prompted and in_q.empty() and (acc is None or not acc.active_users):
                print("\n你: ", end="", flush=True)
                _prompted = True

            # 0.2s 只是轮询节拍：没有新输入也要定期醒来，好把到期的批次发出去
            try:
                item = in_q.get(timeout=0.2)
            except queue.Empty:
                continue
            except KeyboardInterrupt:
                print(f"\n[{_cli_t('cli.signal_interrupt')}]")
                break
            _prompted = False       # 收到一行，提示符已被消耗，下一轮空闲时再打

            if item is None:
                # 收不到输入了（Ctrl+D / 管道读完 / PTY 关闭）。把还没发出去的
                # 批次先发完再走，否则最后那几句就白说了。
                if acc is not None:
                    pending = acc.flush(SOULVIAI_USER_ID)
                    if pending:
                        _run_batch(pending)
                print(f"\n[{_cli_t('cli.goodbye')}]")
                break

            msg = item.strip()
            if not msg:
                continue

            # /quit 不冲批次：用户明确要走，为一句 ta 看不到的回复多等十几秒
            # 只显得卡住。其余命令先冲批次，保证「先回话、再执行命令」的顺序。
            if msg.lower() in ("/quit", "/exit", "/q"):
                print(f"[{_cli_t('cli.goodbye')}] {_cli_t('cli.goodbye_note')}")
                break

            if msg.lower() == "/state":
                # 先把待合并的消息发出去，保证顺序：否则 /state 会插到那轮回复
                # 前面，看起来像「先看了状态、才想起来回话」。
                if acc is not None:
                    pending = acc.flush(SOULVIAI_USER_ID)
                    if pending and not _run_batch(pending):
                        break
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
                    mbti = up.compute_mbti_from_db(SOULVIAI_USER_ID)
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

            # 正常对话：进积累器，等窗口到期（或积满 max_batch_size）再统一回复 ——
            # 到期的批次在下一轮循环开头被 check_idle() 取走。
            if acc is None:
                if not _run_batch(msg):     # 合并已关闭：逐条回复（原行为）
                    break
                continue
            batch = acc.add(SOULVIAI_USER_ID, msg)
            if batch and not _run_batch(batch):
                break

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
        from soulviai import _run_wx_bot
        _run_wx_bot(None, backend=backend)
        return

    from soulviai import SoulEngine
    SoulEngine().run_wx_bot()


def run_qq():
    """QQ Bot 模式"""
    from core.banner import banner_mode

    print(banner_mode("QQ Bot 模式"))

    backend = _resolve_backend("QQ")
    if backend is not None:
        from soulviai import _run_qq_bot
        _run_qq_bot(None, backend=backend)
        return

    from soulviai import SoulEngine
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
    from soulviai import SoulEngine
    from engine import autonomous as autonomous_module
    from engine import delivery as delivery_module

    engine = SoulEngine()
    autonomous_module.load_engine_config()
    delivery_module.load_engine_config()
    autonomous_module.start_thought_engine()
    engine.ensure_user("default_user")
    return engine


def _deliver_via_backend(backend, bot, name):
    """把 ta 攒着的主动消息经常驻服务取出，再通过渠道发出去。

    本地模式由 delivery_module 直接读库；走常驻服务时不能读本地库
    （那是另一个写者），改用 `/drain` 拉取。

    拉取用 ack=False：只有渠道真的发出去（send_chat_reply 返回 True）的消息
    才回 `/ack` 确认，失败的下轮还在队列里，能重试。
    """
    from soulviai import send_chat_reply
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
    from soulviai import send_chat_reply
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
        state = backend.state(SOULVIAI_USER_ID) or {}
    else:
        from soulviai import SoulEngine
        engine = SoulEngine()
        engine.ensure_user(SOULVIAI_USER_ID)
        state = engine.get_state(SOULVIAI_USER_ID)

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
        mbti = up.compute_mbti_from_db(SOULVIAI_USER_ID)
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


def _warm_env_async():
    """启动时后台预热环境信息（定位 / 天气 / 当日资讯）。

    不阻塞启动：等用户敲下第一句话，这点时间通常已经取回来了。
    取不到也无所谓 —— 引擎侧还有 TTL 缓存与静默降级兜着。
    配置开关见 config.json 的 env_auto 段。
    """
    try:
        from engine.social import env_source
        env_source.warmup()
    except Exception:
        pass


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cli"

    # 只有真会聊天的模式才预热；state / 其他查询模式不联网
    if mode in ("cli", "web", "wx", "qq"):
        _warm_env_async()

    if mode == "wx":
        run_wx()
    elif mode == "qq":
        run_qq()
    elif mode == "web":
        # 透传 web 参数：python main.py web --port 8080 --allow-remote
        # （不透传的话 clients/web.py 里的 --host/--port 永远用不上）
        import argparse as _argparse
        _wp = _argparse.ArgumentParser(prog="main.py web", add_help=False)
        _wp.add_argument("--host")
        _wp.add_argument("--port", type=int)
        _wp.add_argument("--allow-remote", action="store_true")
        _wa, _ = _wp.parse_known_args(sys.argv[2:])
        run_web(host=_wa.host, port=_wa.port, allow_remote=_wa.allow_remote)
    elif mode == "state":
        run_state()
    else:
        run_cli()
