# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""世界模型 — 知识图谱 + 因果链追踪 + 长期规划引擎
========================================================
三大能力：
  1. 知识图谱 — 实体-关系-实体三元组存储与检索，构建关于用户的完整知识网络
  2. 因果链追踪 — 保留原有因果对记录、预测、检索（已增强）
  3. 长期规划 — 目标设定 + 步骤分解 + 进度追踪

 升级：
  - 从轻量因果链升级为完整的知识图谱（实体+关系+权重+衰减）
  - 新增长期规划能力（目标管理、步骤分解、进度追踪、复盘更新）
  - 所有原有API保持向后兼容
"""
import json
import random
import re
import time
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

try:
    from core import database as db
except ImportError:
    db = None

CAUSALITY_CACHE: Dict[str, List[Dict]] = {}
MAX_CAUSAL_CHAINS = 80


def load_engine_config():
    global CAUSALITY_CACHE
    CAUSALITY_CACHE = {}
    try:
        chains = db.get_all_causality()
        if chains:
            for c in chains:
                uid = c.get("user_id", "__global__")
                if uid not in CAUSALITY_CACHE:
                    CAUSALITY_CACHE[uid] = []
                CAUSALITY_CACHE[uid].append({
                    "cause": c.get("cause", ""),
                    "effect": c.get("effect", ""),
                    "pattern": c.get("pattern", ""),
                    "verified": bool(c.get("verified", 1)),
                    "count": c.get("occurrence_count", 1),
                })
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 第一部分：知识图谱（新）
# ══════════════════════════════════════════════════════════════════════

def extract_and_store_knowledge(user_id: str, user_message: str, comprehension: dict = None):
    """从用户消息中提取实体和关系，存入知识图谱"""
    if not user_message or len(user_message) < 4:
        return

    intent = comprehension.get("intent", "") if comprehension else ""
    emotion = comprehension.get("true_emotion", "") if comprehension else ""

    entities = _extract_entities(user_message)
    for entity in entities:
        etype = "concept"
        if any(kw in entity for kw in ["喜欢", "讨厌", "爱", "怕", "想", "觉得"]):
            etype = "feeling"
        elif any(kw in entity for kw in ["工作", "公司", "学校", "家", "地方"]):
            etype = "place"
        elif any(kw in entity for kw in ["朋友", "家人", "同事", "同学", "ta"]):
            etype = "person"
        weight = 0.4 + (0.3 if emotion in ("开心", "温柔", "感动") else 0.0)
        try:
            db.upsert_knowledge_entity(user_id, entity, etype, weight)
        except Exception:
            pass

    relations = _extract_relations(user_message, entities)

    # 句法模式关系增强（20种模式，纯正则）
    pattern_relations = _pattern_extract_relations(user_message)
    relations.extend(pattern_relations)

    for e1, rel, e2 in relations:
        try:
            db.upsert_knowledge_relation(user_id, e1, rel, e2, weight=0.5)
        except Exception:
            pass

    # 属性值提取（实体-属性-值四元组）
    extract_attributes_from_message(user_id, user_message)


def _extract_entities(text: str) -> List[str]:
    """从文本中提取候选实体（2-6字中文词，含LLM辅助）"""
    import re
    words = re.findall(r'[\u4e00-\u9fff]{2,6}', text)
    stopwords = {"用户", "对方", "数字", "生命", "灵魂", "什么", "怎么",
                 "这个", "那个", "可以", "不过", "但是", "因为", "所以",
                 "如果", "虽然", "然后", "最后", "没有", "时候", "一个",
                 "自己", "今天", "昨天", "明天", "刚才", "知道", "感觉",
                 "觉得", "就是", "还是", "已经", "以后", "以前", "大家",
                 "可能", "应该", "不会", "不要", "一起", "一下", "一直",
                 "有点", "真的", "那么", "这么", "这样", "那样", "因为",
                 "所以", "但是", "而且", "或者", "只是", "不过", "虽然",
                 "如果", "然后", "只是"}

    regex_entities = [w for w in words if w not in stopwords and len(w) >= 2]

    # 如果正则提取结果不足3个且文本长度>15，尝试LLM辅助
    if len(regex_entities) < 3 and len(text) > 15:
        try:
            from core import ai as ai_module
            prompt = f"从这段话中提取1-3个关键名词实体（人名/兴趣/情感/地点/事物），用逗号分隔：{text[:80]}"
            result = ai_module.background_chat(prompt, temperature=0.1, max_tokens=30)
            if result:
                llm_entities = [e.strip() for e in result.split(",") if e.strip() and len(e.strip()) >= 2]
                # 合并去重
                seen = set(regex_entities)
                for e in llm_entities:
                    if e not in seen and len(e) >= 2:
                        regex_entities.append(e)
                        seen.add(e)
        except Exception:
            pass

    return regex_entities[:8]


def _extract_relations(text: str, entities: List[str]) -> List[Tuple[str, str, str]]:
    """从文本中提取实体间的关系三元组（含LLM辅助）"""
    relations = []
    rel_keywords = {
        "喜欢": "喜欢", "讨厌": "讨厌", "害怕": "害怕", "想去": "想去",
        "在做": "在做", "有": "拥有", "在": "在", "是": "是",
        "觉得": "觉得", "想": "想", "怕": "害怕",
    }
    for kw, rel in rel_keywords.items():
        if kw in text:
            parts = text.split(kw, 1)
            if len(parts) == 2:
                before = _extract_entities(parts[0])
                after = _extract_entities(parts[1])
                if before and after:
                    relations.append((before[-1], rel, after[0]))
                elif before:
                    relations.append((before[-1], rel, kw))

    # 如果没有提取到关系且文本有明确情感/动作词，尝试LLM辅助
    if not relations and len(text) > 10:
        try:
            from core import ai as ai_module
            prompt = f"从这句话提取关系三元组（实体1,关系,实体2）。返回JSON列表或空：{text[:80]}"
            result = ai_module.background_chat(prompt, temperature=0.1, max_tokens=50)
            if result and "(" in result:
                parts = result.strip("()").split(",")
                if len(parts) >= 3:
                    relations.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
        except Exception:
            pass

    if not relations and len(entities) >= 2:
        relations.append((entities[0], "提到", entities[1]))
    return relations[:3]


def query_knowledge_graph_context(user_id: str, topic: str = "") -> str:
    """获取知识图谱上下文文本（供注入prompt）"""
    try:
        return db.get_knowledge_graph_context(user_id, topic)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════
# 第二部分：因果链追踪（原有，增强版）
# ══════════════════════════════════════════════════════════════════════

def record_causality(user_id: str, cause: str, effect: str, pattern: str = ""):
    if user_id not in CAUSALITY_CACHE:
        CAUSALITY_CACHE[user_id] = []

    for entry in CAUSALITY_CACHE[user_id]:
        if entry["cause"] == cause[:60] and entry["effect"] == effect[:60]:
            entry["count"] = entry.get("count", 1) + 1
            entry["verified"] = True
            _persist_causality(user_id, cause, effect, pattern, entry["count"])
            return

    CAUSALITY_CACHE[user_id].append({
        "cause": cause[:120],
        "effect": effect[:120],
        "pattern": pattern[:60],
        "verified": True,
        "count": 1,
    })

    if len(CAUSALITY_CACHE[user_id]) > MAX_CAUSAL_CHAINS:
        CAUSALITY_CACHE[user_id] = sorted(
            CAUSALITY_CACHE[user_id],
            key=lambda x: x.get("count", 1),
            reverse=True,
        )[:MAX_CAUSAL_CHAINS]

    _persist_causality(user_id, cause, effect, pattern, 1)


def _persist_causality(user_id: str, cause: str, effect: str, pattern: str, count: int):
    try:
        db.upsert_causality(user_id, cause[:120], effect[:120], pattern[:60], count)
    except Exception:
        pass


def record_interaction_causality(
    user_id: str,
    user_message: str,
    ai_response: str,
    comprehension: dict = None,
    user_attitude: str = "",
):
    if not comprehension:
        return

    intent = comprehension.get("intent", "")
    emotion = comprehension.get("true_emotion", "")
    depth = comprehension.get("depth", "")

    if intent == "倾诉" and emotion in ("难过", "低落", "焦虑"):
        record_causality(
            user_id,
            cause=f"用户在倾诉负面情绪: {user_message[:40]}",
            effect=f"AI回应态度={user_attitude}",
            pattern="倾诉→情绪支持",
        )

    if intent == "撒娇":
        record_causality(
            user_id,
            cause=f"用户在撒娇: {user_message[:40]}",
            effect=f"AI回应态度={user_attitude}",
            pattern="撒娇→亲密互动",
        )

    if depth == "深度":
        record_causality(
            user_id,
            cause=f"深度对话: {user_message[:40]}",
            effect=f"AI回应态度={user_attitude}",
            pattern="深度对话→关系深化",
        )

    if intent == "敷衍" or emotion == "冷淡":
        record_causality(
            user_id,
            cause=f"用户态度冷淡/敷衍: {user_message[:40]}",
            effect=f"AI回应态度={user_attitude}",
            pattern="冷淡→疏离",
        )

    extract_and_store_knowledge(user_id, user_message, comprehension)


def predict_user_reaction(user_id: str, my_intended_message: str) -> Dict:
    chains = CAUSALITY_CACHE.get(user_id, [])
    if not chains:
        return {"prediction": "不确定", "confidence": 0.0, "evidence": []}

    relevant = []
    for c in chains:
        if any(kw in c.get("cause", "") for kw in _extract_keywords(my_intended_message)):
            relevant.append(c)

    if not relevant:
        return {"prediction": "不确定", "confidence": 0.0, "evidence": []}

    effects = defaultdict(int)
    for c in relevant:
        effects[c.get("effect", "未知")] += c.get("count", 1)

    best_effect = max(effects, key=effects.get) if effects else "不确定"
    total = sum(effects.values())
    confidence = effects[best_effect] / total if total > 0 else 0.0

    return {
        "prediction": best_effect,
        "confidence": round(confidence, 2),
        "evidence": [f"{c['cause'][:40]} → {c['effect'][:40]}" for c in relevant[:3]],
    }


def explain_causality(user_id: str, event: str) -> str:
    chains = CAUSALITY_CACHE.get(user_id, [])
    if not chains:
        return ""

    keywords = _extract_keywords(event)
    matched = []
    for c in chains:
        score = sum(1 for kw in keywords if kw in c.get("cause", ""))
        if score > 0:
            matched.append((score, c))

    if not matched:
        return ""

    matched.sort(key=lambda x: x[0], reverse=True)
    top = matched[:3]

    lines = ["【因果推测】"]
    for _, c in top:
        pattern = c.get("pattern", "")
        if pattern:
            lines.append(f"· 过去类似情境({pattern}): {c['cause'][:40]} → {c['effect'][:40]}")
        else:
            lines.append(f"· {c['cause'][:40]} → {c['effect'][:40]}")

    return "\n".join(lines)


def get_causality_context(user_id: str, max_chars: int = 200) -> str:
    chains = CAUSALITY_CACHE.get(user_id, [])
    if not chains:
        return ""

    verified = [c for c in chains if c.get("verified")]
    if not verified:
        return ""

    patterns = defaultdict(list)
    for c in verified:
        pattern = c.get("pattern", "")
        if pattern:
            patterns[pattern].append(c)

    lines = []
    total = 0
    for pattern, items in sorted(patterns.items(), key=lambda x: len(x[1]), reverse=True):
        line = f"· {pattern}: 已确认{len(items)}次"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    if lines:
        return "【你学到的因果模式】\n" + "\n".join(lines)
    return ""


def _extract_keywords(text: str) -> List[str]:
    """从文本中提取有意义的实体级关键词（替代旧版2-char bigram）"""
    if not text:
        return []
    words = []
    import re

    entities = re.findall(r'[\u4e00-\u9fff]{2,6}', text)
    stopwords = {"用户", "对方", "数字", "生命", "灵魂", "什么", "怎么",
                 "这个", "那个", "可以", "不过", "但是", "因为", "所以",
                 "如果", "虽然", "然后", "最后", "没有", "时候", "一个",
                 "自己", "今天", "昨天", "明天", "刚才", "知道", "感觉",
                 "觉得", "就是", "还是", "已经", "以后", "以前", "大家",
                 "可能", "应该", "不会", "不要", "一起", "一下", "一直",
                 "有点", "真的", "那么", "这么", "这样", "那样", "因为",
                 "所以", "但是", "而且", "或者", "只是", "不过", "虽然",
                 "如果", "然后", "只是"}

    for w in entities:
        if w not in stopwords and len(w) >= 2:
            words.append(w)

    for kw in ["喜欢", "讨厌", "害怕", "想去", "想做", "觉得", "希望",
                "难过", "开心", "生气", "累了", "忙了", "敷衍", "撒娇",
                "冷淡", "温柔", "孤独", "想念", "依赖", "拒绝", "接纳"]:
        if kw in text and kw not in words:
            words.append(kw)

    return words[:15]


# ══════════════════════════════════════════════════════════════════════
# 第三部分：长期规划（新）
# ══════════════════════════════════════════════════════════════════════

def create_goal_from_conversation(user_id: str, goal_text: str, context: str = "",
                                    priority: int = 5, deadline: str = "") -> Optional[int]:
    """从对话中创建一个长期目标"""
    try:
        goal_id = db.create_planning_goal(user_id, goal_text, priority, context, deadline)
        print(f"[世界模型] 创建新目标: {goal_text[:40]}")
        return goal_id
    except Exception as e:
        print(f"[世界模型] 创建目标失败: {e}")
        return None


def decompose_goal_into_steps(user_id: str, goal_id: int, steps: List[str]):
    """将目标分解为可执行的步骤"""
    try:
        for i, step in enumerate(steps):
            db.add_planning_step(goal_id, step, i)
        print(f"[世界模型] 目标#{goal_id} 分解为 {len(steps)} 个步骤")
    except Exception as e:
        print(f"[世界模型] 步骤分解失败: {e}")


def update_goal_progress(user_id: str, goal_id: int, completed_step_index: int,
                          result_note: str = "") -> Dict:
    """更新目标进度：标记某一步为已完成"""
    try:
        steps = db.get_planning_steps(goal_id)
        if completed_step_index >= len(steps):
            return {"success": False, "reason": "步骤索引超出范围"}

        step = steps[completed_step_index]
        db.update_planning_step(step["id"], "done", result_note)

        steps = db.get_planning_steps(goal_id)
        total = len(steps)
        done = sum(1 for s in steps if s["status"] == "done")
        progress = round(done / total, 2) if total > 0 else 0.0

        status = "active" if progress < 1.0 else "done"
        db.update_planning_goal(goal_id, {"progress": progress, "status": status})

        return {"success": True, "progress": progress, "done": done, "total": total}
    except Exception as e:
        return {"success": False, "reason": str(e)}


def get_planning_context(user_id: str, max_goals: int = 3) -> str:
    """获取长期规划上下文文本（供注入prompt）"""
    try:
        goals = db.get_active_planning_goals(user_id, max_goals)
        if not goals:
            return ""

        lines = ["【心里记挂的事】"]
        for g in goals:
            steps = db.get_planning_steps(g["id"])
            done = sum(1 for s in steps if s["status"] == "done")
            total = len(steps)
            if total > 0:
                lines.append(f"· {g['goal']} [{done}/{total}]")
            else:
                lines.append(f"· {g['goal']}")

        return "\n".join(lines)
    except Exception:
        return ""


def get_full_world_context(user_id: str, topic: str = "", event: str = "") -> str:
    """综合获取世界模型的全部上下文（知识图谱 + 因果链 + 长期规划）。
    用于注入 prompt。
    """
    parts = []

    kg = query_knowledge_graph_context(user_id, topic)
    if kg:
        parts.append(kg)

    cc = explain_causality(user_id, event) if event else get_causality_context(user_id)
    if cc:
        parts.append(cc)

    plan = get_planning_context(user_id)
    if plan:
        parts.append(plan)

    attrs = get_attribute_context(user_id)
    if attrs:
        parts.append(attrs)

    return "\n\n".join(parts) if parts else ""


# ══════════════════════════════════════════════════════════════════════
# 第四部分：句法模式增强提取（新增，纯正则，零依赖）
# ══════════════════════════════════════════════════════════════════════

_PATTERN_TEMPLATES = [
    (r"([\u4e00-\u9fff]{1,6})的([\u4e00-\u9fff]{1,6})", "拥有属性"),
    (r"在([\u4e00-\u9fff]{2,10})的时候(.{2,20})", "伴随"),
    (r"比([\u4e00-\u9fff]{1,6})还(.{2,10})", "超越"),
    (r"从([\u4e00-\u9fff]{2,10})到([\u4e00-\u9fff]{2,10})", "演变"),
    (r"像(.{2,10})一样(.{2,10})", "比喻"),
    (r"因为(.{2,30})所以(.{2,30})", "因果"),
    (r"虽然(.{2,30})但是(.{2,30})", "转折"),
    (r"要是(.{2,30})就好了", "愿望"),
    (r"记得(.{2,30})的时候", "回忆"),
    (r"再也(不|没)(.{2,20})", "失去"),
    (r"终于(.{2,30})了", "达成"),
    (r"差点(.{2,20})", "险些"),
    (r"连(.{1,6})都(.{2,20})", "强调"),
    (r"除了(.{2,20})以外", "排除"),
    (r"一边(.{2,10})一边(.{2,10})", "并行"),
    (r"越(.{2,10})越(.{2,10})", "递进"),
    (r"刚(.{2,20})就(.{2,20})", "紧接"),
    (r"明明(.{2,20})却(.{2,20})", "反差"),
    (r"一(.{2,10})就(.{2,20})", "条件"),
    (r"与其(.{2,20})不如(.{2,20})", "取舍"),
]


def _pattern_extract_relations(text: str) -> List[Tuple[str, str, str]]:
    """从 20 种中文句法模式中提取关系三元组。
    纯正则，无 LLM 调用，每段文本 <0.1ms。
    """
    relations = []
    for pattern, rel_type in _PATTERN_TEMPLATES:
        for match in re.finditer(pattern, text):
            groups = match.groups()
            if not groups:
                continue
            e1 = groups[0].strip()
            e2 = groups[-1].strip()
            if len(e1) >= 1 and len(e2) >= 1 and e1 != e2:
                relations.append((e1, rel_type, e2))
    return relations[:6]


_ATTRIBUTE_PATTERNS = [
    (r"(?:喜欢|爱)喝(.{1,10})(?:的)?(?:咖啡|茶|奶|水|饮料)", "饮品偏好"),
    (r"(?:在|去)(.{1,15})(?:工作|上学|上班|读书|住|生活)", "地点"),
    (r"(?:养了|有)(?:只|个|条)(.{1,6})(?:的)?(?:猫|狗|兔子|鸟|宠物)", "宠物"),
    (r"最(?:喜欢|爱|讨厌|怕)(.{1,10})", "偏好"),
    (r"我(?:是|做)(.{1,10})(?:的|工作|职业|行业)", "职业"),
    (r"(?:今年|已经|都).{0,4}(.{1,4})(?:岁|了)", "年龄"),
    (r"(?:叫|是)(.{1,10})(?:吧|吗|的|？|？)", "称呼"),
]


def extract_attributes_from_message(user_id: str, user_message: str):
    """从用户消息中提取属性值对（实体-属性-值），存入知识图谱。
    与传统三元组互补：属性值对比关系三元组更细粒度。
    """
    if not user_message or len(user_message) < 4:
        return

    for pattern, attr_name in _ATTRIBUTE_PATTERNS:
        match = re.search(pattern, user_message)
        if match and match.group(1):
            attr_value = match.group(1).strip()
            if 1 <= len(attr_value) <= 10:
                try:
                    db.upsert_knowledge_attribute(user_id, attr_name, attr_value, confidence=0.5)
                except Exception:
                    pass


def get_attribute_context(user_id: str, max_attrs: int = 6) -> str:
    """获取已提取的属性上下文（供 prompt 注入）"""
    try:
        attrs = db.get_knowledge_attributes(user_id, limit=max_attrs)
        if not attrs:
            return ""

        lines = ["【知道的关于ta的细节】"]
        for a in attrs:
            lines.append(f"· ta的{a['attribute']}: {a['value']}")
        return "\n".join(lines)
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════
# 第五部分：知识图谱质量自评估（新增）
# ══════════════════════════════════════════════════════════════════════

def evaluate_knowledge_quality(user_id: str) -> Dict:
    """评估知识图谱健康度，自动标记低置信度/冲突知识。
    纯统计，无 LLM 调用。
    """
    result = {"status": "healthy", "conflicts": [], "stale_count": 0}

    try:
        conflicts = db.find_knowledge_conflicts(user_id)
        if conflicts:
            result["conflicts"] = conflicts
            result["status"] = "has_conflicts"

        stale = db.count_stale_knowledge(user_id, days=14)
        if stale > 0:
            result["stale_count"] = stale
            if stale > 5:
                result["status"] = "needs_cleanup"
                db.purge_stale_knowledge(user_id, days=14)
    except Exception:
        pass

    return result
