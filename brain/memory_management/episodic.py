import asyncio
import logging
import re
import time
from datetime import datetime
from pathlib import Path
import chromadb
import jionlp as jio

logger = logging.getLogger(__name__)

class EpisodicMemoryManager:
    """管理 ChromaDB 向量情景流水账"""
    def __init__(self):
        self.db_path = str(Path(__file__).parent.parent / "memory_bank")
        self.readable_log_path = Path(self.db_path) / "episodic_diary.md"
        self.client = None
        self.collection = None
        self._init_db()

    def _init_db(self):
        try:
            self.client = chromadb.PersistentClient(path=self.db_path)
            self.collection = self.client.get_or_create_collection(name="episodic_memory")
            if not self.readable_log_path.exists():
                self.readable_log_path.write_text("# 情景记忆录\n\n", encoding="utf-8")
            logger.info("🌌 [海马体] ChromaDB 向量情景记忆库已成功加载！")
        except Exception as e:
            logger.error(f"向量数据库加载失败: {e}")

    async def memorize(self, thread_id: str, summary_content: str):
        """后台记忆固化：将归档的摘要写入向量库"""
        if self.collection is None:
            return
        def _add_to_db():
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.collection.add(
                documents=[summary_content],
                metadatas=[{"thread_id": thread_id, "timestamp": current_time}],
                ids=[f"mem_{thread_id}"]
            )
            try:
                with open(self.readable_log_path, "a", encoding="utf-8") as f:
                    f.write(f"### 🕒 [{current_time}] (话题ID: {thread_id})\n")
                    f.write(f"> **记录**: {summary_content}\n\n")
                    f.write("---\n")
            except Exception as log_e:
                logger.error(f"写入可读日志失败: {log_e}")
        try:
            await asyncio.to_thread(_add_to_db)
            logger.info(f"💾 [潜意识固化] 话题 {thread_id} 的核心记忆已永久写入向量海马体！")
        except Exception as e:
            logger.error(f"记忆固化失败: {e}")

    def _extract_time_filter(self, text: str) -> dict | None:
        """高级时间细胞：调用本地 Time-NLP 引擎"""
        try:
            time_entities = jio.ner.extract_time(text, time_base=time.time())
            if not time_entities:
                return None
            parsed_time = time_entities[0]['detail']['time']
            # 处理范围时间
            if isinstance(parsed_time, list) and len(parsed_time) == 2:
                start_time = parsed_time[0]
                end_time = parsed_time[1]
                return {
                    "$and": [
                        {"timestamp": {"$gte": start_time[:16]}},
                        {"timestamp": {"$lte": end_time[:16]}}
                    ]
                }
            # 处理绝对时间点
            elif isinstance(parsed_time, str):
                return {
                    "timestamp": {
                        "$gte": parsed_time[:16]
                    }
                }
        except Exception as e:
            logger.warning(f"时间细胞解析异常, 降级为无约束检索: {e}")
        return None

    async def recall_subconscious(self, query: str) -> str:
        """动态记忆召回：通过向量相似度从过往记忆中提取内容"""
        if self.collection is None:
            return ""
        time_filter = self._extract_time_filter(query)
        enumeration_pattern = re.compile(
            r"(找|查|看|列|说|发|记得|回忆|总结|提取|有哪些|告诉我).{0,12}?(所有|全部|每个|每次|清单|那些|哪些)|"
            r"(所有|全部|每个|每次|清单|那些|哪些).{0,12}?(找|查|看|列|说|发|回忆|总结|提取|有哪些|告诉我)"
        )
        is_enumeration = bool(enumeration_pattern.search(query))

        def _query_db():
            fetch_count = 10 if is_enumeration else 5
            if time_filter:
                return self.collection.query(
                    query_texts=[query], n_results=fetch_count, where=time_filter,
                    include=["documents", "metadatas", "distances"]
                )
            else:
                return self.collection.query(
                    query_texts=[query], n_results=fetch_count, include=["documents", "metadatas", "distances"]
                )
        try:
            results = await asyncio.to_thread(_query_db)
            if not results or not results['documents'] or not results['documents'][0]: return ""
            docs = results['documents'][0]
            metas = results['metadatas'][0]
            distances = results['distances'][0]
            valid_memories = []
            MAX_DISTANCE_THRESHOLD = 1.3
            for doc, meta, dist in zip(docs, metas, distances):
                if dist <= MAX_DISTANCE_THRESHOLD:
                    valid_memories.append((doc, meta))
            if not valid_memories: return ""
            valid_memories.sort(key=lambda x: x[1].get('timestamp', '2000-01-01'), reverse=True)
            if not is_enumeration:
                valid_memories = valid_memories[:1]
            recalled_list = [f"- [记录于 {meta.get('timestamp', '过去某时')}] {doc}" for doc, meta in valid_memories]
            recalled_text = "\n".join(recalled_list)
            # 向大模型提供“认知场”
            if is_enumeration:
                return f"[海马体涌现的深层记忆]\n{recalled_text}\n(系统提示：海马体已提取多条相关记录。请根据用户的语气判断：如果用户是在索要/回顾这些记录，请自然地列出或总结；如果用户只是陈述感叹，请仅作自然的情感附和，切勿生硬罗列。)"
            else:
                return f"[海马体涌现的最新记忆]\n{recalled_text}\n(系统提示：这是最近的一条相关记忆。请判断是否需要引用它来回答用户。)"
        except Exception as e:
            logger.error(f"海马体召回崩溃: {e}")
            return ""