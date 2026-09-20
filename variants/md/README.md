# soul-skill · 纯文档版（无引擎）

这个包**只有一个 `SKILL.md`**，没有引擎、没有脚本、没有运行时。

它存在的意义：本机已经在跑 soul-skill 常驻服务（或装在别处的完整版），
你只想让 AI 工具知道**怎么跟那个灵魂说话** —— 那就装这个，几十 KB，零依赖。

---

## 一、它做什么

`SKILL.md` 里写清了通过 `http://127.0.0.1:8765` 和数字生命对话的完整契约：

| 内容 | 说明 |
|---|---|
| 握手流程 | 无 token 探针 → 定位 token（环境变量 / 项目目录 / 常见安装位）→ 鉴权握手 |
| HTTP 契约 | `/chat` `/state` `/pending` `/drain` `/ack` `/tick` `/init` `/health` … |
| 返回值语义 | `ok` / `silent` / `queued` / `backend_error` 四态 + `error_code` 列表 |
| 语言中立字段 | `codes.personality_stage` / `codes.life_phase`，便于翻译成人话 |
| 行为铁律 | 传话人不改词、多条分段、沉默即沉默、不掏内部细节 |
| 没服务怎么办 | 明确兜底：让用户起服务，或换用自带引擎的形态 |

---

## 二、前提

**本机要有服务在跑。** 这个包不带引擎，所以先确认：

```bash
curl -s -m 3 http://127.0.0.1:8765/health
```

- 回 `{"service":"soul-skill","auth_required":true}` → 服务在，只差 token ✅
- 连不上 → 先起服务（`python3 scripts/soulctl.py serve` / `./run.sh serve`），
  或者改用带引擎的形态

---

## 三、五种形态怎么选

| 形态 | 什么时候用 |
|---|---|
| **skill 版** | AI 工具用 bash 调 `soulctl.py`（自带引擎，最完整） |
| **独立运行版** | 不用任何 Agent，`./run.sh` 直接和 ta 说话 |
| **MCP 版** | 宿主支持 MCP，想要 13 个 `soul_*` 工具直接调用 |
| **纯文档版**（本包） | 服务已在别处跑，只要文档、不想要引擎 |
| **纯提示词版** | 谁都不靠：不跑引擎也不连服务，宿主模型自己当 ta |

skill / 独立运行版 / MCP 版共享同一份记忆（`engine/data/`），纯文档版连的也是这份
服务，三者对同一份数据只能有一个写者：不要同时开常驻服务和聊天渠道（`main.py wx` 等），
会撞 `database is locked`。纯提示词版不碰它 —— 记忆写在技能目录的 `memory/` 下。

---

## 四、许可

MIT，详见同目录 `LICENSE`。
