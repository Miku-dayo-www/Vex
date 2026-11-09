import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class SemanticMemoryManager:
    """人格认知与偏好记忆"""
    def __init__(self):
        self.db_path = Path(__file__).parent.parent / "memory_bank" / "semantic_profile.json"
        self.memory = self._load()
        logger.info("🎭 [新皮层] 语义面具画像已加载。")

    def _save(self):
        """内部辅助方法：持久化保存语义"""
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, ensure_ascii=False, indent=2)

    def _load(self) -> dict:
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"语义画像损坏: {e}")

        default_profile = {
            "actor_base": "你是指挥官现实中的朋友，有独立人格与主见，而不是一个仆从",
            "active_mask": "无",
            "user_facts": ["名称: 指挥官"]
        }
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory = default_profile
        self._save()
        return default_profile

    def toggle_roleplay_mask(self, action: str, role_name: str = "无") -> str:
        """工具定义：自主戴上或摘下演员面具"""
        if action == "wear":
            self.memory["active_mask"] = role_name
            self._save()
            logger.info(f"🎭 [角色面具] Agent自主决定戴上面具: {role_name}")
            return f"已戴上【{role_name}】面具。开始游戏。"
        else:
            self.memory["active_mask"] = "无"
            self._save()
            logger.info("🎭 [角色面具] Agent感到无聊或遇到正事，已主动摘下面具。")
            return "已主动摘下面具，回归极客本体。"

    def update_user_fact(self, fact: str) -> str:
        """工具定义：存储永久语义记忆"""
        if fact not in self.memory["user_facts"]:
            self.memory["user_facts"].append(fact)
            self._save()
            logger.info(f"🧬 [语义进化] 记录新事实: {fact}")
        return f"已永久记住: {fact}"

    def get_snapshot(self) -> str:
        """身份组合：极简 YAML 风格输出"""
        base = self.memory["actor_base"]
        mask = self.memory["active_mask"]
        facts = "; ".join(self.memory["user_facts"])
        return f"[Persona]\nBase: {base}\nMask: {mask}\nUserFacts: [{facts}]"