import subprocess
import logging
import asyncio
from brain.config import settings

logger = logging.getLogger(__name__)

class PowerShellServer:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.cwd = settings.desktop_path  # 强制执行目录为沙盒

        # 黑名单扩展，并移除了可能误杀的过短字符串
        self.blacklist = [
            "remove-item", "rmdir", "del ", "erase ", "stop-process",
            "restart-computer", "stop-computer", "shutdown",
            "format-volume", "clear-disk", "diskpart", "set-executionpolicy"
        ]
        logger.info(f"💻 PowerShell MCP Server 已挂载。工作目录锁定于: {self.cwd}")

    def run_powershell(self, command: str, timeout: int = 60) -> dict:
        cmd_lower = command.lower()

        # 1. 拦截高危指令并向全局总线报警！
        for b in self.blacklist:
            if b in cmd_lower:
                alert_msg = f"检测到破坏性指令 [{b}]，已执行物理熔断！"
                logger.warning(f"🛡️ 安全拦截: {alert_msg}")

                # 触发异步告警 (如果是供同步环境调用，需放入事件循环)
                try:
                    loop = asyncio.get_running_loop()
                    asyncio.run_coroutine_threadsafe(
                        self.event_bus.publish("system_toast", {
                            "title": "🚨 AI 越权告警",
                            "content": alert_msg
                        }),
                        loop
                    )
                except Exception:
                    pass  # 防御性忽略

                return {"success": False, "output": f"安全拦截：{alert_msg}"}

        # 2. 受限执行环境
        try:
            ps_args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
            # 强制 cwd 为自定义桌面路径
            result = subprocess.run(
                ps_args,
                capture_output=True,
                timeout=timeout,
                cwd=self.cwd
            )

            def smart_decode(byte_data):
                for enc in settings.cmd_encodings:
                    try:
                        return byte_data.decode(enc, errors='strict')
                    except UnicodeDecodeError:
                        continue
                return byte_data.decode(settings.cmd_encodings[0], errors='ignore')

            stdout_str = smart_decode(result.stdout).strip()
            stderr_str = smart_decode(result.stderr).strip()

            parts = []
            if stdout_str: parts.append(stdout_str)
            if stderr_str: parts.append(f"[Error Info]:\n{stderr_str}")
            final_output = "\n".join(parts) if parts else "执行成功，无回显。"

            if len(final_output) > settings.cmd_max_output_length:
                final_output = final_output[:settings.cmd_max_output_length] + "\n\n...[截断]..."

            return {"success": result.returncode == 0, "output": final_output}

        except subprocess.TimeoutExpired:
            return {"success": False, "output": f"执行超时强杀 ({timeout}s)"}
        except Exception as e:
            return {"success": False, "output": str(e)}