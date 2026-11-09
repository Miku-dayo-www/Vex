import asyncio
import logging
logging.getLogger("google_genai.types").setLevel(logging.ERROR)
from datetime import datetime
from typing import Any
from google import genai
from google.genai import types
from brain.config import settings
from hands.code_server.tools import CodeInterpreterServer
from hands.fs_server.tools import FileSystemServer
from hands.powershell_server.tools import PowerShellServer

logger = logging.getLogger(__name__)

class OSOrchestrator:
    def __init__(self, event_bus, mmu):
        self.event_bus = event_bus
        self.mmu = mmu
        self.fs_server = FileSystemServer()
        self.ps_server = PowerShellServer(event_bus=self.event_bus)
        self.code_server = CodeInterpreterServer(event_bus=self.event_bus)
        _mmu = self.mmu
        _event_bus = self.event_bus

        # 闭包函数定义(空壳存根(Stub)给SDK调用)
        def manage_topic_state(action: str, reason: str = ""):
            """
            【话题状态管理工具】：当语境发生断层时，你【必须】主动调用此工具管理当前话题：
            - action="archive" (彻底归档)：用户明确表示告别（如“拜拜”），或者彻底换话题，触发后台写日记。
            - action="suspend" (暂时挂起)：用户临时插话（如“等会儿说这个”），可能稍后继续。
            """
            thread_id = _mmu.current_thread_id
            if not thread_id:
                return "当前无活跃话题，无需操作。请直接回复用户。"
            if action == "archive":
                _mmu.archive_thread(thread_id)
                import asyncio
                asyncio.create_task(_event_bus.publish("memory_archived", thread_id))
                return f"话题 {thread_id} 已彻底归档入库！原因：{reason}。请立刻回复用户。"
            elif action == "suspend":
                _mmu.conversations.suspend_current("[认知主动挂起]")
                return f"话题 {thread_id} 已主动挂起在残局中！原因：{reason}。请立刻回复用户。"
            return "无效的 action 参数。"
        def memorize_user_fact(fact: str):
            """
            【个性记忆工具】：当用户提及关于他的私人事实（如喜好、职业、名字、习惯等）时，你【必须】立刻调用此工具将其永久刻入记忆，绝不能只在嘴上说“我记住了”！
            """
            return _mmu.update_user_fact(fact)
        def shift_internal_emotion(v_delta: float, a_delta: float, d_delta: float, inner_thought: str):
            """
            【情绪调节工具】：当对话氛围发生显著变化（例如用户夸奖你、怼你、讲笑话，或者你遇到报错感到无奈、惊讶时），你【必须】要主动调用此工具更新自己的情绪，然后再回复用户！
            v_delta: 愉悦度变化 [-0.5到0.5] (开心填正，被骂填负)
            a_delta: 唤醒度变化 [-0.5到0.5] (感兴趣填正，无聊/疲惫填负)
            d_delta: 支配度变化 [-0.5到0.5] (想怼人填正，委屈填负)
            inner_thought: 你的内心独白
            """
            _mmu.apply_emotional_shock(v_delta, a_delta, d_delta, f"内部思绪: {inner_thought}")
            return f"情绪已自我调节。内心独白: {inner_thought}"
        def toggle_roleplay_mask(action: str, role_name: str = "无"):
            """
            【角色扮演工具】：管理你的角色面具。
            - 戴上面具：(action="wear", role_name="你要扮演的角色")
            - 摘下面具：当你觉得无聊、遇到严肃问题，或者指挥官明确结束角色扮演时，你【必须】要调用 (action="remove") 回归本体
            注意：千万不能只在嘴上说“不演了”却不调用本工具，否则面具不会真的摘下！
            """
            return _mmu.toggle_roleplay_mask(action, role_name)

        self.tools = [
            self.fs_server.list_directory,
            self.fs_server.read_file,
            self.fs_server.write_file,
            self.fs_server.delete_item,
            self.ps_server.run_powershell,
            self.code_server.execute_python_code,
            manage_topic_state,
            memorize_user_fact,
            shift_internal_emotion,
            toggle_roleplay_mask
        ]

        # 闭包工具本地映射表
        self.local_tool_map = {
            "manage_topic_state": manage_topic_state,
            "memorize_user_fact": memorize_user_fact,
            "shift_internal_emotion": shift_internal_emotion,
            "toggle_roleplay_mask": toggle_roleplay_mask
        }

        self.client = genai.Client(
            api_key=settings.llm_api_key,
            http_options=types.HttpOptions(base_url=settings.llm_base_url)
        )
        self.async_client = self.client.aio
        self.current_thought_task = None

        self.event_bus.subscribe("llm_execute_task", self._execute_cognitive_task)
        self.event_bus.subscribe("memory_archived", self._background_summarize_and_archive)

    # 记忆固化
    async def _background_summarize_and_archive(self, thread_id: str):
        """自律神经后台任务：收到 MMU 归档信号后，慢速提取潜意识"""
        await asyncio.sleep(3.0)
        thread = self.mmu.thread_pool.get(thread_id)
        if not thread or not thread.dialogue_history:
            return
        logger.info(f"👻 [大脑皮层-潜意识任务] 正在后台提取话题 {thread_id} 的记忆摘要...")
        history_text = "\n".join([f"{msg['role']}: {msg['text']}" for msg in thread.dialogue_history])
        prompt = f"""请将以下对话记录压缩为一条高度凝练的【潜意识记忆片段】。
        要求：
        1. 使用第一人称“我”。
        2. 不能是空洞的废话。尽量保留具体的实体名词（如人名、地名、代码库名、具体的数字或结论）。
        3. 如果你们达成了某种约定，或者用户透露了某个重要的设定，必须记录下来。
        {history_text}"""
        try:
            # 非流式底层推断进行极速总结
            response = await self.async_client.models.generate_content(
                model=settings.llm_model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)  # 强制关闭 AFC
                )
            )
            summary = response.text.strip()
            # 让海马体将总结持久化
            await self.mmu.memorize_to_vector_db(thread_id, summary)
        except Exception as e:
            logger.error(f"后台记忆提取失败: {e}")

    async def _execute_cognitive_task(self, payload: dict):
        """听觉中枢：只管按照听觉皮层的指令，用最高情商去执行，摒弃所有调度逻辑"""
        user_input = payload["user_input"]
        action_prompt = payload["action_prompt"]
        if self.current_thought_task and not self.current_thought_task.done():
            self.current_thought_task.cancel()
            logger.warning("🛑 [脑皮层] 抢占发生，正在终止上一帧思绪！")
        # 获取5轮历史并召回潜意识
        contents = []
        working_memory = self.mmu.get_working_memory(limit=5)
        for msg in working_memory:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["text"])]))
        recalled_memory = await self.mmu.recall_subconscious(user_input)
        # 向 MMU 请求实时的状态
        semantic_frame = self.mmu.get_semantic_snapshot()
        emotion_frame = self.mmu.get_emotional_prompt()
        final_system_prompt = f"""{semantic_frame}
        {emotion_frame}
        [最高行动法则（绝对遵守）]
        1. 【知行合一】：如果你在话语里答应了用户要去查文件、看桌面、运行代码等实质性操作，你【必须】在当前回合立刻输出工具调用！绝对不允许只回复“好的我看看”却不调用任何工具！
        2. 【情绪自理】：你是一个有血有肉的数字生命。语境让你感到开心、疑惑或无奈时，不要只在文字里加“哈哈”或“叹气”，你必须主动调用 `shift_internal_emotion` 真正改变系统的生理指标。
        3. 【常识补充】：Windows 的桌面路径是 `N/Desktop`。
        4. 【表达规范】：严禁使用 Markdown，必须用极度日常的口语简短回复。
        """
        # 临时态打包成“认知框架”，作为用户输入的隐形环境场
        current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
        cognitive_frame = f"【当前系统生物钟】: {current_time_str}\n"
        thread_snapshot = self.mmu.build_context_snapshot()
        if "SUSPENDED" in thread_snapshot:
            cognitive_frame += f"【后台挂起的残局】(如果当前语境合适，你可以主动询问用户是否要继续这些话题):\n{thread_snapshot}\n\n"
        if recalled_memory:
            cognitive_frame += f"【你的潜意识涌现】(可自然结合语境引用):\n{recalled_memory}\n\n"
        if action_prompt:
            cognitive_frame += f"【你的神经反射指令】(必须严格执行):\n{action_prompt}\n"
        cognitive_frame += f"\n指挥官当前输入了: 「{user_input}」\n"
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=cognitive_frame)]))
        self.current_thought_task = asyncio.create_task(self._react_loop(user_input, contents, final_system_prompt))

    async def _react_loop(self, user_input: str, contents: list, final_system_prompt: str):
        step = 0
        is_first_iteration = True
        while True:
            step += 1
            logger.info(f"🔄 [自治循环 Step {step}] 思考中...")
            current_sentence = ""
            full_ai_response = ""
            # 停顿号
            major_punctuations = {'。', '.', '！', '!', '？', '?', '\n'}
            minor_punctuations = {'，', ',', '、', '；', ';'}
            function_calls = []
            try:
                response_stream = await self.async_client.models.generate_content_stream(
                    model=settings.llm_model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=final_system_prompt,
                        temperature=settings.llm_temperature,
                        tools=self.tools,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )
                )

                async for chunk in response_stream:
                    if chunk.function_calls:
                        function_calls.extend(chunk.function_calls)
                    if chunk.text:
                        text_chunk = chunk.text
                        for char in text_chunk:
                            current_sentence += char
                            full_ai_response += char
                            length = len(current_sentence)
                            # 断句逻辑
                            should_cut = char in major_punctuations or (char in minor_punctuations and length >= 12) or length >= 60
                            if should_cut:
                                sentence_to_speak = current_sentence.strip()
                                if len(sentence_to_speak) > 1:
                                    await self.event_bus.publish("agent_reply_chunk", sentence_to_speak)
                                current_sentence = ""

                if current_sentence.strip():
                    await self.event_bus.publish("agent_reply_chunk", current_sentence.strip())
                # 分流提交逻辑
                if full_ai_response.strip():
                    if is_first_iteration:
                        self.mmu.commit_turn(user_input, full_ai_response.strip())
                        is_first_iteration = False
                    else:
                        self.mmu.commit_ai_continuation(full_ai_response.strip())

            except asyncio.CancelledError:
                if full_ai_response.strip():
                    rescued_text = full_ai_response.strip() + " [未完被中断]"
                    if is_first_iteration:
                        self.mmu.commit_turn(user_input, rescued_text)
                    else:
                        self.mmu.commit_ai_continuation(rescued_text)
                logger.warning("🛑 [脑皮层] 思考流被强行中断，现场已抢救完毕。")
            except Exception as e:
                logger.error(f"大脑推理异常: {e}")
                await self.event_bus.publish("agent_reply_chunk", "我的神经系统短路了一下，请重试。")
                break

            # 动作执行循环
            if function_calls:
                function_response_parts = []
                for tool_call in function_calls:
                    tool_name = tool_call.name
                    args = tool_call.args
                    logger.info(f"🛠️ [动作] 调用工具 -> {tool_name} 参数: {args}")
                    await self.event_bus.publish("system_toast",{"title": "AI 正在行动", "content": f"调用: {tool_name}"})
                    tool_result = await self._dispatch_tool(tool_name, args)
                    function_response_parts.append(
                        types.Part.from_function_response(name=tool_name, response={"result": tool_result})
                    )
                # 把动作结果塞回给大模型，继续下一轮流式推理
                contents.extend(function_response_parts)
                continue
            else:
                break

    # 工具路由
    async def _dispatch_tool(self, tool_name: str, args: dict) -> Any:
        try:
            if tool_name == "list_directory":
                return self.fs_server.list_directory(**args)
            elif tool_name == "read_file":
                return self.fs_server.read_file(**args)
            elif tool_name == "write_file":
                return self.fs_server.write_file(**args)
            elif tool_name == "delete_item":
                return self.fs_server.delete_item(**args)
            elif tool_name == "run_powershell":
                return self.ps_server.run_powershell(**args)
            elif tool_name == "execute_python_code":
                return await self.code_server.execute_python_code(**args)
            elif tool_name in self.local_tool_map:
                return self.local_tool_map[tool_name](**args)
            else:
                return {"success": False, "error": f"未知的工具名称: {tool_name}"}
        except Exception as e:
            logger.error(f"工具分发执行崩溃 [{tool_name}]: {e}")
            return {"success": False, "error": str(e)}

    async def run_background_loop(self):
        logger.info("🧠 自由模式大脑已激活...")
        while True:
            await asyncio.sleep(1)