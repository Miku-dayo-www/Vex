import ctypes
import io
import logging
import multiprocessing as mp
import time
import wave
from pathlib import Path
import numpy as np
import torch
from gsv_tts import TTS

logger = logging.getLogger(__name__)

def boost_process_priority():
    """强制解除 Windows EcoQoS，锁定高优先级"""
    try:
        # noinspection PyUnresolvedReferences
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        # noinspection PyUnresolvedReferences
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000080)
        # noinspection PyUnresolvedReferences
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
        logger.info("🚀 [物理提权] 已强行解除 Windows 后台降频限制，锁定 CPU/GPU 高优先级！")
    except Exception as e:
        logger.warning(f"⚠️ 物理提权失败: {e}")

class TTSWorker(mp.Process):
    def __init__(self, input_queue: mp.Queue, output_queue: mp.Queue, interrupt_event,
                 model_dir: str, ref_audio_path: str, prompt_text: str,device: str = "cuda"):
        super().__init__()
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.interrupt_event = interrupt_event
        self.model_dir = model_dir
        self.ref_audio_path = ref_audio_path
        self.prompt_text = prompt_text
        self.device = device
        self.daemon = True

    def run(self):
        import os
        os.environ["TQDM_DISABLE"] = "1"
        logging.getLogger("TTS").setLevel(logging.WARNING)
        logging.getLogger("gsv_tts").setLevel(logging.WARNING)
        boost_process_priority()

        model_base = Path(self.model_dir)
        if self.device == "cuda" and torch.cuda.is_available():
            torch.cuda.set_device(0)
        logger.info("🚀 [TTS Worker] 子进程启动，加载流式核心与 KV Cache...")
        try:
            # CUDA Graph KV 缓存分配
            batch_sizes = [1]
            cache_lens = [512, 1024]
            gpt_cache = [(b, c) for b in batch_sizes for c in cache_lens]
            engine = TTS(
                gpt_cache=gpt_cache,
                sovits_cache=[50],
                use_bert=True,
                use_flash_attn=False,
                dtype="float16",
                device=self.device,
            )
            gpt_path = str(model_base / "s1v3.ckpt")
            sovits_path = str(model_base / "s2Gv2ProPlus.pth")
            engine.load_gpt_model(gpt_path)
            engine.load_sovits_model(sovits_path)

            engine.cache_spk_audio(self.ref_audio_path)
            engine.cache_prompt_audio(
                prompt_audio_paths=self.ref_audio_path,
                prompt_audio_texts=self.prompt_text
            )

            # 预热流式图
            with torch.inference_mode():
                for _ in engine.infer_stream(
                        spk_audio_path=self.ref_audio_path, prompt_audio_path=self.ref_audio_path,
                        prompt_audio_text=self.prompt_text, text="预热", stream_mode="token",
                        stream_chunk=25, boost_first_chunk=True
                ): pass
            self.output_queue.put(("__SYS__", b"READY", None))
            logger.info("✅ [TTS Worker] 流式引擎已就绪，GPU 极速通道开启！")

        except Exception as e:
            logger.error(f"❌ [TTS Worker] 初始化崩溃: {e}", exc_info=True)
            self.output_queue.put(("__SYS__", b"ERROR", None))
            return

        while True:
            text_chunk = ""
            try:
                text_chunk = self.input_queue.get()
                if text_chunk is None:
                    break

                if self.interrupt_event.is_set():
                    self.output_queue.put(("DONE", text_chunk, None))
                    continue

                start = time.perf_counter()
                first_chunk = True
                with torch.inference_mode():
                    # 流式推理 infer_stream
                    stream_generator = engine.infer_stream(
                        spk_audio_path=self.ref_audio_path,
                        prompt_audio_path=self.ref_audio_path,
                        prompt_audio_text=self.prompt_text,
                        text=text_chunk,
                        is_cut_text=True,
                        stream_mode="token",
                        stream_chunk=40,  # 每次吐出约 1~2 秒的音频切片
                        overlap_len=5,  # 保证切片间平滑过渡
                        boost_first_chunk=True,  # 首块加速
                        top_k=15, top_p=1.0, temperature=1.0
                    )

                    for clip in stream_generator:
                        # 如果生成中途用户插话，直接 break 生成器，瞬间停下 GPU 运算
                        if self.interrupt_event.is_set():
                            logger.info("🗑️ [TTS Worker] 收到打断指令，瞬间掐断 GPU 算力引擎！")
                            break

                        audio_data = clip.audio_data
                        if hasattr(audio_data, 'cpu'):
                            audio_data = audio_data.cpu().numpy()
                        elif not isinstance(audio_data, np.ndarray):
                            audio_data = np.array(audio_data)

                        # Zero-Copy: float32 -> int16
                        audio_data = np.squeeze(audio_data)
                        if audio_data.dtype != np.int16:
                            audio_data = (audio_data * 32767.0).clip(-32768, 32767).astype(np.int16)

                        pcm_bytes = audio_data.tobytes()
                        wav_buf = io.BytesIO()
                        with wave.open(wav_buf, "wb") as vfout:
                            vfout.setnchannels(1)
                            vfout.setsampwidth(2)
                            vfout.setframerate(32000)
                            vfout.writeframes(pcm_bytes)
                        wav_bytes = wav_buf.getvalue()

                        if first_chunk:
                            first_time = (time.perf_counter() - start) * 1000
                            logger.info(f"⚡ [TTS 首块到达] '{text_chunk[:10]}...' TTFT: {first_time:.0f}ms")
                            first_chunk = False

                        # 边算边发，主进程同步播放
                        self.output_queue.put(("CHUNK", text_chunk, wav_bytes))

                # 句子彻底生成完毕
                self.output_queue.put(("DONE", text_chunk, None))

            except Exception as e:
                logger.error(f"❌ [TTS Worker] 推理异常: {e}", exc_info=True)
                self.output_queue.put(("DONE", text_chunk, None))