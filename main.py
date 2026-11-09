import asyncio
import ctypes
import logging
from brain.mmu_facade import MMUFacade
from brain.orchestrator import OSOrchestrator
from ears.auditory_cortex import AuditoryCortex
from ears.vad_asr_engine import EarsEngine
from mouth.tts_engine import MouthEngine
from nervous_system.event_bus import EventBus
from shell.proactive_cli import AsyncCLI
from shell.tray_notifier import TrayNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("MainOS")

def boost_process_priority():
    """强制解除 Windows EcoQoS，锁定高优先级"""
    try:
        # noinspection PyUnresolvedReferences
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        # noinspection PyUnresolvedReferences
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000080)
        # noinspection PyUnresolvedReferences
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        logging.getLogger("MainOS").info("🚀 [物理提权] 已强行解除 Windows 后台降频限制，锁定 CPU/GPU 高优先级！")
    except Exception as e:
        logging.getLogger("MainOS").warning(f"⚠️ 物理提权失败: {e}")

async def main():
    boost_process_priority()

    logger.info("🚀 AI Agent Master OS 正在启动...")

    # 1. 初始化中枢神经 (QoS Event Bus)
    event_bus = EventBus()
    bus_task = asyncio.create_task(event_bus.run())

    # 2. 挂载 UI 托盘
    tray_ui = TrayNotifier(event_bus)
    tray_ui.run_in_background()

    # 3. 挂载海马体 (独立自治的内存管理单元)
    mmu = MMUFacade(event_bus)

    # 4. 挂载大脑皮层 (注入 event_bus 和 mmu)
    brain = OSOrchestrator(event_bus, mmu)
    brain_task = asyncio.create_task(brain.run_background_loop())

    # 5. 挂载听觉皮层
    mid_brain = AuditoryCortex(event_bus, mmu)

    logger.info("⏳ 系统正在等待 GPU 与深度学习引擎启动...")

    # 6. 挂载嘴巴
    mouth = MouthEngine(event_bus)

    logger.info("✅ 核心引擎加载完毕，正在开启物理感知设备...")

    # 7. 挂载耳蜗 (听觉底层采集与物理拦截)
    ears = EarsEngine(event_bus)
    ears.run_in_background()

    # 8. 挂载异步终端交互
    cli = AsyncCLI(event_bus)
    cli_task = asyncio.create_task(cli.run())

    logger.info("🎉 [系统就绪] 所有感官器官已贯通，Agent 现已进入全双工待机状态！")

    # 9. 监听关机信号，优雅退出
    async def shutdown_handler(_):
        logger.info("收到关机指令，正在清理底层资源与协程...")
        if 'ears' in locals():
            ears.stop()  # 释放麦克风音频流
            logger.info("✅ 听觉中枢已离线。")
        if 'mouth' in locals():
            mouth.stop()  # 向 TTS 子进程发送毒丸并等待其安全释放显存
            logger.info("✅ 发声器官及显存已释放。")
        for task in [bus_task, brain_task, cli_task]:
            if not task.done():
                task.cancel()

    event_bus.subscribe("system_shutdown", shutdown_handler)
    # 并发执行
    try:
        await asyncio.gather(bus_task, brain_task, cli_task)
    except asyncio.CancelledError:
        logger.info("✅ 核心协程已全部安全销毁。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 收到硬中断信号，系统下线。")
        import multiprocessing
        for p in multiprocessing.active_children():
            p.terminate()