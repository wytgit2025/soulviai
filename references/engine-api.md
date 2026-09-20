# 引擎接口契约与排障

## 调用链路

```
soulctl.py                         engine_bridge.py                     项目引擎
（任意 python3 ≥3.8）                （必须用项目的解释器 ≥3.10）
   │                                    │                                  │
   │ 1. 读 config.yaml 定位 project_root │                                  │
   │ 2. 探测可用解释器                   │                                  │
   │ 3. 优先 POST/GET 常驻服务 ──────────┼──→ 127.0.0.1:8765 (serve 模式)    │
   │    常驻不在 → 冷启动 subprocess ─────┼──→ 单次命令                       │
   │                                    │  `from soul import SoulEngine` ──→│
   │                                    │  ChatPipeline.run(user, text) ───→│
   │ 4. 输出单行 JSON                    │                                  │
```

**为什么要两层**：`soulctl.py` 用系统自带 python3 就能跑（纯标准库）；真正的引擎必须用项目的解释器、且在项目根目录下运行（数据全是相对路径 `data/...`）。这层分离让「随便哪个工具」都能调起这台引擎。

### config.yaml 的格式与三处解析器

`config.yaml` 是**扁平 `key: value`**（支持 `#` 注释与引号字符串），由自带的极简解析器读取，
**不依赖 PyYAML** —— 技能与引擎都得在「纯标准库」下跑起来，多一个依赖就多一道装不上的门槛。

同一份格式有三处独立实现，不能合并：`scripts/` 与 `engine/` 必须能各自单独运行，
而 `clients/` 也不 import `core/`（`core/__init__` 会包装 `sys.stdout`）。

| 实现 | 谁在用 |
|---|---|
| `scripts/soulctl.py` → `parse_flat_yaml` | 启动器（**语义基准**） |
| `engine/core/daemon_link.py` → `_read_cfg` | 聊天渠道 / Web 端判断常驻服务地址与 token |
| `engine/clients/web.py` → `_flat_config` | Web 终端解析 `python` / `web_host` / `web_port` |

三者**必须语义一致**，踩过的坑：

- `#` 只当「行首或空白之后」的注释，且引号内的 `#` 不算 —— 裸 `split("#")` 会把
  `daemon_token_file: /Volumes/a#b/token` 静默截成 `/Volumes/a`，路径错了却不报错。
- 引号**成对才剥** —— 贪心的 `strip('"').strip("'")` 会把 `"o'brien"` 啃成 `obrien`。
- `$SOUL_CONFIG` 三者都要认 —— 少一处，用备用配置改了 `daemon_port` 时
  CLI 连新端口、渠道仍去探 8765，两边都以为对方没起服务。
- 空值一律记作 `""`（不要跳过），`true/false` 统一转 bool。

**改任何一份都要同步另外两份。**

## soulctl 命令 → daemon 端点映射

| soulctl 命令 | daemon 端点 | 说明 |
|---|---|---|
| `chat` | `POST /chat` | `{user_id, text, verbose}` |
| `state` | `GET /state` | `?user_id=` |
| `pending` | `GET /pending` | `?user_id=&limit=` |
| `drain` | `POST /drain` | `{user_id, limit, ack}`；`--peek` 即 `ack:false` |
| `ack` | `POST /ack` | `{user_id, ids}` —— 配对 `drain --peek`，只确认真正送达的那几条 |
| `tick` | `POST /tick` | `{user_id}` |
| `init` | `POST /init` | `{user_id, warmup}` |
| `reload-ai` | `POST /config/reload` | 重读 `.env` / `config.json`；daemon 没起则本地生效（`source: local`） |
| `serve` | — | 启动 daemon 本身 |
| `stop` | `POST /shutdown` | 停止 daemon |
| `doctor` / `selftest` / `install` | — | 本地操作，不经 daemon |

返回值中 `source` 字段标明这次走了哪条路：`daemon`（常驻）或 `cold-start`（冷启动）。

### 端点鉴权

除 `/health` 外的所有端点都要求 token，否则 `401 {"error": "unauthorized", "auth_required": true}`。

