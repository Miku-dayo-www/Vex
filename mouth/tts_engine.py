import asyncio
import io
import logging
import multiprocessing as mp
import queue
import random
import threading
import time
from pathlib import Path
import pygame
from mouth.tts_worker import TTSWorker

logger = logging.getLogger(__name__)

class MouthEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.text_queue = asyncio.Queue()
        self.audio_queue = queue.Queue()
        self.is_running = True
        self.is_playing = False

        # 神经探针：用于精准追踪文本在流水线中的物理位置
        self.current_downloading_text = ""
        self.current_playing_text = ""
        self.loop = asyncio.get_running_loop()

        # 软刹车残余缓存：寄存被截断的后续话语
        self.pending_unspoken_report = ""

        # 初始化物理混音器
        pygame.mixer.init(frequency=32000, size=-16, channels=1)
        pygame.mixer.set_num_channels(4)
        self.has_played_filler_this_turn = False

        # 潜意识语气词系统
        self.last_filler_time = 0
        self.filler_sounds = []
        filler_dir = Path(__file__).parent / "fillers"
        if filler_dir.exists():
            for file in filler_dir.iterdir():
                if file.suffix == ".wav":
                    self.filler_sounds.append(pygame.mixer.Sound(str(file)))
            logger.info(f"👄 [潜意识] 已预加载 {len(self.filler_sounds)} 个语气词。")
        else:
            logger.warning("👄 [潜意识] 未找到 fillers 目录，语气词系统休眠。")

        self.ref_audio_path = str(Path(__file__).parent / "ref_voice.wav")
        self.prompt_text = "约德尔人，管好你自己，我跟你没什么可聊的"
        self.tts_input_queue = mp.Queue()
        self.tts_output_queue = mp.Queue()
        self.tts_interrupt_event = mp.Event()

        # 启动子进程
        logger.info("🔥 [发声器官] 正在启动独立 TTS Worker 子进程...")
        project_root = Path(__file__).parent.parent
        self.tts_worker = TTSWorker(
            input_queue=self.tts_input_queue,
            output_queue=self.tts_output_queue,
            interrupt_event=self.tts_interrupt_event,
            model_dir=str(project_root / "models" / "gsv-tts-weights"),
            ref_audio_path=self.ref_audio_path,
            prompt_text=self.prompt_text,
            device="cuda"
        )
        self.tts_worker.start()
        logger.info("⏳ [发声器官] 正在等待 GPU 显存分配与 CUDA 图深度预热 (可能需要较长时间)...")
        while True:
            try:
                msg_type, payload, _ = self.tts_output_queue.get(timeout=20)
                if msg_type == "__SYS__" and payload == b"READY":
                    logger.info("✅ [发声器官] 预热完毕！物理发声链路已贯通。")
                    break
                elif msg_type == "__SYS__" and payload == b"ERROR":
                    logger.error("❌ [发声器官] 子进程初始化彻底失败，请检查环境！")
                    break
            except queue.Empty:
                logger.info("⏳ [发声器官] TTS Worker 正在锁定计算图，请继续耐心等待...")
            except Exception as e:
                logger.error(f"预热监听异常: {e}")

        self.event_bus.subscribe("agent_reply_chunk", self._handle_tts_chunk)
        self.event_bus.subscribe("play_filler", self._play_filler)
        self.event_bus.subscribe("interrupt_tts_hard", self._handle_hard_interrupt)
        self.event_bus.subscribe("interrupt_tts_soft", self._handle_soft_interrupt)

        asyncio.create_task(self._inference_worker())
        threading.Thread(target=self._player_worker, daemon=True).start()

    def stop(self):
        self.is_running = False
        self.tts_input_queue.put(None)
        self.tts_worker.join(timeout=3.0)
        pygame.mixer.quit()

    async def _handle_tts_chunk(self, text: str):
        """前端接收器：将整句文本推入下载队列"""
        clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()
        if clean_text:
            await self.text_queue.put(clean_text)

    async def _inference_worker(self):
        """流式管道接收器"""
        while self.is_running:
            try:
                text_chunk = await self.text_queue.get()
                self.current_downloading_text = text_chunk
                self.tts_interrupt_event.clear()
                logger.info(f"⚡ [投递流式任务] --> {text_chunk}")
                self.tts_input_queue.put(text_chunk)
                # 持续监听流式 Chunk
                while True:
                    result = await asyncio.to_thread(self.tts_output_queue.get)
                    if not result: continue
                    msg_type, res_text, wav_bytes = result
                    if self.tts_interrupt_event.is_set():
                        if msg_type == "DONE": break
                        continue
                    if res_text != text_chunk: continue
                    if msg_type == "DONE":
                        break
                    elif msg_type == "CHUNK" and wav_bytes:
                        audio_io = io.BytesIO(wav_bytes)
                        sound_obj = pygame.mixer.Sound(audio_io)
                        self.audio_queue.put((text_chunk, sound_obj))

            except asyncio.CancelledError:
                continue
            except Exception as e:
                logger.error(f"❌ 流水线异常: {e}", exc_info=True)
            finally:
                self.current_downloading_text = ""

    async def _handle_hard_interrupt(self, _):
        await self._execute_interrupt(hard=True)

    async def _handle_soft_interrupt(self, _):
        await self._execute_interrupt(hard=False)

    async def _execute_interrupt(self, hard: bool):
        """物理反射双轨制：硬打断瞬间闭嘴，软打断优雅收尾"""
        logger.info(f"🛑 [发声器官] 触发{'硬' if hard else '软'}刹车！")
        self.tts_interrupt_event.set()
        unspoken_parts = []
        if self.current_downloading_text:
            unspoken_parts.append(self.current_downloading_text)
            self.current_downloading_text = ""
        # 清空等待下载的文本
        while not self.text_queue.empty():
            try:
                unspoken_parts.append(self.text_queue.get_nowait())
            except:
                break
        # 清空等待播放的音频块
        while not self.audio_queue.empty():
            try:
                chunk, _ = self.audio_queue.get_nowait()
                if not unspoken_parts or unspoken_parts[-1] != chunk:
                    unspoken_parts.append(chunk)
            except:
                break
        # 抽空跨进程管道里的残留
        while not self.tts_input_queue.empty():
            try:
                self.tts_input_queue.get_nowait()
            except:
                break
        while not self.tts_output_queue.empty():
            try:
                self.tts_output_queue.get_nowait()
            except:
                break

        if hard:
            # 【硬刹车】：强行勒令声卡停止。正在说的这半句没说完，计入残余现场。
            if self.current_playing_text:
                unspoken_parts.insert(0, self.current_playing_text)
            pygame.mixer.stop()
            self.is_playing = False
            self.current_playing_text = ""
            unspoken_text = "".join(unspoken_parts)
            if unspoken_text:
                # 硬打断立刻向海马体汇报
                await self.event_bus.publish("tts_interrupted_report", {"unspoken_text": unspoken_text})
        else:
            # 【软刹车】：绝不调用 pygame.mixer.stop()
            unspoken_text = "".join(unspoken_parts)
            if unspoken_text:
                self.pending_unspoken_report = unspoken_text

    def _player_worker(self):
        """【消费者】流式音频排队播放器：利用 Pygame 单声道队列实现无缝拼接"""
        channel = pygame.mixer.Channel(0)
        while self.is_running:
            try:
                text_chunk, sound_obj = self.audio_queue.get(timeout=0.1)
                pygame.mixer.Channel(3).fadeout(200) # 语气词淡出
                self.current_playing_text = text_chunk
                self.is_playing = True
                if not channel.get_busy():
                    channel.play(sound_obj)
                else:
                    channel.queue(sound_obj)
                    while channel.get_queue() is not None and self.is_playing:
                        time.sleep(0.005)
                self.audio_queue.task_done()

            except queue.Empty:
                if self.is_playing and not channel.get_busy():
                    self.is_playing = False
                    self.current_playing_text = ""
                    if self.pending_unspoken_report:
                        logger.info("🍂 [优雅刹车] 上传残余现场...")
                        asyncio.run_coroutine_threadsafe(
                            self.event_bus.publish("tts_interrupted_report",{"unspoken_text": self.pending_unspoken_report}),
                            self.loop
                        )
                        self.pending_unspoken_report = ""
                continue
            except Exception as e:
                logger.error(f"播放器崩溃: {e}")
                self.is_playing = False

    async def _play_filler(self, payload: dict):
        """【高级拟人化魔法】智能判断是否播放语气词"""
        if payload.get("is_first_step", False):
            self.has_played_filler_this_turn = False
        if self.is_playing or not self.filler_sounds or self.has_played_filler_this_turn:
            return
        current_time = time.time()
        # 冷却机制与随机概率
        if current_time - self.last_filler_time < 8.0:
            return
        if random.random() > 0.4:
            return
        try:
            sound = random.choice(self.filler_sounds)
            channel = pygame.mixer.Channel(3)
            if not channel.get_busy():
                channel.play(sound)
                self.last_filler_time = current_time
                self.has_played_filler_this_turn = True
                logger.info("👄 [潜意识] 嗯...")
        except Exception as e:
            logger.error(f"潜意识异常: {e}")