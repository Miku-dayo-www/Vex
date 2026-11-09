import logging
from typing import List, Dict
from brain.memory_management.semantic import SemanticMemoryManager
from brain.memory_management.episodic import EpisodicMemoryManager
from brain.memory_management.conversations import ConversationManager
from brain.emotion_engine import EmotionEngine

logger = logging.getLogger(__name__)

class MMUFacade:
    """【认知内存管理单元 - 全局门面】
    它是整个 Agent 的灵魂容器总控。对外暴露极简 API，对内协调各大器官。
    """
    def __init__(self, event_bus):
        self.event_bus = event_bus
        logger.info("🧠 [MMU 总控] 正在唤醒系统底层器官...")
        self.semantic = SemanticMemoryManager()
        self.episodic = EpisodicMemoryManager()
        self.emotion = EmotionEngine()
        self.conversations = ConversationManager(event_bus=self.event_bus, episodic_memory=self.episodic)
        self.event_bus.subscribe("tts_interrupted_report", self._handle_physical_interruption)
        logger.info("✅ [MMU 总控] 所有记忆与情绪装载完毕。")

    # ==========================================
    # 🧬 聚合 API：专供 Orchestrator 获取上帝视角
    # ==========================================
    def get_semantic_snapshot(self) -> str:
        """获取底层人设与面具画像"""
        return self.semantic.get_snapshot()

    def get_emotional_prompt(self) -> str:
        """获取当前内分泌的情绪提示词"""
        return self.emotion.get_prompt()

    # ==========================================
    # 🎭 面具与偏好 API (路由至 Semantic)
    # ==========================================
    def toggle_roleplay_mask(self, action: str, role_name: str = "无") -> str:
        return self.semantic.toggle_roleplay_mask(action, role_name)

    def update_user_fact(self, fact: str) -> str:
        return self.semantic.update_user_fact(fact)

    # ==========================================
    # 🧪 情绪内分泌 API (路由至 Emotion)
    # ==========================================
    def apply_emotional_shock(self, v_delta: float, a_delta: float, d_delta: float, reason: str):
        self.emotion.apply_shock(v_delta, a_delta, d_delta, reason)

    # ==========================================
    # 🌌 情景流水账 API (路由至 Episodic)
    # ==========================================
    async def recall_subconscious(self, query: str) -> str:
        return await self.episodic.recall_subconscious(query)

    async def memorize_to_vector_db(self, thread_id: str, summary_content: str):
        return await self.episodic.memorize(thread_id, summary_content)

    # ==========================================
    # 🧵 线程与短时记忆 API (路由至 Conversations)
    # ==========================================
    @property
    def thread_pool(self):
        return self.conversations.thread_pool

    @property
    def current_thread_id(self) -> str | None:
        return self.conversations.current_id

    def get_working_memory(self, limit: int = 5) -> List[Dict[str, str]]:
        return self.conversations.get_working_memory(limit)

    def commit_turn(self, user_text: str, ai_text: str):
        self.conversations.commit_turn(user_text, ai_text)

    def commit_ai_continuation(self, ai_text: str):
        self.conversations.commit_ai_continuation(ai_text)

    def archive_thread(self, thread_id: str):
        self.conversations.archive_thread(thread_id)

    def resume_thread(self, thread_id: str):
        self.conversations.resume(thread_id)

    def generate_new_thread_id(self) -> str:
        return self.conversations.generate_id()

    def create_new_thread(self, thread_id: str, summary: str):
        self.conversations.create_new(thread_id, summary)

    def build_context_snapshot(self) -> str:
        return self.conversations.build_context_snapshot()

    async def _handle_physical_interruption(self, payload: dict):
        unspoken = payload.get("unspoken_text", "")
        self.conversations.suspend_current(unspoken)