- 请求头：`X-Soul-Token: <token>`，或 `Authorization: Bearer <token>`（等价，后者方便 curl / 网关）。
- token 由 `serve` 首次启动时生成，落在项目根的 `.soul-daemon.token`（`0600`），重启复用。
  位置可用 `serve --token-file` 改，或用 `SOUL_DAEMON_TOKEN` 直接给定（客户端也认）。
- 无 token 的 `/health` 只回 `{"ok": true, "service": "soul-skill", "auth_required": true}`——
  这是一个**身份探针**：拿到它说明「端口上是我们，但你没 token」，跟「端口被别的程序占了」区分开。
  带 token 的 `/health` 才有 `pid` / `project` / `suspended_reason`。

`doctor` 的 `daemon.state` 就用这个区分：`up`（可用）/ `unauthorized`（在跑但鉴权不过）/ 无（没服务）。

## chat 返回契约

```jsonc
{
  "ok": true,
  "command": "chat",
  "status": "ok",              // ok | silent | queued | backend_error
  "user_id": "default_user",
  "parts": ["嗯…我在。", "累了就先歇会儿，别硬撑"],   // ta 一条条发出的消息
  "text": "嗯…我在。\n累了就先歇会儿，别硬撑",
  "elapsed_ms": 4200,
  "diagnostics": {             // 仅 --verbose 时返回
    "silence_reason": "[LifeGate] ...",   // 沉默原因（内部参考）
    "api_error": null,
    "stage_errors": [],
    "recovery_mode": false,
    "user_attitude": "..."
  }
}
```

### status 语义

| status | ok | 退出码 | 含义 | 调用方应做 |
|---|---|---|---|---|
| `ok` | true | 0 | 正常回复 | 把 `parts` 按条原样转达 |
| `silent` | true | 3 | 主动沉默（生命门控/情绪沉默/选择性回复） | 如实说没回，**不要编造** |
| `queued` | true | 4 | 回复入队延迟发送 | 后续用 `drain` 取 |
| `backend_error` | false | 1 | 模型后端失败 | 如实报错，检查 `ai.api_key` |
| `error` | false | 1 | 引擎异常 | 看 `traceback_tail` |

**关键区分**：`silent` 是人格行为（正常），`backend_error` 是故障。两者都表现为「没有回复」，但绝不可混淆——`engine_bridge.py` 会从引擎日志里捞 `API 调用失败 / 401 / Authentication Fails` 等标记来区分。

**归因必须只看本轮输出**：常驻服务里，后台自主思考引擎也会往同一份日志里写报错。所以
`run_chat` 会在本轮开始前打一个「水位线」，只分析这之后新产生的行——否则一条历史 401
会让后面每一次「人格沉默」都被误报成「后端故障」。排查时如果怀疑归因，看
`diagnostics.api_error` 与 `diagnostics.silence_reason` 是否同源。

**`--plain` 的输出约定**：有正文按条打印；`silent` / `queued` 打印一句状态说明；
`backend_error` 等异常 **stdout 为空、原因写 stderr、退出码非 0**。
调用方看到空输出时，必须先看退出码，不要直接判定成「ta 没说话」。

## state 返回字段语义

| 字段 | 含义 | 转述建议 |
|---|---|---|
| `mind_summary` | 24 维心智的一句话概括 | 「ta 现在情绪偏安静，有点倦」 |
| `personality_stage` | 相处阶段（青涩试探…平淡安稳） | 「你们现在处在松弛默契的阶段」 |
| `life_state` | 躯体/精力状态 | 「ta 刚忙完，有点乏」 |
| `fate_summary` | 羁绊/因果/共鸣 | 「ta 对你的羁绊挺深」 |
| `recent_memories` | 近期记忆 | 可挑一条自然地提 |
| `identity` | 独一无二的生命特质签名 | 少用，偏内部 |
| `mind_raw` | 24 维原始数值（仅 `--raw`） | **不要外露** |

## 多段回复约定

