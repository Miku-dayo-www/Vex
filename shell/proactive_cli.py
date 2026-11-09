import asyncio
import sys
import logging

logger = logging.getLogger(__name__)

class AsyncCLI:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        # 订阅大脑发来的回复
        self.event_bus.subscribe("agent_reply", self._handle_agent_reply)
        self._prompt = "🧑 指挥官: "

    async def _handle_agent_reply(self, message: str):
        """当收到大脑的消息时，非阻塞地打断终端并打印"""
        # \r 回到行首，\033[K 清除当前行（这能完美抹除你输入到一半的字符，防止排版错乱）
        sys.stdout.write(f"\r\033[K🤖 [AI 主宰]: {message}\n")
        # 打印完 AI 的消息后，迅速恢复你的输入提示符
        sys.stdout.write(self._prompt)
        sys.stdout.flush()

    async def run(self):
        """异步非阻塞的交互循环"""
        await asyncio.sleep(2)  # 稍微等待 2 秒，让系统的启动日志先飞一会儿
        while True:
            try:
                sys.stdout.write(self._prompt)
                sys.stdout.flush()

                # 【核心解法】：将阻塞的 readline 操作委托给后台线程！
                # 此时事件总线 (Event Bus) 和大模型 (Orchestrator) 依然在主线程飞速运转。
                user_input = await asyncio.to_thread(sys.stdin.readline)
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.lower() in ['exit', 'quit']:
                    print("🔌 正在物理切断神经连接...")
                    # 触发全局关机事件，通知所有模块停止
                    await self.event_bus.publish("system_shutdown", {})
                    break

                # 将指令扔进事件总线。扔完立刻进行下一次循环，无需傻等大模型思考！
                await self.event_bus.publish("user_instruction", user_input)

            except Exception as e:
                logger.error(f"终端崩溃: {e}")
                break