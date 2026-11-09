import sys
import asyncio
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*pkg_resources is deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)
import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

class CodeInterpreterServer:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        # 确保沙盒目录存在
        self.sandbox_dir = Path(__file__).parent.parent.parent / "sandbox"
        self.sandbox_dir.mkdir(exist_ok=True)
        logger.info(f"🐍 Code Interpreter [全异步防弹版] 已挂载，专用沙盒目录: {self.sandbox_dir}")

    async def execute_python_code(self, code: str, timeout: int = 60) -> dict:
        """
        全异步工业级 Python 代码解释器：
        1. 采用 UUID 防并发覆盖 (解决 PID 冲突)
        2. 采用 asyncio.create_subprocess_exec 防阻塞主循环 (解决 EventLoop 冻结)
        3. 掐断 stdin，配置防死锁环境变量 (防管道死锁)
        """
        script_name = f"runner_{uuid.uuid4().hex[:8]}.py"
        script_path = self.sandbox_dir / script_name
        try:
            # 写入临时脚本
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)

            logger.info(f"⚙️ 正在执行 AI 代码 (沙盒位置: {script_path})...")

            # 配置防死锁环境变量
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["OMP_NUM_THREADS"] = "1"
            env["OPENBLAS_NUM_THREADS"] = "1"
            env["MKL_NUM_THREADS"] = "1"

            # 配置 Windows 专属标志防崩溃弹窗
            creationflags = 0
            if sys.platform == "win32":
                creationflags = 0x08000000  # 等同于 subprocess.CREATE_NO_WINDOW 的常量值

            # 【修复点 2】：使用全异步的 subprocess 创建方法，彻底释放主线程
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-u", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,  # 掐断输入源
                env=env,
                creationflags=creationflags
            )

            try:
                # 使用异步的 communicate，并设定超时时间
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # 处理超时情况：先物理强杀，再读取残局
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

                # 读取最后残留的输出日志
                stdout_data, stderr_data = await process.communicate()
                out_str = stdout_data.decode("utf-8", errors="replace").strip()
                err_str = stderr_data.decode("utf-8", errors="replace").strip()

                error_msg = f"执行超时：代码运行超过 {timeout} 秒被强制终止。\n最后输出:\n{out_str}\n遗留报错:\n{err_str}"
                logger.warning(f"AI 代码超时死锁:\n{error_msg}")
                return {"success": False, "error": error_msg}

            # 正常执行完毕，解码输出
            output = stdout_data.decode("utf-8", errors="replace").strip()
            error = stderr_data.decode("utf-8", errors="replace").strip()

            if process.returncode == 0:
                final_res = output if output else "代码执行成功，无终端输出 (stdout)。"
                return {"success": True, "data": final_res}
            else:
                error_msg = f"代码执行崩溃 (Exit code {process.returncode}):\n{error}"
                logger.warning(f"AI 代码报错:\n{error_msg}")
                return {"success": False, "error": error_msg}

        except Exception as e:
            return {"success": False, "error": f"异步解释器底层异常: {str(e)}"}
        finally:
            # 无论成功失败，确保清理沙盒临时文件
            if script_path.exists():
                try:
                    os.remove(script_path)
                except Exception:
                    pass