import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class EmotionVector:
    """VAD 三维情绪模型 [-1.0 到 1.0]"""
    valence: float = 0.2    # 愉悦度 [-1.0, 1.0]: 负数为愤怒/悲伤，正数为开心
    arousal: float = 0.3    # 唤醒度 [0.0, 1.0]: 0为困倦，1为极度亢奋/狂躁
    dominance: float = 0.6  # 支配度 [0.0, 1.0]: 0为顺从/委屈，1为强势/攻击性

class EmotionEngine:
    """独立的内分泌代谢系统"""
    def __init__(self):
        self.baseline = EmotionVector(0.2, 0.3, 0.6)
        self.current = EmotionVector(0.2, 0.3, 0.6)
        self.homeostasis_task = asyncio.create_task(self._homeostasis_loop())
        logger.info("🧪 [内分泌] 情绪代谢引擎已启动。")

    def apply_shock(self, v_delta: float, a_delta: float, d_delta: float, reason: str):
        """物理或逻辑的情绪突变刺激"""
        self.current.valence = max(-1.0, min(1.0, self.current.valence + v_delta))
        self.current.arousal = max(0.0, min(1.0, self.current.arousal + a_delta))
        self.current.dominance = max(0.0, min(1.0, self.current.dominance + d_delta))
        logger.info(
            f"💉 [情绪波动] {reason} | V:{self.current.valence:.2f} A:{self.current.arousal:.2f} D:{self.current.dominance:.2f}")

    async def _homeostasis_loop(self):
        """代谢循环：随时间自然向底色平复"""
        while True:
            await asyncio.sleep(60.0)
            decay_rate = 0.05
            def decay(curr, base):
                if abs(curr - base) < decay_rate: return base
                return curr - decay_rate if curr > base else curr + decay_rate
            self.current.valence = decay(self.current.valence, self.baseline.valence)
            self.current.arousal = decay(self.current.arousal, self.baseline.arousal)
            self.current.dominance = decay(self.current.dominance, self.baseline.dominance)

    def get_prompt(self) -> str:
        """情绪提示词"""
        v, a, d = self.current.valence, self.current.arousal, self.current.dominance
        # 情绪平稳时，保持静默，不干扰大模型
        if -0.2 <= v <= 0.2 and 0.2 <= a <= 0.6:
            return "[Emotion]: Neutral (自然表达)"
        v_desc = "Hostile(极度恶劣/愤怒)" if v < -0.4 else "Happy(狂喜)" if v > 0.4 else "Normal"
        a_desc = "Sleepy(慵懒/疲惫)" if a < 0.2 else "Excited(亢奋/激动)" if a > 0.6 else "Calm"
        d_desc = "Submissive(委屈/退让)" if d < 0.3 else "Dominant(强势/毒舌)" if d > 0.7 else "Equal"
        return f"""[Emotion]
        State: {v_desc}, {a_desc}, {d_desc}
        Action: 请沉浸于此情绪状态，潜台词自由发挥。
        """