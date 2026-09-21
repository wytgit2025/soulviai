# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
soulviai Web 终端
纯 Python 标准库，零依赖
浏览器实时同步终端输出，支持跨设备操作，无需密码
"""
import sys, os, json, time, threading, select, re, errno, shutil, shlex
try:
    import pty, fcntl, termios, tty          # POSIX 专属
    _HAS_PTY = True
except ImportError:                          # Windows：无 pty/termios
    pty = fcntl = termios = tty = None
    _HAS_PTY = False
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BUFFER = ""
BUFFER_LOCK = threading.Lock()
SSE_CLIENTS = []
SSE_LOCK = threading.Lock()
PTY_FD = None

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][0-9;]*[a-zA-Z]?|\x1b[\[\]()][0-9;]*[a-zA-Z]?|\x1b.')
CTRL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def strip_ansi(text):
    text = ANSI_RE.sub('', text)
    text = CTRL_RE.sub('', text)
    return text


# ── 引擎内部日志：挡在用户视野之外 ──
# 这些是引擎的诊断输出（理解层 / 心智 / 投递 …），给开发者和 Agent 看的东西。
# 直接摊进用户的对话框不只是噪音：SKILL.md 给 Agent 定的铁律是「别把内脏掏给
# 用户看」，网页这侧同理 —— 用户看到「[Phase1+2] 内心OS: …」的那一刻魔法就没了。
#
# 标签是从引擎源码里捞出来的（grep 'print.*\['），新增内部日志时把标签补进来。
# 用户可见的标签刻意不在表内：初始化 / 再见 / 对话出错 / 状态 / 终端 / soulviai
# （最后那个会报「已把旧数据搬到…」，是用户该知道的）。
_DIAG_TAGS = frozenset((
    "Sensors", "环境", "搜索", "Phase1+2", "Phase1+2·合并", "秒回", "后悔修正",
    "自主引擎", "记忆模块", "记忆", "投递", "投递控制", "元认知", "调度器",
    "联动", "世界模型", "社会模拟", "情绪沉默", "维度合并", "维度分裂",
    "向量记忆", "向量重建", "进化", "生命引擎", "成长事件", "触景翻涌",
    "衰减回忆", "渐进改写", "记忆合成", "记忆压缩", "灵魂取名", "投影学习",
    "AI", "Mind", "状态", "终端",
))

# 兜底：诊断行里也可能夹着真正需要用户知道的失败（模型挂了、没余额、超时）。
# 命中上面任何一个词就一律放行 —— 宁可漏一条内部日志，也不能让用户对着空白猜。
_KEEP_MARKERS = ("失败", "错误", "出错", "异常", "Traceback", "Error", "error",
                 "401", "403", "429", "超时", "timeout", "余额", "额度", "quota")


def _is_diag(line: str) -> bool:
    """这一行是不是该挡掉的引擎内部日志。"""
    s = (line or "").strip()
    if not s.startswith("[") or "]" not in s:
        return False
    if any(mark in s for mark in _KEEP_MARKERS):
        return False
    return s[1:s.index("]")] in _DIAG_TAGS


def _drop_diag(text: str) -> str:
    """按行丢掉内部日志，其余原样保留。

    只影响推给浏览器的内容，不影响日志或引擎本身。print() 写 PTY 是整行输出
    （PTY 行缓冲），所以切块边界基本都落在行尾；万一真被切断，最坏结果是漏出一条
    内部日志，不会丢掉用户可见的东西。
    """
    return "\n".join(ln for ln in text.split("\n") if not _is_diag(ln))


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>soulviai 终端</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0a;color:#e0e0e0;font-family:'SFMono-Regular','Cascadia Code','JetBrains Mono','Fira Code','Consolas',monospace;font-size:13px;overflow:hidden;height:100vh;display:flex;flex-direction:column}
.wrap{display:flex;flex-direction:column;height:100vh}
.bar{display:flex;align-items:center;gap:8px;padding:6px 14px;background:#111;border-bottom:1px solid #222;-webkit-user-select:none;user-select:none;flex-shrink:0}
.bar .d{width:10px;height:10px;border-radius:50%}
.bar .d.g{background:#4ade80;box-shadow:0 0 6px #4ade8044}
.bar .d.r{background:#ef4444;box-shadow:0 0 6px #ef444444}
.bar .t{flex:1;font-size:12px;color:#888;letter-spacing:.5px}
.bar .t b{color:#4ade80;margin-right:4px}
.bar .s{font-size:10px;color:#555}
.out{flex:1;overflow-y:auto;padding:10px 16px;white-space:pre-wrap;word-break:break-all;line-height:1.6;font-size:13px;color:#c0c0c0;scroll-behavior:smooth}
.inp{display:flex;align-items:center;gap:6px;padding:6px 14px 10px;border-top:1px solid #1a1a1a;flex-shrink:0;background:#0d0d0d}
.inp .p{color:#4ade80;font-size:13px;opacity:.6}
.inp input{flex:1;background:transparent;border:none;color:#e0e0e0;font-family:inherit;font-size:13px;outline:none}
.inp input::placeholder{color:#333}
.inp input:disabled{opacity:0.3}
.hint{display:none;padding:0 16px 6px 16px;font-size:12px;color:#4ade80;opacity:.7;flex-shrink:0;background:#0d0d0d;letter-spacing:.5px}
.hint.on{display:block}
.hint i{display:inline-block;width:5px;height:5px;border-radius:50%;background:#4ade80;margin-right:6px;vertical-align:middle;animation:blink 1.1s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:.2;transform:scale(.85)}50%{opacity:1;transform:scale(1)}}
@media(max-width:600px){.out{padding:8px 12px;font-size:12px}.inp{padding:4px 12px 8px}.hint{padding:0 12px 6px 12px}}
::selection{background:#4ade80;color:#000}
</style>
</head>
<body>
<div class="wrap">
<div class="bar"><div class="d g" id="dot"></div><div class="t"><b>✦</b> soulviai</div><div class="s" id="sts">connecting</div></div>
<div class="out" id="out"></div>
<div class="hint" id="hint"><i></i><span id="hinttxt"></span></div>
<div class="inp"><div class="p"><span>$</span></div><input type="text" id="inp" placeholder="type..." disabled onkeydown="if(event.key==='Enter')send()"></div>
</div>
<script>
var es,buf='',el=document.getElementById('out'),st=document.getElementById('sts');
var hintEl=document.getElementById('hint'),hintTx=document.getElementById('hinttxt');
var hintNow='';
// 状态机：发出后「在想」→ 第一句回来「正在输入」→ 提示符回来收工。
// 没有它，从发送到出话之间那段（实测 8.7 秒）屏幕是完全静止的，用户只会觉得卡死；
// 有了它，后面那几段刻意留的 1.5 秒拟人延迟也从「卡住」变成「ta 在打字」——
// 这段延迟是人设的一部分，不该删，该让它可读。
function setHint(t){
if(t===hintNow)return;
hintNow=t;
if(!t){hintEl.className='hint';return}
hintTx.textContent=t;
hintEl.className='hint on';
}
connect();
function connect(){
st.textContent='connected';
es=new EventSource('/api/stream');
es.onmessage=function(e){
if(e.data==='__PING__')return;
// 只认对话行与提示符；引擎的内部日志（[Phase1+2]…）不该左右这个状态
if(e.data.indexOf('数字生命')>=0)setHint('ta 正在输入');
if(/^你:\\s*$/.test(e.data))setHint('');
buf+=e.data+'\\n';
el.textContent=buf;
el.scrollTop=el.scrollHeight;
document.getElementById('inp').disabled=false;
document.getElementById('inp').focus()
};
es.onerror=function(){st.textContent='disconnected';document.getElementById('dot').className='d r'}
}
function send(){
var i=document.getElementById('inp'),v=i.value;
if(!v)return;
i.value='';
setHint('ta 在想');
fetch('/api/input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data:v+'\\n'})})
}
</script>
</body>
</html>"""


