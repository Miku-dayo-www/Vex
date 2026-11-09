import asyncio
import logging
import queue
import threading
from pathlib import Path
import sherpa_onnx
import sounddevice as sd
import torch
from silero_vad import load_silero_vad
from ears.vocabulary_list import SAFE_BACKCHANNELS, INTENT_CORPUS
from nervous_system.event_bus import QoS

logger = logging.getLogger(__name__)

class EarsEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.is_running = True

        # 耳朵核心参数
        self.sample_rate = 16000
        self.block_size = 512
        self.vad_threshold = 0.6 # vad判定阈值
        self.silence_patience = 18 # 最长忍受静音帧数(18 × 32ms = 576ms)
        self.audio_queue = queue.Queue(maxsize=100)
        self.is_speaking = False
        self.silence_counter = 0
        self.has_interrupted_current_turn = False

        # 加载听觉模型
        logger.info("👂 [听觉中枢] 正在加载 Silero VAD (纯本地)...")
        self.vad_model = load_silero_vad(onnx=True)
        logger.info("👂 [听觉中枢] 正在加载 Sherpa-ONNX 流式识别引擎...")
        model_dir = Path(__file__).parent.parent / "models" / "sherpa-onnx-streaming"
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder-epoch-99-avg-1.int8.onnx"),
            decoder=str(model_dir / "decoder-epoch-99-avg-1.int8.onnx"),
            joiner=str(model_dir / "joiner-epoch-99-avg-1.int8.onnx"),
            num_threads=1,
            sample_rate=self.sample_rate,
            feature_dim=80,
            decoding_method="greedy_search"
        )
        self.stream = self.recognizer.create_stream()

    def _audio_callback(self, indata, frames, time, status):
        """底层回调，数据采集入队"""
        if status:
            pass
        audio_data = indata[:, 0].copy()
        try:
            self.audio_queue.put_nowait(audio_data)
        except queue.Full:
            pass

    def _assess_barge_in_type(self, text: str) -> str:
        """听觉过滤：极速物理评估，剔除子串误判"""
        clean_text = text.replace(" ", "").strip()
        if not clean_text:
            return "NONE"
        pure_text = clean_text.strip(" 。，！？.,!?~…·\"'“”‘’\r\n\t-")
        if not pure_text:
            return "NONE"
        if len(pure_text) <= 2 and all(char in SAFE_BACKCHANNELS for char in pure_text):
            return "NONE"
        if pure_text in INTENT_CORPUS["HESITATION"]:
            return "SOFT"
        if pure_text in INTENT_CORPUS["REJECT"]:
            return "HARD"
        if len(pure_text) >= 3:
            return "HARD"
        return "NONE"

    def _processing_loop(self, loop):
        """推理与状态机，跨线程投递"""
        logger.info("✅ [听觉中枢] 纯离线全双工监听已启动！")
        while self.is_running:
            try:
                audio_chunk = self.audio_queue.get(timeout=1)
                if audio_chunk is None:
                    logger.info("🛑 [听觉中枢] 收到停机中断信号，退出处理循环。")
                    break
            except queue.Empty:
                continue

            try:
                chunk_tensor = torch.from_numpy(audio_chunk).float()
                vad_prob = self.vad_model(chunk_tensor, self.sample_rate).item()
                # 触发或打断状态机
                if vad_prob > self.vad_threshold:
                    # 有声帧重置静音计时器
                    self.silence_counter = 0
                    if not self.is_speaking:
                        self.is_speaking = True
                        self.has_interrupted_current_turn = False
                        logger.info("🎙️ 检测到语音起始 (触发 Barge-in)")
                else:
                    if self.is_speaking:
                        self.silence_counter += 1

                # --- 听觉神经(Sherpa ASR 流式识别) ---
                # Partial 用于即时反馈
                if self.is_speaking:
                    self.stream.accept_waveform(self.sample_rate, audio_chunk)
                    while self.recognizer.is_ready(self.stream):
                        self.recognizer.decode_stream(self.stream)
                    partial_text = self.recognizer.get_result(self.stream)
                    if partial_text:
                        if not self.has_interrupted_current_turn:
                            barge_in_type = self._assess_barge_in_type(partial_text)
                            if barge_in_type != "NONE":
                                logger.info(f"🛑 [语义中断触发] 探测到内容: '{partial_text}', 烈度: {barge_in_type}")
                                self.has_interrupted_current_turn = True
                                # 通过 QoS.REFLEX 极高优通道，向总线发射不同的脊髓反射指令
                                event_name = "interrupt_tts_hard" if barge_in_type == "HARD" else "interrupt_tts_soft"
                                asyncio.run_coroutine_threadsafe(
                                    self.event_bus.publish(event_name, {}, qos=QoS.REFLEX), loop
                                )
                        # partial 发送给总线，用于未来做 UI 悬浮窗显示等
                        asyncio.run_coroutine_threadsafe(
                            self.event_bus.publish("voice_partial", partial_text), loop
                        )
                # Final 用于逻辑决策
                if self.is_speaking and self.silence_counter > self.silence_patience:
                    self.is_speaking = False
                    self.stream.input_finished()  # 进行尾音处理
                    while self.recognizer.is_ready(self.stream):
                        self.recognizer.decode_stream(self.stream)
                    final_text = self.recognizer.get_result(self.stream)
                    if final_text.strip():
                        logger.info(f"🗣️ 识别结果: {final_text}")
                        asyncio.run_coroutine_threadsafe(
                            self.event_bus.publish("user_instruction", final_text), loop
                        )
                    self.stream = self.recognizer.create_stream()

            except Exception as e:
                logger.exception(f"🔥 处理音频帧时发生严重异常，已跳过该帧: {e}")

    def run_in_background(self):
        loop = asyncio.get_running_loop()
        processor_thread = threading.Thread(target=self._processing_loop, args=(loop,), daemon=True)
        processor_thread.start()
        # 配置声卡输入流
        self.sd_stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            device=None, channels=1, dtype='float32',
            callback=self._audio_callback
        )
        self.sd_stream.start()

    def stop(self):
        self.is_running = False
        if hasattr(self, 'sd_stream'):
            self.sd_stream.stop()
            self.sd_stream.close()