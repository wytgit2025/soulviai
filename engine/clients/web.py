# Copyright (c) 2026 soul-skill 项目作者
# SPDX-License-Identifier: MIT

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
@media(max-width:600px){.out{padding:8px 12px;font-size:12px}.inp{padding:4px 12px 8px}}
::selection{background:#4ade80;color:#000}
</style>
</head>
<body>
<div class="wrap">
<div class="bar"><div class="d g" id="dot"></div><div class="t"><b>✦</b> soulviai</div><div class="s" id="sts">connecting</div></div>
<div class="out" id="out"></div>
<div class="inp"><div class="p"><span>$</span></div><input type="text" id="inp" placeholder="type..." disabled onkeydown="if(event.key==='Enter')send()"></div>
</div>
<script>
var es,buf='',el=document.getElementById('out'),st=document.getElementById('sts');
connect();
function connect(){
st.textContent='connected';
es=new EventSource('/api/stream');
es.onmessage=function(e){
if(e.data==='__PING__')return;
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
                if text:
                    with BUFFER_LOCK:
                        BUFFER += text
                    _send(text)
        except (OSError, ValueError):
            break


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


# ── 项目根 / 解释器解析（优先级与 scripts/soulctl.py 对齐）──
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
    """读技能根的 config.yaml（扁平 `key: value`，与 soulctl 同格式同语义）。

    语义基准是 scripts/soulctl.py:parse_flat_yaml。clients/ 刻意不 import
    core/（core/__init__ 会包装 sys.stdout），所以这里自留一份实现 ——
    **改这里就要同步改 soulctl 与 core/paths 那两份**。
    """
    path = os.environ.get("SOUL_CONFIG") or os.path.join(_SKILL_ROOT, "config.yaml")
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
    """引擎根目录：SOUL_PROJECT_ROOT 优先（与 soulctl 一致），否则技能自带 engine/。"""
    explicit = os.environ.get("SOUL_PROJECT_ROOT")
    if not explicit:
        return _RUNTIME_ROOT
    path = os.path.abspath(os.path.expanduser(explicit))
    if not (os.path.isfile(os.path.join(path, "soul.py"))
            and os.path.isdir(os.path.join(path, "engine"))):
        print("[Web终端] 警告：SOUL_PROJECT_ROOT=%s 不像数字生命项目" % path,
              file=sys.stderr)
    return path


def resolve_python(project_root):
    """挑一个能跑引擎的解释器，顺序与 soulctl:resolve_python 对齐。

    原实现只认 venv/.venv，会无视 SOUL_PYTHON 与 config.yaml 的 python，
    导致用 soulctl 配好的解释器在 web 模式下反而不生效。
    """
    cfg = _flat_config()
    candidates = [
        os.environ.get("SOUL_PYTHON"),
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

    # 取值优先级：调用方参数 > 环境变量 > 内建默认（默认只监听本机）
    if host is None:
        host = os.environ.get("SOUL_WEB_HOST") or "127.0.0.1"
    if port is None:
        try:
            port = int(os.environ.get("SOUL_WEB_PORT") or 5000)
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
