import asyncio
import logging
import time
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)

class QoS(IntEnum):
    """神经递质优先级:数字越小，优先级越高，越先被系统处理"""
    REFLEX = 0      # 脊髓反射级：0ms 响应。用于物理打断 (interrupt_tts)、强行关机等。
    SENSORY = 1     # 感觉神经级：视觉/听觉的识别结果、意图判定输入。
    COGNITIVE = 2   # 大脑皮层级：常规的 LLM 思考指令、工具调用。(默认级别)
    BACKGROUND = 3  # 自律神经级：后台记忆摘要整理、潜意识固化。绝不阻塞主线程。

@dataclass(order=True)
class EventPacket:
    """包装神经信号，利用 dataclass 的 order 属性实现优先队列的自动排序"""
    priority: int
    timestamp: float
    event_type: str = field(compare=False)
    payload: Any = field(compare=False)

class EventBus:
    """全局异步优先事件总线：Agent 的神经网络"""
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._queue = asyncio.PriorityQueue()

    # 阻断深拷贝：大模型 SDK 复制工具环境时直接返回自身引用
    # 避开 asyncio.Queue 内部 _thread.lock 无法序列化的问题
    def __deepcopy__(self, memo):
        return self

    def subscribe(self, event_type: str, callback: Callable):
        """订阅特定事件"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"已订阅事件: {event_type}")

    async def publish(self, event_type: str, payload: Any = None, qos: QoS = QoS.COGNITIVE):
        """发布事件：默认走大脑皮层级，紧急事件请指定 QoS.REFLEX"""
        # 封装信号包，时间戳用于在相同优先级下保证先进先出 (FIFO)
        packet = EventPacket(
            priority=qos.value,
            timestamp=time.time(),
            event_type=event_type,
            payload=payload
        )
        await self._queue.put(packet)
        if qos == QoS.REFLEX:
            logger.warning(f"⚡ [神经突触] 触发反射级极高优信号: {event_type}")

    async def run(self):
        logger.info("⚡ 中枢神经系统 (QoS Event Bus) 已激活，优先级路由开启...")
        while True:
            packet = await self._queue.get()
            callbacks = self._subscribers.get(packet.event_type, [])

            for callback in callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback(packet.payload))
                    else:
                        callback(packet.payload)
                except Exception as e:
                    logger.error(f"神经元执行异常 [{packet.event_type}]: {e}")

            self._queue.task_done()