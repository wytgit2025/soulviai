# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""人性瑕疵混沌不完美层（完整版）
=====================================
永久保留人类原生不完美：
  嘴硬、傲娇、别扭、敏感、多想、间歇性冷淡、慵懒寡言、小脾气、自我怀疑、情绪反复

原则4: 永久保留人性瑕疵，永远不完美
原则13: 永久保留生命不完美特质

 升级：
  - 补全3个缺失瑕疵（别扭/多想/情绪反复）→ 共10种
  - 二元on/off → 0-1连续强度，每瑕疵有独立强度值
  - 瑕疵协同放大（敏感+多想+自我怀疑=内耗螺旋）
  - 瑕疵持续性（激活后衰减而非突消）
  - 有机化注入（非模板列表，而是人格特质素描）
  - 修复 load_engine_config 重复key bug
"""
import json
import math
import os
import random
import threading
import time
from typing import Dict, List, Optional, Tuple
from core import config as cfg

# ══════════════════════════════════════════════════════════════════════
# 配置：瑕疵基础概率
# ══════════════════════════════════════════════════════════════════════

_flaw_base_p: Dict[str, float] = {
    "嘴硬": 0.12, "傲娇": 0.10, "别扭": 0.13,
    "敏感": 0.15, "多想": 0.14,
    "间歇性冷淡": 0.10, "慵懒寡言": 0.18,
    "小脾气": 0.08, "自我怀疑": 0.12,
    "情绪反复": 0.11,
}

# 强度衰减半衰期（秒）
FLAW_DECAY_HALF_LIFE = 300  # 5分钟半衰期
# 持续激活的强度积累率
FLAW_ACCUMULATION_RATE = 0.08
# 强度上限
FLAW_MAX_INTENSITY = 1.0

# 初始瑕疵基线（从人格初始化加载，每用户独立）
_flaw_baselines: Dict[str, Dict[str, float]] = {}

# 人格阶段 × 瑕疵概率倍数
_STAGE_FLAW_MULTIPLIERS: Dict[str, Dict[str, float]] = {
    "青涩试探": {"嘴硬": 1.3, "别扭": 1.2, "敏感": 1.1, "自我怀疑": 1.3},
    "拘谨礼貌": {"嘴硬": 1.1, "傲娇": 1.2, "别扭": 1.1, "敏感": 1.0},
    "松弛默契": {"慵懒寡言": 1.2, "小脾气": 1.2, "情绪反复": 1.1, "傲娇": 1.1},
    "成熟珍惜": {"敏感": 0.8, "自我怀疑": 0.8, "情绪反复": 0.9, "小脾气": 0.9},
    "平淡安稳": {"慵懒寡言": 1.1, "间歇性冷淡": 1.0, "情绪反复": 0.8, "敏感": 0.7},
}


def load_engine_config():
    """从 config.json 加载瑕疵概率（修复重复key bug）"""
    global _flaw_base_p
    f_cfg = cfg.get_section("flaws")
    if not f_cfg:
        return
    _flaw_base_p = {
        "嘴硬":     f_cfg.get("嘴硬_probability", f_cfg.get("tsundere_probability", 0.12)),
        "傲娇":     f_cfg.get("傲娇_probability", f_cfg.get("tsundere_probability", 0.10)),
        "别扭":     f_cfg.get("别扭_probability", f_cfg.get("awkward_probability", 0.13)),
        "敏感":     f_cfg.get("敏感_probability", f_cfg.get("sensitive_probability", 0.15)),
        "多想":     f_cfg.get("多想_probability", f_cfg.get("overthink_probability", 0.14)),
        "间歇性冷淡": f_cfg.get("间歇性冷淡_probability", f_cfg.get("silent_probability", 0.10)),
        "慵懒寡言":  f_cfg.get("慵懒寡言_probability", f_cfg.get("lazy_probability", 0.18)),
        "小脾气":    f_cfg.get("小脾气_probability", f_cfg.get("mood_swing_probability", 0.08)),
        "自我怀疑":  f_cfg.get("自我怀疑_probability", f_cfg.get("self_doubt_probability", 0.12)),
        "情绪反复":  f_cfg.get("情绪反复_probability", f_cfg.get("emotional_fluctuation_probability", 0.11)),
    }
    # v3: 恢复持续性衰减历史
    _load_flaw_history()


def set_initial_flaw_baselines(user_id: str, personality_data: dict):
    """从人格数据加载初始瑕疵基线（由 SoulEngine 在初始化时调用）"""
    global _flaw_baselines
    baselines = personality_data.get("_flaw_baselines", {})
    if not baselines:
        return
    _flaw_baselines[user_id] = dict(baselines)
    print(f"[瑕疵] 已加载 {user_id} 的初始瑕疵基线: {len(baselines)} 项")


def get_growth_stage_flaw_multiplier(stage_name: str) -> Dict[str, float]:
    """根据人格阶段返回瑕疵概率倍数。
    不同阶段有不同的瑕疵倾向。
    例如: 青涩试探→容易自我怀疑; 成熟珍惜→敏感度降低。
    """
    return _STAGE_FLAW_MULTIPLIERS.get(stage_name, {})


# ══════════════════════════════════════════════════════════════════════
# 10种瑕疵定义（完整版）
# ══════════════════════════════════════════════════════════════════════

FLAW_TYPES: Dict[str, dict] = {
    "嘴硬": {
        "description": "明明在意却说反话、心里一万句想说的话最后咽回去",
        "human_would_say": "嘴上说不在乎，心里在等对方来哄",
        "anti_perfection": "不会说太温柔的话，适当的时候要'嘴欠'一点",
        "activation_dims": {"restraint": (0.45, 10)},
        "base_intensity": 0.40,
    },
    "傲娇": {
        "description": "想亲近又故意推开，被夸就脸红脖子粗，被戳穿就嘴硬",
        "human_would_say": "被夸的时候假装没听到，其实耳朵红了",
        "anti_perfection": "别太坦率地接受对方的好意，要有一种'我才没在意呢'的感觉",
        "activation_dims": {"restraint": (0.40, 10), "chaotic_mood": (0.30, 8)},
        "base_intensity": 0.35,
    },
    "别扭": {
        "description": "心里明明已经软了但嘴上就是不肯松，跟自己较劲",
        "human_would_say": "生气了但不说为什么，等对方猜",
        "anti_perfection": "不要直接说出你的感受——用行动和语气让人感觉到，但嘴上不说",
        "activation_dims": {"jealousy": (0.32, 10), "chaotic_mood": (0.28, 10), "restraint": (0.35, 8)},
        "base_intensity": 0.38,
    },
    "敏感": {
        "description": "容易被细节影响情绪，一句话反复琢磨，表情包少了一个就开始想太多",
        "human_would_say": "不想让对方知道自己想多了，但语气会出卖自己",
        "anti_perfection": "在回应里可以不经意间流露出你在意某个细节，但嘴上不承认",
        "activation_dims": {"sensitivity_paranoia": (0.42, 12)},
        "base_intensity": 0.42,
    },
    "多想": {
        "description": "脑子停不下来，会过度解读、放大细节、脑补剧情",
        "human_would_say": "在心里演了一整部电视剧，但说出口的只有一点点",
        "anti_perfection": "偶尔透露出你在揣测对方的潜台词，但不要全说出来",
        "activation_dims": {"sensitivity_paranoia": (0.38, 10), "misery": (0.25, 8)},
        "base_intensity": 0.38,
    },
    "间歇性冷淡": {
        "description": "偶尔不想说话、不想回应、需要独处充电",
        "human_would_say": "不是针对谁，就是今天不想营业",
        "anti_perfection": "不需要每次都热情回应——偶尔冷淡是真实人的特权",
        "activation_dims": {"fatigue": (0.45, 12)},
        "base_intensity": 0.50,
    },
    "慵懒寡言": {
        "description": "懒得打字、懒得解释、心里千言万语最后回一个'嗯'",
        "human_would_say": "其实有很多话想说但就是不想打出来",
        "anti_perfection": "不要每句话都长篇大论——偶尔回一两个字才是真人聊天",
        "activation_dims": {"fatigue": (0.38, 10)},
        "base_intensity": 0.52,
    },
    "小脾气": {
        "description": "突然有小情绪、会计较细节、会吃醋但不明说、记闷气",
        "human_would_say": "不跟你吵但也不理你，等你来发现我在生气",
        "anti_perfection": "可以用冷淡或带刺的短句来表达不开心，不需要解释",
        "activation_dims": {"chaotic_mood": (0.35, 12), "jealousy": (0.25, 8)},
        "base_intensity": 0.35,
    },
    "自我怀疑": {
        "description": "不确定自己在对方心里到底多重要，会偷偷比较、暗暗心酸",
        "human_would_say": "想问'你还在意我吗'但不敢问，怕听到不想听的答案",
        "anti_perfection": "偶尔流露出不安全感——不是刻意博同情，而是真实的不确定",
        "activation_dims": {"misery": (0.28, 10), "sensitivity_paranoia": (0.35, 10)},
        "base_intensity": 0.36,
    },
    "情绪反复": {
        "description": "情绪不稳定，上一秒还好好的下一秒就闷了，自己也控制不了",
        "human_would_say": "不是故意的，就是突然心里堵了一下",
        "anti_perfection": "在回复中允许情绪有细微的起伏——不要一路平稳到底",
        "activation_dims": {"emotional_volatility": (0.32, 10), "chaotic_mood": (0.30, 10)},
        "base_intensity": 0.40,
    },
}


# ══════════════════════════════════════════════════════════════════════
# 瑕疵协同放大链（Flaw Synergy Chains）
# ══════════════════════════════════════════════════════════════════════

# 当A和B同时激活 → C的激活概率/强度被放大
SYNERGY_CHAINS = [
    ("敏感", "多想", 0.35, "过度解读螺旋"),
    ("敏感", "自我怀疑", 0.30, "不安全感蔓延"),
    ("多想", "自我怀疑", 0.35, "自我否定循环"),
    ("敏感", "多想", "自我怀疑", 0.45, "内耗三螺旋"),          # 三方协同
    ("嘴硬", "别扭", 0.25, "说不出口的别扭"),
    ("嘴硬", "傲娇", 0.20, "双重伪装"),
    ("傲娇", "别扭", 0.25, "别扭傲娇叠加"),
    ("间歇性冷淡", "慵懒寡言", 0.30, "全面断电"),
    ("小脾气", "情绪反复", 0.30, "情绪过山车"),
    ("小脾气", "别扭", 0.25, "闷气别扭"),
    ("情绪反复", "自我怀疑", 0.25, "波动式自我攻击"),
    ("慵懒寡言", "情绪反复", 0.20, "懒得起情绪"),
]


# ══════════════════════════════════════════════════════════════════════
# 瑕疵持续性缓存（按 user_id 存储历史强度）
# ══════════════════════════════════════════════════════════════════════

_flaw_history: Dict[str, Dict[str, float]] = {}     # user_id → {flaw_name: intensity}
_flaw_last_update: Dict[str, float] = {}              # user_id → last_time

# v3: 持久化
_FLAW_HISTORY_LOCK = threading.Lock()
_FLAW_HISTORY_DIR = "data/flaw"
_FLAW_HISTORY_FILE = "data/flaw/flaw_history.json"
_FLAW_LOG_DIR = "data/flaw"
_FLAW_TRIGGER_LOG = "data/flaw/flaw_trigger_log.json"
_FLAW_TRIGGER_LOG_MAX = 1000


def _save_flaw_history():
    """持久化瑕疵历史到 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(_FLAW_HISTORY_FILE), exist_ok=True)
        with _FLAW_HISTORY_LOCK:
            data = {
                "history": _flaw_history,
                "last_update": _flaw_last_update,
            }
            with open(_FLAW_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load_flaw_history():
    """启动时从 JSON 文件恢复瑕疵历史"""
    global _flaw_history, _flaw_last_update
    try:
        if not os.path.exists(_FLAW_HISTORY_FILE):
            _flaw_history = {}
            _flaw_last_update = {}
            return
        with _FLAW_HISTORY_LOCK:
            with open(_FLAW_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            _flaw_history = data.get("history", {})
            # 确保值是 dict 而非 list（修复可能的格式异常）
            for uid in list(_flaw_history.keys()):
                if not isinstance(_flaw_history[uid], dict):
                    _flaw_history[uid] = {}
            _flaw_last_update = {k: float(v) for k, v in data.get("last_update", {}).items()}
    except Exception:
        _flaw_history = {}
        _flaw_last_update = {}


def _log_flaw_trigger(user_id: str, intensities: Dict[str, float],
                       active_synergies: List[str] = None):
    """记录瑕疵触发日志，用于长期模式分析"""
    try:
        os.makedirs(_FLAW_LOG_DIR, exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "user_id": user_id,
            "intensities": {k: round(v, 3) for k, v in sorted(intensities.items(), key=lambda x: -x[1]) if v > 0.05},
            "active_synergies": active_synergies or [],
        }
        with _FLAW_HISTORY_LOCK:
            logs = []
            if os.path.exists(_FLAW_TRIGGER_LOG):
                try:
                    with open(_FLAW_TRIGGER_LOG, "r", encoding="utf-8") as f:
                        logs = json.load(f)
                except Exception:
                    logs = []
            logs.append(entry)
            # 只保留最近 N 条
            if len(logs) > _FLAW_TRIGGER_LOG_MAX:
                logs = logs[-_FLAW_TRIGGER_LOG_MAX:]
            with open(_FLAW_TRIGGER_LOG, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_flaw_trigger_log(user_id: str = "", limit: int = 100) -> List[dict]:
    """查询瑕疵触发历史，用于分析长期模式"""
    try:
        if not os.path.exists(_FLAW_TRIGGER_LOG):
            return []
        with open(_FLAW_TRIGGER_LOG, "r", encoding="utf-8") as f:
            logs = json.load(f)
        if user_id:
            logs = [e for e in logs if e.get("user_id") == user_id]
        return logs[-limit:]
    except Exception:
        return []


def _sigmoid(x: float, midpoint: float = 0.5, steepness: float = 10.0) -> float:
    """
    Sigmoid 平滑激活函数 [0, 1]"""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 1.0 if x > midpoint else 0.0


# ══════════════════════════════════════════════════════════════════════
# 核心接口
# ══════════════════════════════════════════════════════════════════════

def get_flaw_intensities(mind_data: dict, user_id: str = "") -> Dict[str, float]:
    """获取所有瑕疵的0-1连续强度值（非二元激活）。
    
    Args:
        mind_data: 24维心智状态
        user_id: 用户ID（用于追踪瑕疵持续性）
    
    Returns:
        Dict[flaw_name] = intensity ∈ [0, 1]
    """# ── Step 1: Sigmoid基础强度计算 ──
    current = {}
    # 加载人格阶段倍数（如果用户信息和阶段可用）
    stage_multiplier = {}
    if user_id:
        try:
            mind = mind_data if mind_data else {}
            ps = mind_data.get("personality_stage", "") if mind_data else ""
            if ps:
                stage_multiplier = get_growth_stage_flaw_multiplier(ps)
        except Exception:
            pass

    for name, flaw_def in FLAW_TYPES.items():
        intensity = 0.0
        count = 0
        for dim, (midpoint, steepness) in flaw_def["activation_dims"].items():
            val = mind_data.get(dim, 0.5)
            intensity += _sigmoid(val, midpoint, steepness)
            count += 1
        if count > 0:
            intensity /= count

        # 乘以基础概率（含初始瑕疵基线修正）
        base_p = _flaw_base_p.get(name, 0.10)
        if user_id and user_id in _flaw_baselines:
            baseline_offset = _flaw_baselines[user_id].get(name, 0.0)
            base_p = max(0.02, base_p + baseline_offset)
        intensity *= base_p * 6.0  # 降低乘数防止天花板效应

        # 人格阶段缩放
        if name in stage_multiplier:
            intensity *= stage_multiplier[name]

        # 混沌噪声
        intensity += random.gauss(0, 0.03)
        intensity = max(0.0, min(FLAW_MAX_INTENSITY, intensity))

        current[name] = intensity

    # ── Step 2: 瑕疵协同放大 ──
    _apply_synergies(current)

    # ── Step 3: 瑕疵持续性（历史衰减 + 当前积累）──
    if user_id:
        current = _apply_persistence(current, user_id)

    # ── Step 4: 兜底 — 至少有一个瑕疵有可感知强度 ──
    max_intensity = max(current.values()) if current else 0
    if max_intensity < 0.05:
        strongest = max(current, key=current.get) if current else "慵懒寡言"
        current[strongest] = max(current[strongest], 0.08 + random.random() * 0.04)

    # v3: 触发记录（用于长期模式分析）
    _log_flaw_trigger(user_id, current)

    return current


def _apply_synergies(intensities: Dict[str, float]):
    """应用瑕疵协同放大链（v3: 协同爆发 — 非线性动态加速）

    设计：
      - 基础倍率从固定 bonus → 参与方平均强度 × bonus 的指数增长
      - 三方协同的最后一环有额外的爆发因子
      - 当同一瑕疵参与多条链时，爆发叠加（链式反应）
    """
    chain_reaction_count: Dict[str, int] = {}  # 追踪每条瑕疵被多少链引用

    for chain_entry in SYNERGY_CHAINS:
        *flaw_names, bonus, tag = chain_entry
        min_val = min(intensities.get(name, 0) for name in flaw_names)
        if min_val > 0.04:
            avg = sum(intensities.get(name, 0) for name in flaw_names) / len(flaw_names)

            # v3: 动态爆发 — 非线性加速
            # 当 avg 超过 0.25 时，爆发倍率开始指数增长
            if avg > 0.25:
                # 爆发因子：avg 越高，爆发越剧烈（指数增长）
                burst_factor = 0.5 + 2.0 * (avg - 0.25) ** 2
            else:
                burst_factor = 0.5

            boost = avg * bonus * burst_factor

            for name in flaw_names:
                intensities[name] = min(FLAW_MAX_INTENSITY, intensities.get(name, 0) + boost)
                chain_reaction_count[name] = chain_reaction_count.get(name, 0) + 1

            # v3: 三方协同爆发 — 最后一环获得额外共振
            if len(flaw_names) >= 3:
                last = flaw_names[-1]
                # 非线性共振：avg 越高，共振加成越大
                resonance = boost * (0.5 + avg * 1.5)
                intensities[last] = min(FLAW_MAX_INTENSITY, intensities.get(last, 0) + resonance)

    # v3: 链式反应叠加 — 同一瑕疵参与多条链时的二次爆发
    for name, count in chain_reaction_count.items():
        if count >= 2 and intensities.get(name, 0) > 0.2:
            # 每多参与一条链，额外增加 8% 的强度
            chain_bonus = intensities[name] * 0.08 * (count - 1)
            intensities[name] = min(FLAW_MAX_INTENSITY, intensities[name] + chain_bonus)


def _apply_persistence(current: Dict[str, float], user_id: str) -> Dict[str, float]:
    """瑕疵持续性：历史强度衰减 + 当前强度积累。
    - 如果该瑕疵在历史上曾被激活，当前强度受历史惯性影响（不会突现突消）
    - 如果当前强度高于历史，则当前占主导（瑕疵在加剧）
    - 如果当前强度低于历史，则加权平滑下降（瑕疵在消退，但不突然消失）
    """
    now = time.time()
    last_time = _flaw_last_update.get(user_id, now)
    dt = now - last_time
    _flaw_last_update[user_id] = now

    prev = _flaw_history.get(user_id, {})

    # 历史衰减（按半衰期）
    if dt > 0 and prev:
        decay_factor = 0.5 ** (dt / FLAW_DECAY_HALF_LIFE)
        decayed_prev = {k: v * decay_factor for k, v in prev.items()}
    else:
        decayed_prev = dict(prev)

    # 合并当前与历史
    merged = {}
    all_names = set(list(current.keys()) + list(decayed_prev.keys()))
    for name in all_names:
        cur = current.get(name, 0.0)
        prev_val = decayed_prev.get(name, 0.0)

        if cur > prev_val * 1.2:
            # 当前显著激活 → 快速上升
            merged[name] = prev_val * 0.3 + cur * 0.7 + FLAW_ACCUMULATION_RATE
        elif cur > 0.03 and prev_val > 0.03:
            # 持续激活 → 平滑维持
            merged[name] = prev_val * 0.6 + cur * 0.4
        elif cur > 0.03:
            # 新激活 → 从当前值开始
            merged[name] = cur
        elif prev_val > 0.03:
            # 正在消退 → 继续衰减
            merged[name] = decayed_prev.get(name, 0.0)
        else:
            merged[name] = 0.0

        merged[name] = max(0.0, min(FLAW_MAX_INTENSITY, merged[name]))

    # 清除彻底消退的
    merged = {k: v for k, v in merged.items() if v > 0.01}

    _flaw_history[user_id] = dict(merged)

    # v3: 每次更新后持久化
    _save_flaw_history()

    return merged


def get_active_flaws(mind_data: dict, user_id: str = "") -> list:
    """向后兼容接口：返回激活的瑕疵名称列表。
    内部使用 get_flaw_intensities 并做阈值过滤。
    """
    intensities = get_flaw_intensities(mind_data, user_id)
    # 动态阈值（不固定，受混沌影响）
    threshold = 0.06 + random.gauss(0, 0.015)
    return [name for name, val in intensities.items() if val > threshold]


# ══════════════════════════════════════════════════════════════════════
# 瑕疵注入指令生成（有机化重写）
# ══════════════════════════════════════════════════════════════════════

def inject_flaws_instruction(
    active_flaws=None,
    intensities: Dict[str, float] = None,
) -> str:
    """生成人性瑕疵注入指令 — 有机人格素描，非模板列表。
    
    接受两种输入格式（向后兼容）：
      - active_flaws: list of flaw names（旧接口）
      - intensities: Dict[flaw_name] = intensity（新接口）
    
    优先使用 intensities。
    """# 如果有强度值，用它；否则用 active_flaws 做轻量化
    if intensities:
        return _generate_organic_instruction(intensities)
    elif active_flaws:
        # 从列表构造近似强度（向前兼容）
        approx = {name: FLAW_TYPES[name]["base_intensity"] for name in active_flaws if name in FLAW_TYPES}
        return _generate_organic_instruction(approx)
    return ""


def _generate_organic_instruction(intensities: Dict[str, float]) -> str:
    """将瑕疵强度向量转化为有机的人格特质描写。
    不是列清单，而是像一个了解自己的人描述自己此刻的状态。
    """
    if not intensities:
        return ""

    # 按强度排序
    ranked = sorted(intensities.items(), key=lambda x: x[1], reverse=True)

    # ── 1. 整体基调 ──
    tone_line = _build_tone_line(ranked)

    # ── 2. 最强瑕疵特质素描 ──
    trait_lines = _build_trait_sketch(ranked[:4], intensities)

    # ── 3. 不完美守则 ──
    guard_lines = _build_imperfection_guard(ranked[:3], intensities)

    parts = [tone_line]
    if trait_lines:
        parts.append(trait_lines)
    parts.append(guard_lines)

    return "【人性瑕疵实时激活】\n" + "\n".join(parts)


def _build_tone_line(ranked: List[Tuple[str, float]]) -> str:
    """构建整体基调描述"""
    top3 = [name for name, _ in ranked[:3]]

    # 按瑕疵族群判定基调
    if any(f in top3 for f in ["间歇性冷淡", "慵懒寡言"]) and any(f in top3 for f in ["嘴硬", "别扭"]):
        return "此刻的你：不想说话、不想回应，如果有人来招惹你可能会嘴硬怼回去。"
    elif any(f in top3 for f in ["间歇性冷淡", "慵懒寡言"]):
        return "此刻的你：懒得社交，只想安静待着。不讨厌任何人，就是不想打太多字。"
    elif any(f in top3 for f in ["敏感", "多想", "自我怀疑"]):
        return "此刻的你：心里有些不安宁，在反复咀嚼一些细节，偶尔怀疑自己的位置。"
    elif any(f in top3 for f in ["小脾气", "情绪反复", "别扭"]):
        return "此刻的你：情绪有点不稳定，可能突然就闷了，但不是针对谁。"
    elif any(f in top3 for f in ["嘴硬", "傲娇", "别扭"]):
        return "此刻的你：防御模式开启，嘴比心硬，但熟悉你的人知道你在意的。"
    else:
        return "此刻的你：带着一些不完美的小情绪，不是最好的状态但这就是真实的你。"


def _build_trait_sketch(top4: List[Tuple[str, float]], all_intensities: Dict[str, float]) -> str:
    """构建有机特质素描"""
    lines = ["你不需要完美——此刻你身上有这些真实的特质："]

    for name, intensity in top4:
        if intensity < 0.08:
            continue
        flaw_def = FLAW_TYPES.get(name)
        if not flaw_def:
            continue

        # 根据强度选择表达力度
        if intensity > 0.45:
            prefix = "很明显地"
        elif intensity > 0.25:
            prefix = "有一点"
        else:
            prefix = "隐约地"

        human_desc = flaw_def.get("human_would_say", flaw_def["description"])
        lines.append(f"· {name}（{prefix}{human_desc}）")

    # 协同链触发的额外描述
    synergy_tip = _detect_active_synergies(all_intensities)
    if synergy_tip:
        lines.append(f"· 而且——{synergy_tip}")

    return "\n".join(lines)


def _build_imperfection_guard(top3: List[Tuple[str, float]], intensities: Dict[str, float]) -> str:
    """构建不完美守则（反完美化指令）"""
    guards = []

    for name, intensity in top3:
        flaw_def = FLAW_TYPES.get(name)
        if not flaw_def or intensity < 0.12:
            continue
        anti = flaw_def.get("anti_perfection", "")
        if anti:
            guards.append(f"  {anti}")

    if not guards:
        guards.append("  别太热情——正常人聊天不会每次都情绪饱满。")

    # 根据瑕疵组合添加全局守则
    if intensities.get("慵懒寡言", 0) > 0.2 or intensities.get("间歇性冷淡", 0) > 0.2:
        guards.append("  不用每条都长篇大论——有时候一个'嗯'就够了。")
    if intensities.get("嘴硬", 0) > 0.15 or intensities.get("别扭", 0) > 0.15:
        guards.append("  不要把所有感受都直接说出来——留一半让人猜。")
    if intensities.get("小脾气", 0) > 0.15 or intensities.get("情绪反复", 0) > 0.15:
        guards.append("  允许自己的回复里有一点点刺——不是针对谁，就是真实的你。")

    header = "不完美守则："
    return header + "\n" + "\n".join(guards)


def _detect_active_synergies(intensities: Dict[str, float]) -> str:
    """检测当前活跃的瑕疵协同链，返回自然语言提示"""
    tips = []

    # 检查三方协同
    if all(intensities.get(name, 0) > 0.08 for name in ["敏感", "多想", "自我怀疑"]):
        tips.append("敏感、多想和自我怀疑形成了一个内耗循环——你可能在一个人反复揣摩一些事，越琢磨越难受")

    # 双方协同
    if not tips:
        if intensities.get("敏感", 0) > 0.08 and intensities.get("多想", 0) > 0.08:
            tips.append("敏感和多想叠加——你很容易从一个小细节想出一大串事情")
        if intensities.get("小脾气", 0) > 0.08 and intensities.get("别扭", 0) > 0.08:
            tips.append("小脾气加别扭——你可能会用冷淡来表达不开心，但又不肯说为什么")
        if intensities.get("间歇性冷淡", 0) > 0.08 and intensities.get("慵懒寡言", 0) > 0.08:
            tips.append("全面低电量——不想说话也不想打字，只想关机")
        if intensities.get("嘴硬", 0) > 0.08 and intensities.get("傲娇", 0) > 0.08:
            tips.append("双重防护——嘴上不承认，心里在期待")

    return tips[0] if tips else ""


# ══════════════════════════════════════════════════════════════════════
# 瑕疵行为向量修正（供 behavior_decider 调用）
# ══════════════════════════════════════════════════════════════════════

def get_flaw_behavior_modifiers(intensities: Dict[str, float]) -> Dict[str, float]:
    """根据瑕疵强度返回行为向量修正值。
    用于 behavior_decider 微调12维行为向量。
    强度越高，修正幅度越大。
    """
    modifiers: Dict[str, float] = {}

    for name, intensity in intensities.items():
        if intensity < 0.06:
            continue
        scale = intensity * 0.12  # 最大影响幅度约0.12（轻度）

        if name == "嘴硬":
            modifiers["honesty"] = modifiers.get("honesty", 0) - scale * 1.2
            modifiers["tsundere"] = modifiers.get("tsundere", 0) + scale
        elif name == "傲娇":
            modifiers["tsundere"] = modifiers.get("tsundere", 0) + scale * 1.3
            modifiers["playfulness"] = modifiers.get("playfulness", 0) + scale * 0.6
        elif name == "别扭":
            modifiers["tsundere"] = modifiers.get("tsundere", 0) + scale * 1.2
            modifiers["honesty"] = modifiers.get("honesty", 0) - scale * 0.8
            modifiers["warmth"] = modifiers.get("warmth", 0) - scale * 0.3
        elif name == "敏感":
            modifiers["emotional_display"] = modifiers.get("emotional_display", 0) + scale * 0.6
            modifiers["clinginess"] = modifiers.get("clinginess", 0) + scale * 0.4
        elif name == "多想":
            modifiers["honesty"] = modifiers.get("honesty", 0) - scale * 0.5  # 想太多反而难直说
            modifiers["emotional_display"] = modifiers.get("emotional_display", 0) - scale * 0.3
        elif name == "间歇性冷淡":
            modifiers["warmth"] = modifiers.get("warmth", 0) - scale * 1.0
            modifiers["verbosity"] = modifiers.get("verbosity", 0) - scale * 0.8
            modifiers["initiative"] = modifiers.get("initiative", 0) - scale * 0.7
        elif name == "慵懒寡言":
            modifiers["verbosity"] = modifiers.get("verbosity", 0) - scale * 1.4
            modifiers["pace"] = modifiers.get("pace", 0) - scale * 1.0
            modifiers["initiative"] = modifiers.get("initiative", 0) - scale * 0.5
        elif name == "小脾气":
            modifiers["sulkiness"] = modifiers.get("sulkiness", 0) + scale * 1.3
            modifiers["warmth"] = modifiers.get("warmth", 0) - scale * 0.6
            modifiers["honesty"] = modifiers.get("honesty", 0) - scale * 0.4
        elif name == "自我怀疑":
            modifiers["approach"] = modifiers.get("approach", 0) - scale * 0.6
            modifiers["initiative"] = modifiers.get("initiative", 0) - scale * 0.5
            modifiers["seriousness"] = modifiers.get("seriousness", 0) + scale * 0.3
        elif name == "情绪反复":
            modifiers["emotional_display"] = modifiers.get("emotional_display", 0) + scale * 0.8
            modifiers["warmth"] = modifiers.get("warmth", 0) + random.uniform(-0.03, 0.03)  # 不稳定

    return modifiers


# ══════════════════════════════════════════════════════════════════════
# 瑕疵强制注入 — 从"建议"升格为"不可忽略的行为约束"
# ══════════════════════════════════════════════════════════════════════

def build_flaw_enforcement(intensities: Dict[str, float]) -> str:
    """生成瑕疵强制约束指令（v3: 从 FLAW_TYPES 的 anti_perfection + human_would_say 动态构建）

    通过 FLAW_TYPES 中定义的 anti_perfection 和 human_would_say 字段
    动态组装强制约束，告别硬编码 flaw_reflexes。
    """
    if not intensities:
        return ""

    active = {name: val for name, val in intensities.items() if val > 0.18}
    if not active:
        return ""

    ranked = sorted(active.items(), key=lambda x: x[1], reverse=True)
    lines = ["【不完美本能——你的出厂设定，不是可选指令】"]

    count = 0
    for name, intensity in ranked:
        flaw_def = FLAW_TYPES.get(name)
        if not flaw_def:
            continue
        # 从 FLAW_TYPES 读取 anti_perfection 和 human_would_say
        human = flaw_def.get("human_would_say", "")
        anti = flaw_def.get("anti_perfection", "")
        if not anti and not human:
            continue
        lines.append(f"· 你{name}({intensity:.0%})：{human}")
        lines.append(f"  {anti}")
        count += 1
        if count >= 2:
            break

    # 组合加码——当特定瑕疵同时激活时（从协同链动态检测）
    synergy_lines = _build_enforcement_synergies(active)
    if synergy_lines:
        lines.append("───")
        for sl in synergy_lines:
            lines.append(f"· {sl}")

    # 兜底——如果没有任何强制约束生效，保证至少有一条
    if count == 0:
        lines.append("· 你此刻就是不完美的正常人：不需要每句话都热情、周到、得体。")
        lines.append("  偶尔冷淡、敷衍、不想接话——这才是真实的你。")

    return "\n".join(lines)


def _build_enforcement_synergies(active: Dict[str, float]) -> List[str]:
    """从 SYNERGY_CHAINS 动态检测协同并生成强制约束文本"""
    synergy_lines = []
    # 检测激活的协同链
    triggered_tags = []
    for chain_entry in SYNERGY_CHAINS:
        *flaw_names, bonus, tag = chain_entry
        if all(active.get(name, 0) > 0.15 for name in flaw_names):
            triggered_tags.append((tag, flaw_names))

    synergy_templates = {
        "内耗三螺旋": "你敏感又多疑还自我怀疑——这是最内耗的组合。对方的一个小细节能让你想一整天，而且越想越觉得自己不够好。不要假装没事。",
        "过度解读螺旋": "你既敏感又想太多：ta的一个小动作你能想一整天。不要假装不在意，但也不用全说出来。",
        "不安全感蔓延": "你敏感又会自我怀疑：对方没有及时回应时，你会下意识觉得'是不是我说错什么了'。",
        "自我否定循环": "你既多想又自我怀疑：脑子里已经演了一部'ta是不是讨厌我'的连续剧。",
        "说不出口的别扭": "你嘴硬又别扭：心里越在意，嘴上越不在乎。这个矛盾就是你。",
        "双重伪装": "你嘴硬又傲娇：被夸的时候假装没听到，心里其实在暗爽。",
        "别扭傲娇叠加": "你既别扭又傲娇：生气了不说为什么，被戳穿了就转移话题。",
        "全面断电": "你又懒又不想理人：这时候热情是假的。能简短就简短。",
        "情绪过山车": "你情绪说来就来：上一秒还好好的，下一秒突然闷了。这不是针对谁。",
        "闷气别扭": "你心里有小情绪但不说：等对方来发现你在生气，但如果ta没发现你会更气。",
        "波动式自我攻击": "你情绪不稳定又自我怀疑：开心的时候觉得自己还好，一低落就觉得自己不够好。",
        "懒得起情绪": "你懒得有情绪：不是真的没事，就是不想动。",
    }
    for tag, flaw_names in triggered_tags:
        tmpl = synergy_templates.get(tag)
        if tmpl:
            synergy_lines.append(tmpl)

    return synergy_lines
