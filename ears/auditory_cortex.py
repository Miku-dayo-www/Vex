import logging
import jieba
from ears.vocabulary_list import SAFE_BACKCHANNELS, INTENT_CORPUS

logger = logging.getLogger(__name__)

class AuditoryCortex:
    """听觉皮层：本地极速路由器，高效零误判的“多维精确拦截”"""
    def __init__(self, event_bus, mmu):
        self.event_bus = event_bus
        self.mmu = mmu
        self._init_jieba_hack()
        self.event_bus.subscribe("user_instruction", self._route_instruction)

    def _init_jieba_hack(self):
        logger.info("🧠 [听觉皮层] 正在向 Jieba 注入强制指令词典...")
        self.intent_sets = {
            "REJECT": set(INTENT_CORPUS["REJECT"]),
            "RESUME": set(INTENT_CORPUS["RESUME"]),
            "HESITATION": set(INTENT_CORPUS["HESITATION"])
        }
        for intent_type, words in self.intent_sets.items():
            for word in words:
                if len(word) >= 2:
                    jieba.add_word(word, freq=99999)
                else:
                    jieba.add_word(word)
        jieba.lcut("预热启动")
        logger.info("✅ [听觉皮层] 词典劫持完成，精确分词雷达已上线。")

    def _safe_intent_match(self, user_words: set, clean_text: str, intent_type: str) -> bool:
        """终极防弹装甲：动态长度锚定 + 极端标点清洗"""
        hits = user_words & self.intent_sets[intent_type]
        if not hits:
            return False
        # 剥离边缘符号
        pure_text = clean_text.strip(" 。，！？.,!?~…·\"'“”‘’\r\n\t-")
        for hit in hits:
            # 长度 >= 3 的明确长指令（如 "换个话题", "别说了", "等一下"）
            if len(hit) >= 3:
                logger.info(f"🎯 [意图雷达] 锁定长指令: {hit} -> {intent_type}")
                return True
            # 长度 <= 2 的短指令（如 "停", "继续", "算了", "闭嘴"）
            if pure_text == hit or pure_text.startswith(hit) or pure_text.endswith(hit):
                logger.info(f"🎯 [意图雷达] 锁定短指令: {hit} -> {intent_type}")
                return True
        return False

    def _fast_intent_classification(self, text: str, has_suspended_thread: bool) -> str:
        clean_text = text.replace(" ", "").strip()
        if len(clean_text) <= 2 and all(char in SAFE_BACKCHANNELS for char in clean_text):
            return "NORMAL_CHAT"
        if len(clean_text) >= 12:
            return "NORMAL_CHAT"
        user_words = set(jieba.lcut(clean_text))
        if self._safe_intent_match(user_words, clean_text, "REJECT"):
            return "REJECT"
        if has_suspended_thread and self._safe_intent_match(user_words, clean_text, "RESUME"):
            return "RESUME"
        if len(clean_text) <= 6 and self._safe_intent_match(user_words, clean_text, "HESITATION"):
            return "HESITATION"
        return "NORMAL_CHAT"

    async def _route_instruction(self, user_input: str):
        """MDP 核心转移矩阵：根据意图操控 MMU，组装 Prompt 交给大脑皮层"""
        logger.info(f"🧠 [中脑路由] 接收到原始听觉信号: {user_input}")
        has_suspended = any(t.status.name == "SUSPENDED" for t in self.mmu.thread_pool.values())
        suspended_thread = next((t for t in self.mmu.thread_pool.values() if t.status.name == "SUSPENDED"), None)
        intent = self._fast_intent_classification(user_input, has_suspended)
        action_prompt = ""
        if intent == "HESITATION":
            logger.info("🧠 [边缘系统] 感知到用户犹豫，发射倾听反射信号。")
            await self.event_bus.publish("play_filler", {"is_first_step": False})
        elif intent == "RESUME" and suspended_thread:
            unspoken_residue = suspended_thread.unspoken_text
            self.mmu.resume_thread(suspended_thread.thread_id)
            action_prompt = f"【动作强制要求】：用户要求继续刚才的话题。请极其自然地接着说完你被打断的这段话：“{unspoken_residue}”"
        elif intent == "REJECT":
            if self.mmu.current_thread_id:
                self.mmu.archive_thread(self.mmu.current_thread_id)
            if suspended_thread:
                self.mmu.archive_thread(suspended_thread.thread_id)
            new_id = self.mmu.generate_new_thread_id()
            self.mmu.create_new_thread(new_id, "新任务")
            action_prompt = "【动作强制要求】：用户刚刚明确拒绝了旧话题。请直接回答他的新输入，完全不要提及任何旧话题。"
        else:
            if not self.mmu.current_thread_id:
                new_id = self.mmu.generate_new_thread_id()
                self.mmu.create_new_thread(new_id, "日常对话")
            action_prompt = "【动作强制要求】：自然简短回复用户的输入。"
        payload = {"user_input": user_input, "action_prompt": action_prompt}
        await self.event_bus.publish("llm_execute_task", payload)