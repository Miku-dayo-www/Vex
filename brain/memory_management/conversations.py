import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List
from nervous_system.event_bus import QoS

logger = logging.getLogger(__name__)

# 对话线程状态机
class ThreadStatus(Enum):
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"

@dataclass
class CognitiveThread:
    thread_id: str
    topic_summary: str
    unspoken_text: str
    status: ThreadStatus
    dialogue_history: List[Dict[str, str]] = field(default_factory=list)

class ConversationManager:
    """短期工作区：管理多线程残局与对话回合"""
    def __init__(self, event_bus, episodic_memory):
        self.event_bus = event_bus
        self.episodic_memory = episodic_memory
        self.thread_pool: Dict[str, CognitiveThread] = {}
        self.current_id: str | None = None
        self.suspend_timer_task = None
        self.idle_timer_task = None
        logger.info("🧵 [工作区] 对话线程池管理已就绪。")

    def get_working_memory(self, limit: int = 5) -> List[Dict[str, str]]:
        """瞬时工作区：只提取当前线程最近 N 轮的纯净对话，守住推理延迟"""
        if self.current_id and self.current_id in self.thread_pool:
            # 一轮对话包含 user 和 model 两条记录
            return self.thread_pool[self.current_id].dialogue_history[-(limit * 2):]
        return []

    def _reset_idle_timer(self):
        """闲置计时器"""
        if self.idle_timer_task:
            self.idle_timer_task.cancel()
        if self.current_id:
            self.idle_timer_task = asyncio.create_task(self._idle_watchdog(self.current_id))

    async def _idle_watchdog(self, thread_id: str):
        """闲置自然归档"""
        try:
            await asyncio.sleep(1200.0) # 闲置时间(秒)
            if thread_id in self.thread_pool and self.thread_pool[thread_id].status == ThreadStatus.RUNNING:
                logger.info(f"⏳ [工作区] 话题 {thread_id} 闲置 20 分钟，感知到自然结束，自动打包进长期记忆。")
                self.archive_thread(thread_id)
        except asyncio.CancelledError:
            pass

    def commit_turn(self, user_text: str, ai_text: str):
        """原子化事务提交。对话完整结束才成对写入历史，防止脏数据"""
        if self.current_id and self.current_id in self.thread_pool:
            self.thread_pool[self.current_id].dialogue_history.append({"role": "user", "text": user_text})
            self.thread_pool[self.current_id].dialogue_history.append({"role": "model", "text": ai_text})
            logger.info("💾 [工作区提交] 对话事务已提交。")
            self._reset_idle_timer()

    def commit_ai_continuation(self, ai_text: str):
        """将多轮思考拼接到上一次的 AI 回复中"""
        if self.current_id and self.current_id in self.thread_pool:
            history = self.thread_pool[self.current_id].dialogue_history
            if history and history[-1]["role"] == "model":
                history[-1]["text"] += f" (执行动作后) {ai_text}"
                logger.info("🔗 [工作区追加] 工具动作结果已合并至当前认知周期。")
            else:
                self.commit_turn("[系统追加]", ai_text)
            self._reset_idle_timer()

    def suspend_current(self, unspoken_text: str):
        """挂起话题，保存残余现场"""
        if not self.current_id: return
        thread = self.thread_pool.get(self.current_id)
        if thread and len(unspoken_text.strip()) > 2:
            thread.unspoken_text = unspoken_text
            thread.status = ThreadStatus.SUSPENDED
            logger.info(f"⏸️ [工作区挂起] 话题 [{thread.topic_summary}] 被打断，真实残余现场已封存入栈。")
            if self.suspend_timer_task:
                self.suspend_timer_task.cancel()

    def build_context_snapshot(self) -> str:
        """只暴露活跃与挂起线程，阻断 Prompt 膨胀"""
        if not self.thread_pool:
            return "当前无任何历史话题记录。"
        snapshot = "[系统内存快照 (Thread Pool)]\n"
        active_count = 0
        for t_id, thread in self.thread_pool.items():
            if thread.status == ThreadStatus.ARCHIVED:
                continue
            active_count += 1
            unspoken_info = f" | 未说完残余: '{thread.unspoken_text}'" if thread.unspoken_text else ""
            snapshot += f"- ID: {t_id} | 状态: {thread.status.value} | 摘要: {thread.topic_summary}{unspoken_info}\n"
        if active_count == 0:
            return "当前无活跃话题，请随时开启新话题。"
        return snapshot

    def archive_thread(self, thread_id: str):
        """归档话题，触发潜意识固化"""
        if thread_id in self.thread_pool:
            summary = self.thread_pool[thread_id].topic_summary
            self.thread_pool[thread_id].status = ThreadStatus.ARCHIVED
            self.thread_pool[thread_id].unspoken_text = ""
            if self.current_id == thread_id:
                self.current_id = None
            logger.info(f"🗑️ [工作区] 话题 {thread_id} ({summary}) 已被物理隔离。")
            # 发射信号通知 Orchestrator 进行后台总结
            asyncio.create_task(
                self.event_bus.publish("memory_archived", thread_id, qos=QoS.BACKGROUND)
            )
            if self.suspend_timer_task:
                self.suspend_timer_task.cancel()

    def generate_id(self) -> str:
        """生成线程 ID"""
        return str(uuid.uuid4())[:6]

    def create_new(self, thread_id: str, summary: str):
        """开辟新话题"""
        self.current_id = thread_id
        self.thread_pool[thread_id] = CognitiveThread(thread_id, summary, "", ThreadStatus.RUNNING)
        logger.info(f"✨ [工作区] 开启全新线程: {summary} (ID: {thread_id})")

    def resume(self, thread_id: str):
        """弹栈恢复话题"""
        if thread_id in self.thread_pool:
            self.current_id = thread_id
            self.thread_pool[thread_id].status = ThreadStatus.RUNNING
            self.thread_pool[thread_id].unspoken_text = ""
            logger.info(f"♻️ [工作区] 唤醒并接续历史话题 (ID: {thread_id})")
            if self.suspend_timer_task:
                self.suspend_timer_task.cancel()