def _read_pty():
    global BUFFER, PTY_FD
    while PTY_FD is not None:
        try:
            r, _, _ = select.select([PTY_FD], [], [], 0.5)
            if r:
                data = os.read(PTY_FD, 4096)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                text = strip_ansi(text)
                text = _drop_diag(text)
                if text:
                    _append(text)
                    _send(text)
        except (OSError, ValueError):
            break


def _append(text):
    """把文本并入回放缓冲区。

    单独抽成函数是因为 BUFFER 是模块级全局：在别的函数里直接写 `BUFFER += x`
    而没有 `global BUFFER`，Python 会把它当成局部变量并抛 UnboundLocalError
    （回显那次就是这么炸的）。声明只在这一处，调用方不必再记得。
    """
    global BUFFER
    with BUFFER_LOCK:
        BUFFER += text


def _send(text):
    dead = []
    with SSE_LOCK:
        for c in SSE_CLIENTS:
            try:
                for line in text.split("\n"):
                    if not line:
                        continue
                    c.wfile.write(b"data: " + line.encode("utf-8") + b"\n")
                c.wfile.write(b"\n")
                c.wfile.flush()
            except Exception:
                dead.append(c)
        for c in dead:
            try:
                SSE_CLIENTS.remove(c)
            except ValueError:
                pass


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        elif path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with SSE_LOCK:
                SSE_CLIENTS.append(self)
            with BUFFER_LOCK:
                if BUFFER:
                    _send(BUFFER)
            try:
                while self in SSE_CLIENTS:
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except Exception:
                        break
                    time.sleep(10)
            finally:
                with SSE_LOCK:
                    try:
                        SSE_CLIENTS.remove(self)
                    except ValueError:
                        pass
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/input":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            cmd = data.get("data", "")
            if cmd and PTY_FD is not None:
                try:
                    os.write(PTY_FD, cmd.encode("utf-8"))
                except OSError:
                    pass
                # 回显用户输入。child_shell() 把 PTY 设成了 raw 模式（见那里的注释），
                # 内核因此**不回显**输入；而前端的输入框在发送后立刻清空
                # （i.value=''）。两件事叠在一起，用户发出去的内容在屏幕上完全
                # 不出现 —— 看起来就像输入掉进了黑洞，连发没发出去都判断不了。
                # 回显也写进 BUFFER，这样中途刷新页面/重连的人还能看到自己说过的话。
                echo = cmd if cmd.endswith("\n") else cmd + "\n"
                _append(echo)
                _send(echo)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address))
        t.daemon = True
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


