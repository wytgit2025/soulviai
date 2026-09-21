# Copyright (c) 2026 soulviai 项目作者
# SPDX-License-Identifier: Apache-2.0

"""
TaskScheduler — 轻量级后台任务调度器
统一管理所有后台线程的生命周期：注册 → 调度 → 执行 → 监控 → 重启 → 动态调频
纯标准库实现，零外部依赖。
"""
import contextlib
import threading
import time
import random
import heapq
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from core.logging_utils import log_error


def _background_context():
    """把调度器任务标记为「后台上下文」。

    调度器注册的任务（life_engine / ferment_release / reflection / persona_analysis …）
    内部会触发矛盾博弈、记忆复盘等 LLM 调用。打上这个标记后，core/ai.py 的熔断器
    才能在模型接口挂掉时把这些调用一并挡下，而不是只停自主思考引擎、放任其余任务
    继续刷 401。纯标准库兜底：core.ai 不可用时退化为空上下文。
    """
    try:
        from core.ai import background_context
        return background_context()
    except Exception:  # pragma: no cover - 仅在 core.ai 不可用时触发
        return contextlib.nullcontext()


@dataclass
class TaskSpec:
    name: str
    fn: Callable
    interval: float
    priority: int = 5
    auto_restart: bool = True
    max_restarts_per_hour: int = 5
    adaptive: bool = False
    enabled: bool = True
    last_run: float = 0.0
    consecutive_fails: int = 0
    total_fails: int = 0
    total_runs: int = 0
    restart_cooldown: float = 0.0


class DynamicTuner:
    """心智驱动动态调频器

    根据当前心智状态，调整 adaptive=True 任务的间隔倍率。
    集成各模块中分散的"状态→频率"映射规则。
    """

    def __init__(self):
        self._mind_cache: Dict[str, dict] = {}

    def cache_mind(self, user_id: str, mind_data: dict):
        self._mind_cache[user_id] = mind_data

    def get_multiplier(self, task_name: str, user_id: str = None) -> float:
        """返回任务间隔倍率。1.0 = 正常, >1 = 更慢, <1 = 更快"""
        mind = self._mind_cache.get(user_id) if user_id else None
        if not mind:
            return 1.0

        fatigue = mind.get("fatigue", 0.25)
        loneliness = mind.get("loneliness", 0.4)
        joy = mind.get("joy", 0.5)
        chaotic = mind.get("chaotic_mood", 0.2)
        dependence = mind.get("dependence", 0.2)

        if task_name == "autonomous_thought":
            if fatigue > 0.8:
                return 10.0
            if fatigue > 0.6:
                return 3.0
            if loneliness > 0.6:
                return 0.5
            if joy > 0.7:
                return 0.7
            return 1.0

        if task_name in ("thinking_30min", "thinking_60min"):
            if fatigue > 0.7:
                return 0.0
            if chaotic > 0.5:
                return 1.5
            return 1.0

        if task_name == "ferment_release":
            if chaotic > 0.6:
                return 0.5
            if fatigue > 0.7:
                return 2.0
            return 1.0

        return 1.0


