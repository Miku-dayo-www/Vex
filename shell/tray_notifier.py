import logging
import threading
import time
import pystray
from PIL import Image, ImageDraw
import asyncio

logger = logging.getLogger(__name__)

class TrayNotifier:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.icon = None
        # 捕获主线程的 asyncio 事件循环，这是跨线程通信的桥梁！
        self.loop = asyncio.get_running_loop()
        self._setup_icon()

        # 向总线订阅气泡弹窗事件
        self.event_bus.subscribe("system_toast", self._handle_toast_event)

    def _create_image(self):
        """动态绘制系统托盘的极客图标"""
        width, height = 64, 64
        image = Image.new('RGB', (width, height), color=(20, 20, 20))
        dc = ImageDraw.Draw(image)
        dc.ellipse((16, 16, 48, 48), outline=(0, 255, 128), width=4)
        dc.ellipse((24, 24, 40, 40), fill=(0, 255, 128))
        return image

    def _on_status_clicked(self, icon, item):
        """用户在托盘右键点击状态时触发"""
        # 【重要】pystray 运行在独立线程，向 asyncio 发布事件必须用 threadsafe
        asyncio.run_coroutine_threadsafe(
            self.event_bus.publish("system_toast", {
                "title": "系统状态",
                "content": "AI 核心神经元运转正常，随时待命。"
            }),
            self.loop
        )

    def _on_quit_clicked(self, icon, item):
        """用户点击退出"""
        logger.info("接收到 UI 退出指令，正在停止托盘图标...")
        icon.stop()
        # 通知总线，准备全局关机
        asyncio.run_coroutine_threadsafe(
            self.event_bus.publish("system_shutdown", {}),
            self.loop
        )

    def _setup_icon(self):
        """组装右下角菜单"""
        menu = pystray.Menu(
            pystray.MenuItem("查看状态", self._on_status_clicked),
            pystray.MenuItem("断开神经连接 (退出)", self._on_quit_clicked)
        )
        self.icon = pystray.Icon("AI_OS_Core", self._create_image(), "AI 系统管家", menu)

    async def _handle_toast_event(self, payload: dict):
        """[核心逻辑] 监听到总线的系统弹窗请求，执行物理弹窗"""
        title = payload.get("title", "系统通知")
        content = payload.get("content", "")
        if self.icon and self.icon.HAS_NOTIFICATION:
            # pystray 的 notify 方法是线程安全的，可以直接调用
            self.icon.notify(content, title)
        else:
            logger.warning("系统托盘未就绪或当前系统不支持气泡通知")

    def run_in_background(self):
        """将原本会阻塞主线程的 tray.run() 降维打击到子线程"""

        def _run():
            logger.info("🖥️ 托盘 UI 线程已挂载")
            # 解决原本初始化太快无法弹窗的问题
            threading.Thread(target=self._delayed_startup_toast, daemon=True).start()
            self.icon.run()

        tray_thread = threading.Thread(target=_run, daemon=True)
        tray_thread.start()
        return tray_thread

    def _delayed_startup_toast(self):
        """开机 1.5 秒后，向总线发送第一条弹窗欢迎词"""
        time.sleep(1.5)
        asyncio.run_coroutine_threadsafe(
            self.event_bus.publish("system_toast", {
                "title": "系统主宰已上线",
                "content": "异步引擎初始化完成！托盘已接管。"
            }),
            self.loop
        )