# ── 项目根 / 解释器解析（优先级与 scripts/soulviaictl.py 对齐）──
_HERE = os.path.dirname(os.path.abspath(__file__))          # <项目>/clients
_RUNTIME_ROOT = os.path.dirname(_HERE)                      # <项目>
_SKILL_ROOT = os.path.dirname(_RUNTIME_ROOT)                # 技能根


def _strip_comment(raw):
    """去掉行尾注释。

    只把「行首或空白之后的 #」当注释，且引号内的 # 不算 —— 否则
    `python: /Volumes/a#b/bin/python` 会被截成 `/Volumes/a`。
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


def _flat_config():
    """读技能根的 config.yaml（扁平 `key: value`，与 soulviaictl 同格式同语义）。

    语义基准是 scripts/soulviaictl.py:parse_flat_yaml。clients/ 刻意不 import
    core/（core/__init__ 会包装 sys.stdout），所以这里自留一份实现 ——
    **改这里就要同步改 soulviaictl 与 core/paths 那两份**。
    """
    path = os.environ.get("SOULVIAI_CONFIG") or os.path.join(_SKILL_ROOT, "config.yaml")
    data = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = _strip_comment(raw).rstrip()
                if not line.strip() or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                # 只有成对的引号才剥：`"it's"` 应得到 `it's`，
                # 贪心地 strip('"').strip("'") 会把它啃成 `its`。
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if v.lower() in ("true", "false"):
                    data[k] = (v.lower() == "true")
                else:
                    data[k] = v
    except Exception:      # 配置坏了也要能降级跑
        pass
    return data


def resolve_project_root():
    """引擎根目录：SOULVIAI_PROJECT_ROOT 优先（与 soulviaictl 一致），否则技能自带 engine/。"""
    explicit = os.environ.get("SOULVIAI_PROJECT_ROOT")
    if not explicit:
        return _RUNTIME_ROOT
    path = os.path.abspath(os.path.expanduser(explicit))
    if not (os.path.isfile(os.path.join(path, "soulviai.py"))
            and os.path.isdir(os.path.join(path, "engine"))):
        print("[Web终端] 警告：SOULVIAI_PROJECT_ROOT=%s 不像数字生命项目" % path,
              file=sys.stderr)
    return path


def resolve_python(project_root):
    """挑一个能跑引擎的解释器，顺序与 soulviaictl:resolve_python 对齐。

    原实现只认 venv/.venv，会无视 SOULVIAI_PYTHON 与 config.yaml 的 python，
    导致用 soulviaictl 配好的解释器在 web 模式下反而不生效。
    """
    cfg = _flat_config()
    candidates = [
        os.environ.get("SOULVIAI_PYTHON"),
        cfg.get("python"),
        os.path.join(project_root, ".venv", "bin", "python"),
        os.path.join(project_root, "venv", "bin", "python"),
        sys.executable,
    ]
    for name in ("python3.13", "python3.12", "python3.11", "python3.10", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for cand in candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return sys.executable or "python3"


def child_shell():
    """子进程：启动 soulviai 终端对话"""
    project_root = resolve_project_root()
    python = resolve_python(project_root)
    # raw 模式：关掉行缓冲（前端一次就 post 一整行）与 OPOST，让输出保持裸 \n，
    # 前端 pre-wrap 直接渲染即可，不会掺进 \r。
    # 代价是内核不再回显输入 —— 用户输入的回显由 do_POST 里的 /api/input 负责，
    # 改成 setcbreak 之类不会恢复回显，删或改这里前先看那一段。
    tty.setraw(0)
    os.chdir(project_root)

    shell = os.environ.get("SHELL", "/bin/bash")
    cmd = "cd %s && exec %s main.py cli" % (
        shlex.quote(project_root), shlex.quote(python))

    sys.stdout.write("\r\n")
    sys.stdout.flush()

    os.execvp(shell, [shell, "-c", cmd])
    os._exit(1)


def _start_pty():
    global PTY_FD
    pid, fd = pty.fork()
    if pid == 0:
        child_shell()
    else:
        PTY_FD = fd


def _try_bind(host, port, max_retries=5):
    """尝试绑定端口，被占用就顺延到下一个。

    只换端口、不清场 —— 与 engine/core/daemon_link.py 的范式一致：端口被占
    不碰别人的进程。原实现会用 `lsof -ti :port` + `kill -9` 杀掉占用者，
    那可能是用户自己的另一个服务，属于越界行为。
    """
    for _ in range(max_retries):
        try:
            return ThreadedHTTPServer((host, port), Handler), port
        except OSError as exc:
            # macOS 的 EADDRINUSE 是 48，不是 Linux 的 98 —— 原实现硬编码 98，
            # 在 mac 上这个分支永远进不去，端口被占会直接抛错退出。
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES):
                raise
            print("[Web终端] 端口 %d 不可用（%s），尝试 %d"
                  % (port, exc.strerror or exc.errno, port + 1))
            port += 1
    raise OSError("无法绑定端口（连续尝试了 %d 个）" % max_retries)


def _display_host(host):
    """把 0.0.0.0 / :: 换成真正点得开的地址（打印 0.0.0.0 的 URL 常打不开）。"""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def run_web(host=None, port=None, allow_remote=False):
    global PTY_FD
    if not _HAS_PTY:
        print("[Web终端] 该模式依赖 POSIX 的 pty/termios，Windows 下不可用。")
        print("[Web终端] 请改用命令行模式：python main.py cli")
        return

    # 取值优先级：调用方参数 > 环境变量 > config.yaml > 内建默认（只监听本机）。
    # config.yaml 这一层原本是缺的：web_host / web_port 写在配置里完全不生效，
    # 把端口从 5000 改掉了照样绑 5000 —— 而同一份配置里的 python 是生效的
    # （resolve_python 读它），用户很容易以为自己改错了地方。
    # 注意「读得到」不等于「放行」：非回环 host 仍在下面被拦下，只是现在被拦下时
    # 报的是配置里那个地址，而不是悄悄退回 127.0.0.1。
    _cfg = _flat_config()
    if host is None:
        host = (os.environ.get("SOULVIAI_WEB_HOST")
                or _cfg.get("web_host") or "127.0.0.1")
    if port is None:
        try:
            port = int(os.environ.get("SOULVIAI_WEB_PORT")
                       or _cfg.get("web_port") or 5000)
        except ValueError:
            port = 5000

    # 与常驻服务同一套安全默认：非回环地址必须显式放行
    if allow_remote:
        host = "0.0.0.0"
    elif host not in ("127.0.0.1", "::1", "localhost"):
        print("[Web终端] 拒绝在非回环地址 %s 上监听。" % host)
        print("[Web终端] 本模式没有鉴权，暴露到网络等于把 ta 的对话与记忆交出去；")
        print("[Web终端] 确有需要请显式加 --allow-remote。")
        return

    server, port = _try_bind(host, port)
    print("[Web终端] http://%s:%d" % (_display_host(host), port))
    if host not in ("127.0.0.1", "::1", "localhost"):
        print("[Web终端] ⚠ 正在监听所有网卡且无鉴权，请确认网络环境可信")
    print("[Web终端] 按 Ctrl+C 停止")
    print()

    pty_thread = threading.Thread(target=_start_pty, daemon=True)
    pty_thread.start()
    time.sleep(0.5)

    reader = threading.Thread(target=_read_pty, daemon=True)
    reader.start()

    # 自动打开浏览器。放在 serve_forever() 之前、端口已经 bind 之后：
    # 双击启动那条链路的目标用户不看命令行，只给一行 http://… 等于没告诉他下一步
    # 该干什么。放在这里还有个好处 —— socket 已经 listen，浏览器的首次请求会排在
    # backlog 里，等 serve_forever() 一跑就立刻被接走，不会看到「无法连接」。
    # 失败一律忽略（无图形界面、容器里没有 xdg-open 都很正常）；设
    # SOULVIAI_NO_BROWSER=1 可跳过 —— 某些环境里拉浏览器会带出一串无用的报错。
    if not os.environ.get("SOULVIAI_NO_BROWSER"):
        url = "http://%s:%d" % (_display_host(host), port)
        opened = False
        try:
            import webbrowser
            opened = bool(webbrowser.open(url))
        except Exception:
            opened = False
        if opened:
            print("[Web终端] 已在浏览器中打开。")
        else:
            print("[Web终端] 没能自动打开浏览器，请手动访问上面的地址。")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Web终端] 正在停止...")
        server.shutdown()
    finally:
        if PTY_FD is not None:
            try:
                os.close(PTY_FD)
            except OSError:
                pass
            PTY_FD = None


if __name__ == "__main__":
    import argparse
    a = argparse.ArgumentParser(description="soulviai Web 终端（浏览器）")
    a.add_argument("--host", help="监听地址（默认 127.0.0.1，只允许本机访问）")
    a.add_argument("--port", type=int, help="监听端口（默认 5000）")
    a.add_argument("--allow-remote", action="store_true",
                   help="允许监听非回环地址（无鉴权，仅网络可信时使用）")
    args = a.parse_args()
    run_web(host=args.host, port=args.port, allow_remote=args.allow_remote)