class TaskScheduler:
    """轻量级后台任务调度器

    用法:
        scheduler = TaskScheduler()
        scheduler.register("my_task", my_func, interval=60, priority=3)
        scheduler.start()
        # ... 运行中 ...
        scheduler.stop()
    """

    def __init__(self):
        self._tasks: Dict[str, TaskSpec] = {}
        self._ready_queue: List[Tuple[float, int, str]] = []
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._dispatcher_thread: Optional[threading.Thread] = None
        self._tuner = DynamicTuner()
        self._max_per_cycle = 10

    # ── 公开 API ──

    def register(self, name: str, fn: Callable, interval: float,
                 priority: int = 5, auto_restart: bool = True,
                 max_restarts_per_hour: int = 5,
                 adaptive: bool = False,
                 delay_first: bool = False) -> None:
        """注册一个周期性任务

        delay_first=True 时首次执行要等满一个 interval。默认 False（首次执行发生
        在注册后的第一个调度周期，约 0.5s）是**刻意的**，life_engine 那批任务依赖
        它立刻起跑。会联网的任务应该用 True：否则它会在引擎刚构造完就抢跑，
        和对话入口的首次采集撞车 —— 对方看到采集线程已在跑，那一轮就拿不到环境信息。
        """
        with self._lock:
            self._tasks[name] = TaskSpec(
                name=name, fn=fn, interval=interval,
                priority=priority, auto_restart=auto_restart,
                max_restarts_per_hour=max_restarts_per_hour,
                adaptive=adaptive,
                last_run=time.time() if delay_first else 0.0,
            )

    def unregister(self, name: str) -> None:
        with self._lock:
            self._tasks.pop(name, None)

    def start(self) -> None:
        """启动调度器（启动调度线程）"""
        if self._running.is_set():
            return
        self._running.set()
        self._dispatcher_thread = threading.Thread(
            target=self._dispatch_loop, daemon=True,
            name="task-scheduler"
        )
        self._dispatcher_thread.start()
        print(f"[调度器] 已启动 ({len(self._tasks)} 个任务已注册)")

    def stop(self) -> None:
        self._running.clear()
        print("[调度器] 已停止")

    def is_running(self) -> bool:
        return self._running.is_set()

    def set_max_per_cycle(self, n: int) -> None:
        self._max_per_cycle = max(1, n)

    def get_task(self, name: str) -> Optional[TaskSpec]:
        with self._lock:
            return self._tasks.get(name)

    def get_all_tasks(self) -> Dict[str, TaskSpec]:
        with self._lock:
            return dict(self._tasks)

    def get_stats(self) -> dict:
        with self._lock:
            return {
                name: {
                    "interval": t.interval,
                    "priority": t.priority,
                    "enabled": t.enabled,
                    "total_runs": t.total_runs,
                    "consecutive_fails": t.consecutive_fails,
                    "total_fails": t.total_fails,
                }
                for name, t in self._tasks.items()
            }

    def disable_task(self, name: str) -> None:
        with self._lock:
            task = self._tasks.get(name)
            if task:
                task.enabled = False

    def enable_task(self, name: str) -> None:
        with self._lock:
            task = self._tasks.get(name)
            if task:
                task.enabled = True

    def set_interval(self, name: str, interval: float) -> bool:
        with self._lock:
            task = self._tasks.get(name)
            if task:
                task.interval = interval
                return True
            return False

    def cache_mind(self, user_id: str, mind_data: dict) -> None:
        self._tuner.cache_mind(user_id, mind_data)

    # ── 内部调度循环 ──

    def _dispatch_loop(self):
        """调度主循环：每 0.5s 检查一次就绪队列"""
        while self._running.is_set():
            try:
                self._tick()
            except Exception as e:
                log_error("scheduler.dispatch", str(e))
            time.sleep(0.5)

    def _tick(self):
        now = time.time()
        executed = 0

        # 功率管理：无交互时降低后台任务频率
        power_multiplier = _power_manager.get_tick_multiplier()

        with self._lock:
            ready_tasks = []
            for name, task in self._tasks.items():
                if not task.enabled:
                    continue
                if task.restart_cooldown > now:
                    continue

                multiplier = 1.0
                if task.adaptive:
                    multiplier = self._tuner.get_multiplier(task.name)
                    if multiplier <= 0.0:
                        continue

                # 生命体征始终保持高频，不受功率管理影响
                if name == "life_engine":
                    effective_interval = task.interval * multiplier
                elif name in ("reflection", "persona_analysis", "weather_refresh"):
                    # 后台分析型任务大幅降频（深睡期 10×，即天气最长可陈旧数小时；
                    # 这是有意的 —— 没人说话时不值得为保鲜频繁联网，一旦有对话，
                    # on_message_received() 立刻回到 ACTIVE，ChatPipeline 的 ensure()
                    # 也会当场刷新）。weather_refresh 在 soulviai.py 注册。
                    effective_interval = task.interval * multiplier * power_multiplier
                else:
                    effective_interval = task.interval * multiplier * max(1.0, power_multiplier * 0.7)

                if now - task.last_run >= effective_interval - 0.5:
                    ready_tasks.append((task.priority, name))

            ready_tasks.sort(key=lambda x: x[0])

            for priority, name in ready_tasks:
                if executed >= self._max_per_cycle:
                    break
                task = self._tasks.get(name)
                if not task:
                    continue
                task.last_run = now
                executed += 1

                self._execute_task(name)

    def _execute_task(self, name: str):
        task = self._tasks.get(name)
        if not task:
            return

        try:
            # 标记为后台上下文：接口挂掉时，ai 层会短路任务内部的 LLM 调用
            with _background_context():
                task.fn()
            task.consecutive_fails = 0
            task.total_runs += 1
        except Exception as e:
            task.consecutive_fails += 1
            task.total_fails += 1
            task.total_runs += 1
            log_error(f"scheduler.task.{name}", str(e))

            if task.consecutive_fails >= 3:
                cooldown = min(60, 2 ** (task.consecutive_fails - 3))
                task.restart_cooldown = time.time() + cooldown
                print(f"[调度器] ⚠ {name} 连续失败 {task.consecutive_fails} 次, "
                      f"冷却 {cooldown}s")

            if task.consecutive_fails >= 10 and task.auto_restart:
                task.enabled = False
                print(f"[调度器] 🛑 {name} 连续失败 10 次, 已自动停用")

            if task.total_fails >= task.max_restarts_per_hour:
                task.enabled = False
                print(f"[调度器] 🛑 {name} 已达小时最大失败次数, 已停用")