引擎用 `|||` 分隔多段消息。`engine_bridge.py` 负责拆成 `parts` 数组。
**呈现时必须分条**，不要拼成一大段——那正是「像真人发消息」的关键。

## 排障手册

| 现象 | 根因 | 处理 |
|---|---|---|
| `没找到数字生命项目根目录` | `project_root` 失效 | 改 `config.yaml`，或用 `--project` / `$SOUL_PROJECT_ROOT` |
| `没找到可用的 Python 解释器` | 系统 python < 3.10 | `soulctl.py setup` 建 venv，或 `--python` 指定 |
| `deps_required_ok: false` | 依赖没装 | `python3 $S setup` |
| `backend_error` / 401 | api_key 失效或额度耗尽 | 修 `config.json` 的 `ai.api_key`，再 `doctor --check-api` |
| `vector_memory: false` | 没装 fastembed/onnxruntime | **正常且默认**；要不要开见 setup-guide 的「要不要装向量记忆」一节 |
| 老是 `silent` | 可能是 API 失败被误判 | `--verbose` 看 `diagnostics.api_error` |
| 回复等很久 | 拟人延迟 + 模型耗时 | 用 `serve` 常驻；或调大 `chat_timeout_seconds` |
| 端口 8765 被占 | 有别的 daemon 在跑 | `soulctl.py stop`，或改 `config.yaml` 的 `daemon_port` |
| `拒绝在非回环地址上监听` | `daemon_host` 被改成对外地址 | 改回 `127.0.0.1`；确需暴露加 `--allow-remote` 并套 HTTPS |
| `端口…上有 soul-skill 常驻服务，但鉴权不通过` | 那个 daemon 用了别的 token 文件 | `serve --restart` 换成本机 token，或设 `SOUL_DAEMON_TOKEN` 对齐 |
| 手动 curl 得到 `401 unauthorized` | 没带 token | 加 `-H "X-Soul-Token: $(cat $PROJECT/.soul-daemon.token)"` |
| `无法准备鉴权 token` | token 文件所在目录不可写 | `serve --token-file <可写路径>`，或设 `SOUL_DAEMON_TOKEN` |
| `指定…不像数字生命项目` | `--project` / `$SOUL_PROJECT_ROOT` 指错 | 显式指定失效时**不会静默换项目**，按提示改路径 |
| 日志停止增长 / 不再主动发消息 | 模型接口持续失败，自主思考引擎已自动暂停 | 看 `GET /health` 的 `suspended_reason`，修好 key 后 `serve --restart` |
| 日志超大 | 已在 4MB 处裁剪并折叠重复行 | 仍偏大说明模型接口在持续失败，按上一条处理 |
| `database is locked` | 同一项目被多进程同时跑 | 只保留一个写者：daemon 活着就别再开 CLI/微信模式 |

## 自检手段

```bash
python3 $S doctor                 # 项目 + 解释器 + 依赖 + daemon + 配置
python3 $S doctor --check-api     # 额外真打一次模型接口（花少量额度）
python3 $S selftest               # 沙箱副本 + 假回复，验证链路不花额度
```

`selftest` 会把项目代码复制到临时目录、抹掉 `api_key` 与微信凭证、注入固定假回复，然后跑
`doctor → init → chat → state → pending → tick` 全链路。**它验证的是「命令→引擎→管道→多段回复」这条通路，不代表模型后端可用。**

沙箱有两个硬护栏，任一不满足就**直接中止**（不会退回真实项目）：
1. 沙箱里必须同时有 `soul.py` 与 `engine/`；
2. `resolve_project` 的解析结果必须等于沙箱目录本身。

（历史版本没有这两道门：沙箱复制不全时 `resolve_project` 会「软失败」回落到真实 `engine/`，
自检会一边打印「不碰真实数据」，一边把记忆写进真灵魂。）

## 沙箱与真实数据的边界

- `selftest` / `--fake-reply`：只用于链路自检，**生产调用绝不用**。
- 技能内**不含** `data/`；所有记忆写入真实项目目录，不可逆。
- 不要为了「测试」反复调用 `chat`——每次调用都在真实地相处。
