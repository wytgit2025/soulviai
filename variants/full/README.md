# soul-skill · 形态槽位：skill（完整技能）

**这里没有薄壳。** 本目录存在的意义只有一个：让 `variants/` 与构建器里的五种形态
一一对应，不留需要口头解释的例外。

---

## 为什么没有薄壳

skill 形态的交付内容就是**技能根本身**：

```
SKILL.md + scripts/ + references/ + engine/ + config.yaml + VERSION + LICENSE
```

构建器对它的声明是 `entries: None`（技能根全量）+ `overrides: []`（不替换任何文件）
—— **技能根就是它的薄壳**，没有第二份需要拼装的东西。

把根 `SKILL.md` 复制一份到这里当薄壳，会带来两个实际问题：

1. **双份维护**：同一个技能定义要改两处，漏一处就漂移；
2. **多份技能定义**：仓库本身就是可安装的技能目录，多一份 `SKILL.md`
   会让人和工具都不确定哪份算数。

所以这里只放这份说明，不放副本。

---

## 各形态的薄壳对照

| 形态 | 薄壳目录 | 薄壳内容 |
|---|---|---|
| `skill` | 无（本体即技能根） | —— |
| `standalone` | `variants/standalone/` | `run.sh` / `run.cmd` / `README.md` |
| `mcp` | `variants/mcp/` | `SKILL.md` / `README.md` / `mcp.json` |
| `md` | `variants/md/` | `SKILL.md` / `README.md` |
| `prompt-md` | `variants/prompt-md/` | `SKILL.md` / `README.md` |

> `variants/` 是构建输入，不进任何包，因此本目录的内容不影响 skill 形态的包。

---

## 它受构建器校验

`scripts/dev/build_variants.py` 的 `check_shells()` 会核对每个形态都有 `variants/<key>/` 槽位，
缺一个就在构建时报错 —— 这不是可以随手删掉的装饰。
