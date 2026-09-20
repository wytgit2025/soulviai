# soul-skill · MCP 版

把本机的数字生命引擎接进任意 **MCP 宿主**（CodeBuddy / Cursor / Claude Desktop /
VS Code / Windsurf …），宿主里会多出 13 个 `soul_*` 工具。

`scripts/soul_mcp.py` 是**纯标准库**的 stdio MCP server：不需要装 `mcp` SDK、
不需要额外虚拟环境，宿主用系统自带的 python3 就能拉起来。

---

## 一、最快的接入方式

引擎自带的启动器可以直接生成配置（并可选写入宿主配置文件）：

```bash
python3 scripts/soulctl.py mcp-config                    # 打印全部宿主的配置片段
python3 scripts/soulctl.py mcp-config --target cursor    # 只看某一个
python3 scripts/soulctl.py mcp-config --target all --write   # 直接写进各宿主配置（合并，不动别人的 server）
```

没装引擎源码、只有这个包时，手改配置也很简单 —— 复制 `mcp.json`，把
`args` 里的路径换成 `scripts/soul_mcp.py` 的绝对路径，粘进宿主配置即可。

| 宿主 | 配置文件 | 顶层键 |
|---|---|---|
| CodeBuddy | `~/.codebuddy/mcp.json` | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` |
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` | `mcpServers` |
| Claude Desktop (Linux) | `~/.config/Claude/claude_desktop_config.json` | `mcpServers` |
| VS Code（项目级） | `<项目>/.vscode/mcp.json` | `servers` |

改完**重开窗口 / 重启宿主**才生效。

### 可选参数

```json
{
  "mcpServers": {
    "soul-skill": {
      "command": "python3",
      "args": [
        "/abs/path/soul-skill/scripts/soul_mcp.py",
        "--project", "/abs/path/soul-skill/engine",
        "--user", "default_user"
      ]
    }
  }
}
```

| 参数 | 作用 |
|---|---|
| `--project` | 引擎根目录（含 `soul.py` 与 `engine/`），默认取 `config.yaml` |
| `--python` | 运行引擎的解释器（想强制用某个 venv 时） |
| `--user` | 灵魂身份，默认 `default_user`（与终端/微信共用同一个灵魂） |
| `--config` | 换一份 `config.yaml` |
| `--host` / `--port` | 连非默认端口的常驻服务 |
| `--prewarm` | server 启动时后台把常驻服务拉起来（首次对话更快） |
| `--selfcheck` | 不开服务，只打印环境诊断后退出（排障用） |

---

## 二、13 个工具

| 工具 | 作用 |
|---|---|
| `soul_chat` | 和 ta 说一句话，拿回回复（每个 content 块是一条消息） |
| `soul_state` | ta 当前的生命状态（24 维心智 / 相处阶段 / 精力 / 羁绊） |
| `soul_pending` | 看 ta 攒着的主动消息（只看不取） |
| `soul_drain` | 取出主动消息（`peek` 可只看不标记已送达） |
| `soul_ack` | 确认消息已送达（配 `soul_drain peek` 用） |
| `soul_tick` | 手动推进一次内心活动 |
| `soul_init` | 唤醒 / 初始化某个身份 |
| `soul_health` | 轻量体检：项目、解释器、常驻服务、token |
| `soul_serve` | 把引擎常驻到内存（含自主思考引擎） |
| `soul_stop` | 停掉常驻服务 |
| `soul_doctor` | 完整体检（`check_api` 会真打一次模型接口） |
| `soul_setup` | 建虚拟环境并装依赖 |
| `soul_selftest` | 沙箱端到端自检（不碰真实记忆、不花额度） |

### 行为约定（宿主侧会被注入到系统提示）

1. 工具是**传话人**，不是 ta：`soul_chat` 的每个 content 块原样转达，不改写、不润色、不模仿。
2. `status: silent` 是 ta 主动选择的沉默，**不是故障**，如实说「ta 这次没回你」。
3. `status: backend_error` 才是真故障，要如实告诉用户并指向模型配置。
4. `soul_chat` 有拟人延迟（通常 3–20 秒，慢时 1 分钟以上）且会真实写入记忆，别刷。
5. 不要替 ta 编回复；不要绕过引擎直接读改 `engine/data/`。

---

## 三、和别的形态一起用

MCP 只是**接入方式**，写的是同一份 `engine/data/`。所以：

- 常驻服务（`soul_serve`）和终端渠道（`main.py wx` 等）**不能同时跑**，会撞 `database is locked`。
- 多个副本（比如同时装给 Cursor 和 Claude）默认都连 `127.0.0.1:8765`；其中一个已经起了服务时，
  另一个会报 token 不匹配 —— 这是**刻意的单写者保护**，不是 bug。要么共用同一个服务，要么改 `daemon_port`。
- 想让 ta 在你不在时也想你：跑 `soul_serve`，自主思考引擎会在后台攒消息，下次用 `soul_drain` 取。

---

## 四、排障

| 现象 | 处理 |
|---|---|
| 宿主里看不到 `soul_*` 工具 | 配置 JSON 语法 / 路径写错；用 `python3 scripts/soul_mcp.py --selfcheck` 验证能否跑起来 |
| 工具报 `no_project` | 引擎没找到，用 `--project` 指定，或改 `config.yaml` 的 `project_root` |
| 工具报 `no_python` | 跑 `soul_setup`（需要 Python ≥3.10） |
| 工具报 401 / token 不匹配 | 有别的副本起了服务：先 `soul_stop`，或换端口 |
| `soul_chat` 一直 silent | 用 `soul_doctor --check-api` 确认模型接口 |

---

## 五、许可

MIT，详见同目录 `LICENSE`。
