# variants/ · 四种交付形态与组装方法

这一层放的是**交付包模板**，不是拿来直接运行的目录。
克隆仓库后请先读根目录 `README.md` 走快速开始；要分发某个形态时，按下表组装。

| 形态 | 组装方法（在仓库根执行） |
|---|---|
| **agent-full** 完整技能版 | 整个仓库就是它：`engine/` + `scripts/` + `config.yaml` + `SKILL.md` 原样分发 |
| **standalone-app** 独立运行版 | `cp -r engine scripts config.yaml variants/standalone-app/{run.sh,run.cmd,启动-mac.command,启动-win.cmd,README.md,SKILL.md} <目标目录>/`，再加上根目录的 `VERSION` `LICENSE` `DISCLAIMER.md`；最后 `chmod +x <目标目录>/run.sh <目标目录>/启动-mac.command` |
| **mcp-tools** MCP 版 | `cp -r engine scripts config.yaml <目标目录>/`，加上 `variants/mcp-tools/mcp.json`（把里面的脚本路径改成绝对路径）与根目录 `SKILL.md` `VERSION` `LICENSE` |
| **persona-prompt** 纯提示词版 | 只要 `variants/persona-prompt/SKILL.md` + 根目录 `VERSION` `LICENSE` `DISCLAIMER.md` |

组装要点：

- **别把 `engine/.env`、`engine/.venv`、`engine/data`、任何 `*token*` 打进包里**（`.gitignore`
  已在 git 层防住，手工拷贝时注意同样规则）。`engine/data` 是运行期落下的记忆，拷进去等于
  把灵魂和渠道凭证一起发出去。
- **`启动-mac.command` 必须带执行位**，否则 Finder 里双击打不开（页面会变成用编辑器打开）。
  `cp -p` 能保住权限位；从 zip/U 盘/网盘取回来丢了权限时，补一次 `chmod +x` 即可。
- 记忆在 `~/.soulviai/`，不在仓库树里 —— 组装出来的包是「空壳灵魂」，数据留在本机。
- 带引擎的三个形态（agent-full / standalone-app / mcp-tools）写的是**同一份** `~/.soulviai/` 记忆，
  同一时刻只能有一个写者。
- persona-prompt 不连任何服务，自带独立的 `memory/`。

各形态的详细定位与用法见各自子目录的 `README.md`。
