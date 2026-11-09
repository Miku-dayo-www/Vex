import logging
from pathlib import Path
import shutil

logger = logging.getLogger(__name__)

class FileSystemServer:
    def __init__(self):
        logger.info("📁 FS Server [终极自由形态] 已挂载，全面接管本地文件系统。")

    def list_directory(self, path: str) -> dict:
        """强化版：支持统计、隐藏文件过滤，并按类型排序"""
        try:
            target = Path(path).resolve()
            if not target.exists() or not target.is_dir():
                return {"success": False, "error": f"路径 {target} 无效或不是一个文件夹"}

            # 使用 iterdir 获取所有子项
            items = list(target.iterdir())
            dirs = []
            files = []
            for item in items:
                name = item.name
                # 过滤掉系统隐藏文件、临时锁定文件，保持返回结果干净
                if name.startswith("~$") or name.startswith(".") or name.lower() in ["desktop.ini", "thumbs.db"]:
                    continue

                if item.is_dir():
                    dirs.append(name)
                else:
                    # 附带文件大小信息，帮助模型更好地决策
                    size_kb = round(item.stat().st_size / 1024, 2)
                    files.append(f"{name} ({size_kb} KB)")

            # 对结果进行字典序排序，方便模型阅读
            dirs.sort()
            files.sort()
            res = (
                f"📂 目录 {target} 扫描完毕。\n"
                f"统计信息：包含 {len(dirs)} 个文件夹，{len(files)} 个文件。\n\n"
                f"[📁 文件夹列表]:\n{', '.join(dirs) if dirs else '无'}\n\n"
                f"[📄 文件列表]:\n{', '.join(files) if files else '无'}"
            )
            return {"success": True, "data": res}

        except Exception as e:
            logger.error(f"FS Server 扫描目录失败 [{path}]: {e}")
            return {"success": False, "error": f"底层异常: {str(e)}"}

    def read_file(self, file_path: str, offset: int = 0, limit: int = 2000) -> dict:
        """强化版：支持多种编码轮询、超大文件截断和行号标记"""
        target = Path(file_path).resolve()
        try:
            if not target.exists():
                return {"success": False, "error": f"文件不存在: {target}"}
            if not target.is_file():
                return {"success": False, "error": f"目标不是一个文件: {target}"}

            # 定义常见的文本编码列表，从上到下依次尝试解码
            encodings_to_try = ["utf-8", "gbk", "cp936", "utf-16"]
            for enc in encodings_to_try:
                try:
                    with open(target, "r", encoding=enc) as f:
                        # 采用基于行的切片，防止读取几个 G 的日志文件撑爆内存
                        lines = []
                        for _ in range(offset):
                            next(f, None)

                        # 读取指定的 limit 行
                        for _ in range(limit):
                            line = next(f, None)
                            if line is None:
                                break
                            lines.append(line)

                    # 为每一行添加物理行号，方便大模型精准修改
                    numbered = "".join(f"{offset + i + 1}\t{line}" for i, line in enumerate(lines))
                    # 检查是否还有剩余内容
                    has_more = False
                    with open(target, "r", encoding=enc) as f:
                        # 粗略判断：如果跳过 offset+limit 后还能读出一行，说明被截断了
                        for _ in range(offset + limit): next(f, None)
                        if next(f, None) is not None: has_more = True

                    if has_more:
                        numbered += f"\n\n... (警告：文件过长，当前仅展示 {offset} 到 {offset + limit} 行。如果需要，请调大 offset 继续往后读) ..."
                    return {"success": True, "data": numbered}

                except UnicodeDecodeError:
                    # 如果当前编码失败，换下一个继续尝试
                    continue
                except StopIteration:
                    pass

            return {"success": False,
                    "error": f"文件读取失败，尝试了 {encodings_to_try} 均无法解码，这可能是一个二进制文件。"}

        except Exception as e:
            logger.error(f"FS Server 读取文件失败 [{file_path}]: {e}")
            return {"success": False, "error": f"底层异常: {str(e)}"}

    def write_file(self, file_path: str, content: str) -> dict:
        """自动创建层级目录，强制覆写"""
        target = Path(file_path).resolve()
        try:
            # 自动创建不存在的父级目录结构 (mkdir -p)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "data": f"✅ 文件内容已成功写入: {target}"}

        except Exception as e:
            logger.error(f"FS Server 写入文件失败 [{file_path}]: {e}")
            return {"success": False, "error": f"底层写入异常: {str(e)}"}

    def delete_item(self, target_path: str) -> dict:
        """彻底物理删除文件或文件夹 (无视只读属性)"""
        target = Path(target_path).resolve()
        try:
            if not target.exists():
                return {"success": False, "error": f"删除失败，目标不存在: {target}"}

            if target.is_dir():
                shutil.rmtree(target)  # 递归删除整个目录
                return {"success": True, "data": f"✅ 文件夹已从物理磁盘抹除: {target}"}
            else:
                target.unlink()  # 删除单文件
                return {"success": True, "data": f"✅ 文件已从物理磁盘抹除: {target}"}

        except Exception as e:
            logger.error(f"FS Server 删除失败 [{target_path}]: {e}")
            return {"success": False, "error": f"物理删除失败，请检查文件是否被占用: {str(e)}"}