# ── 全局单例 ──
_scheduler: Optional[TaskScheduler] = None


def get_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler


def init_scheduler() -> TaskScheduler:
    """初始化并返回全局调度器实例"""
    return get_scheduler()


# ══════════════════════════════════════════════════════════════════════
# 系统电源管理 — SystemPowerManager
# ══════════════════════════════════════════════════════════════════════

from enum import Enum, auto

class PowerState(Enum):
    DEEP_SLEEP = auto()     # 无交互超过2小时
    LIGHT_SLEEP = auto()    # 无交互超过30分钟
    AWAKE = auto()          # 正常
    ACTIVE = auto()         # 对话中：全功率


class SystemPowerManager:
    """系统电源管理——不该动的时候别动

    根据用户交互间隔自动调节后台任务频率。
    对话时全功率，静默时休眠。
    """

    def __init__(self):
        self.last_interaction = time.time()
        self._state = PowerState.AWAKE
        self._idle_thresholds = {
            PowerState.DEEP_SLEEP: 7200,   # 2小时
            PowerState.LIGHT_SLEEP: 1800,  # 30分钟
        }

    def get_state(self) -> PowerState:
        elapsed = time.time() - self.last_interaction
        if elapsed > self._idle_thresholds[PowerState.DEEP_SLEEP]:
            return PowerState.DEEP_SLEEP
        if elapsed > self._idle_thresholds[PowerState.LIGHT_SLEEP]:
            return PowerState.LIGHT_SLEEP
        # 5分钟内有交互算活跃
        if elapsed < 300:
            return PowerState.ACTIVE
        return PowerState.AWAKE

    def on_message_received(self):
        """收到消息时立刻激活"""
        self.last_interaction = time.time()

    def get_tick_multiplier(self) -> float:
        """不同状态下后台任务的执行频率倍率"""
        state = self.get_state()
        if state == PowerState.DEEP_SLEEP:
            return 10.0
        if state == PowerState.LIGHT_SLEEP:
            return 3.0
        if state == PowerState.AWAKE:
            return 1.5
        return 1.0  # ACTIVE


# 全局电源管理器实例
_power_manager = SystemPowerManager()


def get_power_manager() -> SystemPowerManager:
    return _power_manager
