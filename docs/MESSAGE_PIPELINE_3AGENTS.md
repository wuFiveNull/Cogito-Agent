# AI Agent 消息处理链路对比分析

> 基于以下三个项目的源码分析：
> - **akashic-agent** — 事件驱动、插件化、多通道 AI Agent 框架
> - **hermes-agent** — 通用 Agent 运行时，支持多 provider、多工具集、多模态路由
> - **Cogito-Agent** — 六边形架构，SQLite 持久化，受控能力执行
>
> 本文聚焦：**用户输入的消息（含多模态消息）如何处理，完整链路是什么。**

---

## 目录

1. [核心链路纵览](#一核心链路纵览)
2. [akashic-agent：6 阶段插件化流水线](#二akashic-agent6-阶段插件化流水线)
3. [hermes-agent：3900 行大循环对话引擎](#三hermes-agent3900-行大循环对话引擎)
4. [Cogito-Agent：六边形架构的受控运行时](#四cogito-agent六边形架构的受控运行时)
5. [多模态消息处理对比](#五多模态消息处理对比)
6. [架构哲学与设计取舍](#六架构哲学与设计取舍)
7. [核心链路对比表](#七核心链路对比表)

---

## 一、核心链路纵览

三个项目的消息处理链路共享一个**宏观模式**，但实现方式截然不同：

```
用户输入
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│  接收层：从「外部通道」到「内部消息类型」                           │
│  akashic: Channel → InboundMessage → MessageBus (asyncio.Queue)  │
│  hermes:  CLI/ACP → str + conversation_history                   │
│  Cogito:  CLI/API → RuntimeEvent → ChatApplicationService         │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│  前置处理：会话准备 / 命令识别 / 记忆检索 / 系统提示组装 / 多模态处理 │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│  核心循环：LLM 推理 ↔ 工具执行（直到模型返回文本或达上限）          │
│  akashic: Reasoner.run() — BeforeStep/AfterStep 插件链           │
│  hermes:  while(api_call_count < max_iterations) — 7+ 错误回退   │
│  Cogito:  _generate_reply() → _dispatch_tools() 循环             │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────────────────────────────────────┐
│  后置处理：回复持久化 / 记忆同步 / 会话压缩 / 出站分发             │
└──────────────────────────────────────────────────────────────────┘
  │
  ▼
  输出回复
```

---

## 二、akashic-agent：6 阶段插件化流水线

### 2.1 架构概览

akashic-agent 是一个 **事件驱动、插件化的 AI Agent 框架**，核心设计理念是：

> **一切皆 Phase，插件在 Gate/Tap 介入**

### 2.2 消息定义

```python
# bus/events.py
@dataclass
class InboundMessage:
    channel: str       # 来源渠道（"cli"、"slack"）
    sender: str        # 发送者标识
    chat_id: str       # 会话 ID
    content: str       # 文本内容
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)    # 媒体文件路径列表
    metadata: dict[str, Any] = field(default_factory=dict)
```

`InboundItem = InboundMessage | SpawnCompletionItem` 支持区分普通用户消息和内部工作项。

### 2.3 完整链路

```
User 发送消息
  │
  ├─ 0. 消息接收
  │     Channel（Telegram / CLI / IPC）收到原始消息
  │     构建 InboundMessage(channel, chat_id, content, media, metadata)
  │     MessageBus.publish_inbound(msg) → asyncio.Queue
  │
  ├─ 1. AgentLoop 消费（agent/looping/core.py）
  │     AgentLoop.run() 阻塞等待 bus.consume_inbound()
  │     → asyncio.create_task(_process(msg))
  │     → 构建 TurnInterruptState
  │     → 发布 TurnStarted 事件到 EventBus
  │
  ├─ 2. CoreRunner 路由（agent/core/runner.py）
  │     InboundMessage → AgentCore.process()
  │     SpawnCompletionItem → 独立 handler
  │
  ├─ 3. PassiveTurnPipeline — 6 阶段处理（agent/core/passive_turn.py）
  │
  │    Phase 1: BeforeTurn（GATE）
  │    ├─ ContextStore.prepare():
  │    │   ├─ 读取 Session history
  │    │   ├─ 调用 RetrievalPipeline.retrieve() → 混合检索(BM25 + Dense)
  │    │   ├─ 收集技能提及（collect_skill_mentions）
  │    │   └─ 输出 ContextBundle（history, memory_blocks, skill_mentions）
  │    ├─ EventBus.emit(BeforeTurnCtx) → 插件可改写/abort
  │    └─ 检查 abort → 提前返回
  │
  │    Phase 2: BeforeReasoning（GATE）
  │    ├─ 同步工具上下文
  │    ├─ EventBus.emit(BeforeReasoningCtx) → 插件可改写
  │    └─ 检查 abort → 提前返回
  │
  │    Phase 3: Reasoner.run_turn（agent/core/passive_turn.py DefaultReasoner）
  │    │
  │    ├─ 准备 attempt plans（retry 策略：全量 → 裁剪 section → 缩小 history）
  │    │
  │    ├─ PromptRender（GATE）
  │    │   ├─ ContextBuilder.render() 组装系统 prompt
  │    │   │   ├─ 基础系统提示
  │    │   │   ├─ 上下文框架（长期记忆 / 自我认知 / 近期记忆 / 技能）
  │    │   │   ├─ 会话历史 + 记忆检索块
  │    │   │   ├─ 技能注入提示
  │    │   │   └─ 工具目录提示（deferred tools hint）
  │    │   └─ EventBus.emit(PromptRenderCtx)
  │    │       └─ 插件 Gate：可追加 system_sections_top/bottom
  │    │
  │    ├─ [LLM 推理循环 — Reasoner.run()]
  │    │   │
  │    │   ├─ BeforeStep（GATE）
  │    │   │   ├─ Token 估算 + EventBus.emit
  │    │   │   └─ 检查 early_stop → 生成不完整进展总结
  │    │   │
  │    │   ├─ LLM.chat() — 策略模式(DeepSeek/DashScope/Default)
  │    │   │
  │    │   ├─ 如果 LLM 返回 tool_calls：
  │    │   │   ├─ ToolExecutor.preflight（ToolHook 链：壳沙箱/Shell安全/循环检测）
  │    │   │   ├─ EventBus.fanout(BeforeToolCallCtx)
  │    │   │   ├─ ToolRegistry.execute(name, arguments)
  │    │   │   ├─ EventBus.fanout(AfterToolResultCtx)
  │    │   │   └─ 结果追加回 messages → 继续循环
  │    │   │
  │    │   └─ 如果 LLM 返回文本：
  │    │       └─ AfterStep（TAP）→ 退出循环
  │    │
  │    └─ 返回 TurnRunResult（reply, tools_used, tool_chain, thinking）
  │
  │    Phase 4: AfterReasoning（GATE）
  │    ├─ 解析回复 + 持久化到 Session
  │    ├─ 构建 OutboundMessage
  │    └─ EventBus.emit(AfterReasoningCtx) → 插件可改写回复
  │
  │    Phase 5: AfterTurn（TAP）
  │    └─ EventBus.fanout(AfterTurnCtx)
  │    └─ OutboundPort.dispatch() → MessageBus.publish_outbound(msg)
  │
  └─ 4. Channel 层收到 OutboundMessage，发送给用户
```

### 2.4 多模态消息处理

akashic-agent 通过 **`InboundMessage.media`** 传递媒体信息，在 ContextBuilder 中组装：

```
InboundMessage.media = ["/path/to/image.png"]
  │
  ├─ ContextBuilder.render() → ContextRequest(media=...)
  │
  ├─ MessageEnvelopeBuilder._build_user_content():
  │   ├─ 未启用多模态：
  │   │   └─ _build_text_with_media_refs() → 文本引用 + 提示调用 read_image_vision 工具
  │   ├─ 启用了多模态：
  │   │   ├─ 本地图片 → base64 编码 → image_url content block
  │   │   ├─ 远程图片 → 直接保留 URL → image_url content block
  │   │   └─ 输出格式：
  │   │       [{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
  │   │        {"type": "text", "text": "这是什么？"}]
  │   └─ 无媒体 → 原样返回文本
  │
  └─ LLM Provider 用 OpenAI 多模态格式发送
```

关键配置项：
- `config.multimodal` — 是否启用多模态嵌入
- `config.vl_available` — 是否配置了专门的视觉模型 provider

### 2.5 关键解耦机制

| 机制 | 说明 |
|------|------|
| **EventBus Gate/Tap** | 插件在每个 Phase 可介入、拦截、改写 |
| **Phase 拓扑排序** | 模块自动按依赖排列执行顺序 |
| **消息总线** | Channel 和 AgentLoop 只通过 `asyncio.Queue` 通信 |
| **ToolHook 链** | 工具执行前后可插入 pre/post hooks |

---

## 三、hermes-agent：3900 行大循环对话引擎

### 3.1 架构概览

hermes-agent 的核心理念是：

> **一个函数贯穿完整流程，代码即架构**

`run_conversation()` 函数（约 3900 行，位于 `agent/conversation_loop.py`）是核心入口，从消息接收到回复返回一站式完成。

### 3.2 消息定义

以**纯文本**为主要输入形式，辅以 `conversation_history` 列表：

```python
user_message: str                          # 用户文本消息
conversation_history: List[Dict[str, Any]] # 历史消息列表
```

### 3.3 完整链路

```
用户输入 "帮我看下这个图片"
  │
  ├─ 1. 调用层
  │     CLI / ACP Adapter / Gateway 发送
  │     → AIAgent.run_conversation(user_message, ...)
  │     → agent/conversation_loop.run_conversation()
  │
  ├─ 2. 前置处理（build_turn_context）
  │
  │   ├─ a. 会话准备
  │   │   ├─ session_id / task_id 初始化
  │   │   ├─ _ensure_db_session() 数据库会话
  │   │   └─ 加载 conversation_history
  │   │
  │   ├─ b. 记忆与上下文构建
  │   │   ├─ MemoryManager.prefetch_all(user_message)
  │   │   │   └─ 遍历所有 MemoryProvider → 获取相关记忆
  │   │   └─ build_memory_context_block()
  │   │       └─ 构建 <memory-context> 标记块
  │   │
  │   ├─ c. 系统提示组装
  │   │   ├─ _restore_or_build_system_prompt()
  │   │   │   ├─ AGENTS.md / SOUL.md / PROFILE.md 加载
  │   │   │   ├─ build_skills_system_prompt()
  │   │   │   ├─ build_context_files_prompt()
  │   │   │   └─ 缓存到 session DB（prefix-cache 优化）
  │   │   ├─ 注入记忆块
  │   │   └─ 注入工具定义 (get_tool_definitions)
  │   │
  │   ├─ d. 图像路由（agent/image_routing.py）
  │   │   ├─ decide_image_input_mode(user_message, agent)
  │   │   │   ├─ 检查 config.image_input_mode: auto / native / text
  │   │   │   ├─ auto 模式：
  │   │   │   │   ├─ 有 vision_analyze provider？→ text 模式
  │   │   │   │   ├─ 模型 supports_vision？→ native 模式
  │   │   │   │   └─ 否则 → text 模式
  │   │   │   └─ 返回决定
  │   │   │
  │   │   ├─ native 模式：
  │   │   │   ├─ extract_image_refs() → 提取本地/URL 图片引用
  │   │   │   ├─ encode_image() → base64 编码
  │   │   │   └─ 在 messages 中插入 image_url content part
  │   │   │
  │   │   └─ text 模式：
  │   │       └─ vision_analyze() 预分析 → 文本摘要 → 拼入用户消息
  │   │
  │   ├─ e. 消息净化（agent/message_sanitization.py）
  │   │   ├─ _sanitize_messages_surrogates() → 替换孤立代理字符
  │   │   ├─ _sanitize_messages_non_ascii() → 处理非 ASCII
  │   │   └─ _strip_images_from_messages() → 必要时剥离图片
  │   │
  │   └─ f. Prompt 缓存
  │       └─ apply_anthropic_cache_control() → Anthropic prompt caching
  │
  ├─ 3. 核心对话循环
  │
  │   ├─ 确定 API 路由：
  │   │   ├─ api_mode == "codex_app_server" → run_codex_app_server_turn()
  │   │   ├─ api_mode == "codex_responses" → run_codex_stream()
  │   │   └─ 默认 → OpenAI / Anthropic / Gemini / Bedrock
  │   │
  │   ├─ [LLM 调用循环]
  │   │   │
  │   │   ├─ a. 准备请求参数
  │   │   │   ├─ 合并 messages + system + tools
  │   │   │   ├─ 设置 max_tokens / temperature / reasoning_config
  │   │   │   ├─ 凭证池轮换 / 代理配置
  │   │   │   ├─ 消息序列修复（repair_message_sequence_with_cursor）
  │   │   │   └─ prepend steer → drain_pending_steer（/steer 命令注入）
  │   │   │
  │   │   ├─ b. 调用 LLM
  │   │   │   ├─ provider_adapter.chat() / stream()
  │   │   │   ├─ 流式回调 → stream_delta_callback / thinking_callback
  │   │   │   └─ 并发工具分派（_should_parallelize_tool_batch）
  │   │   │
  │   │   ├─ c. 如果返回 tool_calls：
  │   │   │   ├─ handle_function_call() → 分派到对应工具
  │   │   │   │   ├─ model_tools.get_toolset_for_tool() 找到工具集
  │   │   │   │   └─ tools/<toolset>/ 下执行
  │   │   │   ├─ ToolGuardrail 检查
  │   │   │   ├─ 大结果溢出 → tempfile 存储
  │   │   │   ├─ 工具结果分类（file_mutation_result_landed）
  │   │   │   └─ 结果追加回 messages
  │   │   │
  │   │   ├─ d. 错误处理 & 回退
  │   │   │   ├─ classify_api_error() → 错误分类（7+ 类别）
  │   │   │   ├─ 上下文超长 → ContextCompressor.truncate()
  │   │   │   ├─ 图像尺寸超限 → _image_error_max_dimension() → 缩放重试
  │   │   │   ├─ 计费/额度不足 → 回退模型或提示
  │   │   │   ├─ 内容策略拦截 → _content_policy_blocked_result()
  │   │   │   └─ 不可恢复错误 → 用户提示
  │   │   │
  │   │   └─ e. 限制检查
  │   │       ├─ max_iterations 达到 → 收尾总结
  │   │       ├─ iteration_budget 耗尽 → 停止
  │   │       └─ 空回复重试 → 注入提示重试一次
  │   │
  │   └─ [退出循环] → 得到 final_response
  │
  ├─ 4. 后置处理
  │
  │   ├─ a. MemoryManager.sync_all(user_msg, assistant_response)
  │   │   └─ 遍历所有 MemoryProvider → 异步同步记忆
  │   │
  │   ├─ b. MemoryManager.queue_prefetch_all()
  │   │   └─ 后台线程预加载下次可能需要的记忆
  │   │
  │   ├─ c. 背景审查（agent/background_review.py）
  │   │   └─ _run_background_review_if_needed()
  │   │       └─ 异步分析对话 → 技能建议 / 记忆提取
  │   │
  │   ├─ d. Session DB 持久化
  │   │   ├─ 保存 messages + token_usage
  │   │   └─ 更新 session 状态
  │   │
  │   └─ e. 收尾记录
  │       ├─ save_trajectory()
  │       └─ credits_tracker.log_turn()
  │
  └─ 5. 返回结果
      {final_response, tool_chain, usage, session_id, ...}
```

### 3.4 多模态消息处理 — 三种路由模式

hermes-agent 的图片路由是最丰富的，支持三种模式：

```yaml
image_input_mode: auto  # 可选: auto / native / text
```

**判断逻辑**（`agent/image_routing.py:decide_image_input_mode`）：

```
auto 模式：
  ├─ auxiliary.vision.provider 有自定义配置？→ text 模式
  │   （用户已选择了专门的视觉分析后端）
  ├─ 模型 metadata 报告 supports_vision=True？→ native 模式
  │   （模型自己能看懂图片）
  └─ 否则 → text 模式
      （用 vision_analyze 工具预分析，结果转文字）
```

**native 模式** — 原生图片传输：
```python
# agent/image_routing.py
local_paths, urls = extract_image_refs(user_message)
# 本地图片 → base64 编码
# URL 图片 → 保留 URL
msg["content"] = [
    {"type": "text", "text": "帮我看下这个图片"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
]
```

**text 模式** — 视觉预分析转文本：
```python
description = vision_analyze(image_path)
user_message = f"{user_message}\n[图片分析: {description}]"
```

### 3.5 Provider 多路径路由

```
run_conversation()
  ├─ api_mode == "codex_app_server"
  │   └─ agent/codex_runtime.py — Codex CLI subprocess
  ├─ api_mode == "codex_responses"
  │   └─ agent/codex_runtime.py — OpenAI Responses API
  └─ 默认路径
      ├─ OpenAI chat.completions（含 streaming）
      ├─ Anthropic adapter（agent/anthropic_adapter.py）
      ├─ Gemini adapter（agent/gemini_native_adapter.py）
      ├─ Bedrock adapter（agent/bedrock_adapter.py）
      └─ 自定义 provider（通过 credential_pool 轮换）
```

---

## 四、Cogito-Agent：六边形架构的受控运行时

### 4.1 架构概览

Cogito-Agent 是当前主项目，采用 **六边形架构（Ports/Adapters）**，核心设计理念：

> **关注点分离 + 受控能力执行 + 全链路可观测**

### 4.2 消息定义

使用结构化的 `RuntimeEvent` 作为统一入口：

```python
# shared/events.py
class RuntimeEvent(BaseModel):
    workspace_id: str
    session_id: str
    actor_id: str
    source: EventSource        # cli / api / autonomy / drift
    type: EventType            # user_message / tool_result / resume
    payload: dict[str, Any]    # {"text": "...", "content": [...]}
```

多模态内容使用 Pydantic 模型层次：

```python
# models/messages.py
ContentPart = TextPart | ImagePart | FilePart

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    uri: str = ""                     # data URI 或 http URL
    attachment_id: str | None = None  # 附件引用（上传后）
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    trust_level: str = "untrusted"

class FilePart(BaseModel):
    type: Literal["file"] = "file"
    uri: str
    mime_type: str
    filename: str
```

### 4.3 CLI 入口

```python
# cli/chat.py
# 1. 用户输入裸文本
user_input = input("You: ")

# 2. 构建 RuntimeEvent
event = RuntimeEvent(
    workspace_id=workspace_id,
    session_id=session_id,
    actor_id="user",
    source=EventSource.cli,
    type=EventType.user_message,
    payload={"text": user_input},  # 纯文本
)

# 3. 委托给 ApplicationService
result = ChatApplicationService(kernel).process(event)
```

### 4.4 API 入口（FastAPI）

```python
# api/app.py
# 1. 接收结构化请求（支持多模态）
class ChatRequest(BaseModel):
    session_id: str
    workspace_id: str
    text: str | None = None
    content: list[ContentItem] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)

    def get_content_parts(self) -> list[ContentPart]:
        """将 text + content + attachment_ids 归一化为 ContentPart[]"""
        ...

# 2. /chat 端点
@app.post("/chat")
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    content_parts = req.get_content_parts()
    payload = {
        "text": req.text or "",
        "content": [p.model_dump(exclude_none=True) for p in content_parts],
    }
    event = RuntimeEvent(..., payload=payload)
    result = chat_service.process(event)
    return ChatResponse(output=result.output, ...)

# 3. /chat/stream 端点（SSE 流式）
@app.post("/chat/stream")
def chat_stream(req: ChatStreamRequest, request: Request) -> StreamingResponse:
    ...
    return StreamingResponse(generate_sse_events(...), media_type="text/event-stream")
```

### 4.5 完整链路

```
用户输入消息（CLI 纯文本 / API 结构化含图片）
  │
  ├─ 0. 接收层
  │     CLI: input() → RuntimeEvent
  │     API: FastAPI → ChatRequest → RuntimeEvent
  │     Console: htmx POST → RuntimeEvent
  │
  ├─ 1. ApplicationService（application/）
  │     ChatApplicationService.process(event)
  │     → RuntimeKernel.process(event) 或 process_stream(event)
  │
  ├─ 2. RuntimeKernel（runtime/kernel.py）
  │
  │   ├─ _prepare_turn_setup()
  │   │   ├─ 创建 Trace + Span（全链路追踪）
  │   │   ├─ _check_budget_model() — 模型调用预算检查
  │   │   ├─ _check_model_policy() — 策略引擎检查
  │   │   └─ 初始化 TurnStateMachine
  │   │
  │   ├─ _run_pre_model_phase(event, trace)
  │   │   ├─ _persist_user_message() — 持久化用户消息
  │   │   ├─ _build_context()
  │   │   │   ├─ 从 SQLite 读取最近消息（最近 6 条）
  │   │   │   ├─ _check_memory_context_guard() — 记忆合并积压检查
  │   │   │   ├─ _load_context_memories()
  │   │   │   │   └─ MemoryRetrievalService.recall()
  │   │   │   │       ├─ MemoryQueryBuilder.build() (query + session summary)
  │   │   │   │       └─ 混合检索：resident + dynamic memories
  │   │   │   └─ ContextEngine.build()
  │   │   │       ├─ 系统提示
  │   │   │       ├─ session_summary
  │   │   │       ├─ memory_file (SELF.md, MEMORY.md, RECENT_CONTEXT.md)
  │   │   │       ├─ retrieved_memories (带分数排序)
  │   │   │       ├─ recent_messages
  │   │   │       └─ current_message
  │   │   ├─ _get_extra_content() — 提取图片/文件附件
  │   │   └─ _run_vision_pipeline() — 如需要，运行视觉分析管道
  │   │
  │   ├─ _build_model_messages()
  │   │   ├─ _resolve_attachment_content() → attachment_id → data URI
  │   │   ├─ _build_vision_context() → 获取附件描述上下文
  │   │   ├─ _supports_vision() 检查主模型是否支持原生视觉
  │   │   ├─ 不支持原生视觉 → _run_vision_pipeline() 预处理
  │   │   └─ PromptBuilder.build()
  │   │       ├─ 1. System policy / agent instruction
  │   │       ├─ 2. Skill instruction（可选）
  │   │       ├─ 3. Retrieved memories（标记来源）
  │   │       ├─ 4. Workspace file context
  │   │       ├─ 5. Conversation history
  │   │       ├─ 6. Tool results from current turn
  │   │       ├─ 7. Vision observations
  │   │       └─ 8. Current user message（含多模态 content）
  │   │
  │   ├─ _generate_reply()
  │   │   ├─ ModelAdapter.chat(messages, tools=tool_schemas)
  │   │   ├─ Retry with backoff（最多 2 次重试）
  │   │   ├─ Token 追踪 → Tracer.log_model_call()
  │   │   └─ 返回 ModelResponse(content, tool_intents, ...)
  │   │
  │   ├─ [工具循环] 最大 _max_tool_rounds 轮
  │   │
  │   │   ├─ _dispatch_tools()
  │   │   │   ├─ 遍历 resp.tool_intents
  │   │   │   ├─ _check_budget_tool() — 工具调用预算检查
  │   │   │   ├─ CapabilityExecutor.execute()
  │   │   │   │   ├─ PolicyEngine 策略评估
  │   │   │   │   ├─ Guardians（网络/路径/Shell/SecretEgress）
  │   │   │   │   ├─ 需要审批 → ApprovalRequiredError
  │   │   │   │   ├─ 被拒绝 → 收集 Denied 结果
  │   │   │   │   └─ 成功 → 收集 tool_result
  │   │   │   └─ 构建 follow_up_msgs → ModelAdapter.chat() 继续
  │   │   │
  │   │   └─ 达到上限 → _TOOL_CHAIN_TERMINATED
  │   │
  │   ├─ _run_after_turn()
  │   │   ├─ _persist() — 持久化 assistant 回复
  │   │   ├─ _update_session_summary() — 更新会话摘要
  │   │   └─ _consolidate() — 记忆合并
  │   │
  │   └─ _cleanup_turn()
  │       ├─ EndSpan / EndTrace
  │       └─ 发布 RuntimeEvent(EventType.turn_completed)
  │
  └─ 3. 输出返回
      CLI: print()
      API: ChatResponse / SSE StreamEvent
      Console: htmx 渲染
```

### 4.6 多模态消息处理 — 视觉管道

Cogito-Agent 的多模态处理是**分层的**：

```
用户发送含图片消息
  │
  ├─ 入口：API /chat 端点 → ChatRequest.get_content_parts()
  │   ├─ text → TextPart
  │   ├─ content[].type == "image" → ImagePart(uri, mime_type)
  │   ├─ content[].type == "file" → FilePart(uri, mime_type, filename)
  │   └─ attachment_ids → 从附件仓库加载 → ImagePart(data_uri)
  │
  ├─ 预处理：_build_model_messages()
  │   ├─ _resolve_attachment_content()
  │   │   └─ attachment_id → 从附件存储读取数据 → data URI
  │   ├─ _build_vision_context()
  │   │   └─ 收集已有视觉分析观察 → 拼入 prompt
  │   └─ _supports_vision() 检查
  │
  ├─ [分支 A] 主模型支持原生视觉
  │   └─ 直接传递 ImagePart(data_uri) 给模型
  │
  └─ [分支 B] 主模型不支持原生视觉
      └─ _run_vision_pipeline()
          ├─ [子分支 B1] VisionService 可用
          │   └─ 逐个检查图片 → inspect_image() → 文本结果
          ├─ [子分支 B2] 用专门视觉模型（route_role=vision_worker）
          │   ├─ _build_vision_messages() — 构建纯视觉 prompt
          │   ├─ ModelAdapter.chat() 在新路由中调用
          │   ├─ 解析 Structured JSON Observation
          │   └─ 记录到 tool_results
          └─ 返回 (text_parts, primary_text) → 替换 messages 中的图片
```

### 4.7 关键解耦机制

| 机制 | 说明 |
|------|------|
| **Ports/Adapters** | `RuntimePersistencePort`、`RuntimeTracePort` 等 Protocol 定义 SPI |
| **ApplicationService** | `ChatApplicationService` 封装 kernel 调用，通道无关 |
| **Governed Capability Executor** | 策略、Guardian、审批、审计、追踪全包裹 |
| **ContextEngine** | 带 Token 预算的上下文选择、排序、裁剪 |
| **TurnStateMachine** | 显式状态机管理 turn 生命周期 |

---

## 五、多模态消息处理对比

| 维度 | akashic-agent | hermes-agent | Cogito-Agent |
|------|---------------|-------------|-------------|
| **消息格式** | `InboundMessage.content + .media` | `str + conversation_history` | `RuntimeEvent.payload = {text, content[]}` |
| **多模态策略** | ContextBuilder 嵌入 image_url（配置驱动） | 三模式路由：auto/native/text | 分层视觉管道：原生 / 视觉模型 / VisionService |
| **图片来源** | media 路径列表 | `extract_image_refs()` 正则提取 | `ContentItem` + `attachment_ids` + 附件仓库 |
| **图片编码** | 本地 base64、URL 直传 | 本地 base64、URL 直传 | attachment_id → data URI |
| **模型检测** | `config.multimodal` 开关 + `config.vl_available` | `model_metadata.supports_vision` | `_supports_vision()` → Router 检查 |
| **视觉分析管道** | 无内置，提示调用 `read_image_vision` 工具 | `vision_analyze()` 预分析 → 文本摘要 | 完整视觉管道：VisionService + 视觉模型路由 |
| **回退机制** | 无专门处理 | `image_input_mode: auto` 自动降级 | 主模型不支持 → 视觉模型分析 → 文本替代 |
| **错误恢复** | N/A | 图片尺寸超限 → 缩放重试 | 无专门错误恢复 |
| **消息净化** | HTML-escaped + redacted | 代理字符 + 非 ASCII + 工具参数修复 | `wrap_untrusted()` → safety layer |
| **流式支持** | 通过 StreamDeltaReady 事件 | stream_callback / thinking_callback | SSE StreamEvent (delta/final/error) |
| **附件管理** | 无 | 无（直接读文件路径） | `/attachments` API 管理，dedup by hash |

---

## 六、架构哲学与设计取舍

### akashic-agent：插件化流水线

```
哲学：一切皆 Phase，插件在 Gate/Tap 介入
特点：
  - 5 个 Gate + 2 个 Tap，覆盖生命周期的每个缝隙
  - 插件在任意阶段可拦截、可改写、可增强
  - 通道和核心通过 asyncio.Queue 解耦
  - Phase 模块拓扑排序，自动处理依赖
代价：
  - 消息类型简单（InboundMessage），多模态偏弱
  - 管道长，跟踪复杂
  - 插件化架构导致调试困难
```

### hermes-agent：过程式大循环

```
哲学：一个函数贯穿完整流程，代码即架构
特点：
  - run_conversation() 从消息接收到回复一站式
  - 多 Provider 路由（6+ 种 API 后端）
  - 丰富的错误分类和回退策略（7+ 种错误类型）
  - 复杂的消息净化 + 流式补全
  - 图像路由最丰富（auto/native/text）
代价：
  - 单函数 3900 行，理解和维护成本高
  - 主要解耦发生在工具集层面
  - 生命周期 hook 不如 akashic 的形式化
  - 大量全局状态和 agent 属性访问
```

### Cogito-Agent：六边形受控运行时

```
哲学：关注点分离 + 受控能力执行 + 全链路可观测
特点：
  - Port/Adapter 接口清晰，测试友好
  - 全链路追踪（Trace + Span）
  - 三层防护：Policy → Guardian → Approval
  - 结构化多模态消息模型（Pydantic）
  - 附件管理系统（去重、校验、哈希匹配）
  - 显式 TurnStateMachine 管理生命周期
代价：
  - 架构层次多 (CLI/API → AppService → Kernel → Model)
  - 事件模型复杂（RuntimeEvent 传递所有信息）
  - 每层都有预算/策略检查，路径较长
  - 记忆系统在 kernel 外独立（retrieval service）
```

---

## 七、核心链路对比表

| 阶段 | akashic-agent | hermes-agent | Cogito-Agent |
|------|---------------|-------------|-------------|
| **接收** | Channel → MessageBus (Queue) | CLI/ACP → str | CLI/API → RuntimeEvent |
| **入口处理** | AgentLoop → CoreRunner | `run_conversation()` 直接处理 | `ChatApplicationService.process()` |
| **命令识别** | BeforeTurn → skill_mentions | /compact 等硬编码 | CLI 层 `/help` 等分支 + kernel 内建 |
| **会话准备** | ContextStore.prepare() | build_turn_context() | `_run_pre_model_phase()` |
| **系统提示** | ContextBuilder.render() 模块化 | `_restore_or_build_system_prompt()` 缓存 | `ContextEngine.build()` + `PromptBuilder.build()` |
| **记忆检索** | RetrievalPipeline (BM25+Dense) | MemoryManager.prefetch_all() | `MemoryRetrievalService.recall()` |
| **多模态处理** | media 嵌入 PromptRender | 三模式路由 (auto/native/text) | 分层视觉管道 (VisionService/视觉模型) |
| **LLM 调用** | LLMProvider (Strategy 模式) | ProviderAdapter (6+ 路由) | ModelAdapter + ModelRouter + Retry |
| **工具执行** | ToolRegistry + ToolExecutor | handle_function_call + toolsets | `GovernedCapabilityExecutor` (Policy+Guardian+Audit) |
| **工具钩子** | ToolHook (pre/post) | ToolGuardrails | PolicyDecision + Guardians + Approval |
| **错误处理** | attempt plans (section trimming) | classify_api_error 7+ 类别回退 | BudgetError / PolicyDeniedError / ApprovalRequiredError |
| **预算控制** | 隐式 max_iterations | IterationBudget + max_iterations | TurnBudget (model + tool + wall clock) |
| **记忆同步** | AfterReasoning → Session 持久化 | MemoryManager.sync_all() + background_review | `_consolidate()` → after_turn + LLM extraction |
| **出站** | MessageBus → Channel | final_response dict | TurnResult / SSE StreamEvent |
| **追踪** | EventBus + diagnostic_log | trajectory JSONL | Trace + Span + AuditLog |
| **扩展方式** | Plugin + PhaseModule + EventBus | toolsets + external provider | Port/Adapter + ApplicationService |

---

## 附录：关键代码位置

### akashic-agent

| 组件 | 文件 |
|------|------|
| 消息定义 | `bus/events.py` |
| AgentLoop 消费 | `agent/looping/core.py` |
| CoreRunner 路由 | `agent/core/runner.py` |
| PassiveTurnPipeline | `agent/core/passive_turn.py` |
| ContextStore | `agent/core/passive_turn.py` |
| Reasoner (DefaultReasoner) | `agent/core/passive_turn.py` |
| ContextBuilder | `agent/context.py` |
| MessageEnvelopeBuilder | `agent/context.py` |
| Lifecycle 模块 | `agent/lifecycle/phases/` |
| 工具注册/执行 | `agent/tools/registry.py`, `agent/tool_hooks/executor.py` |
| 记忆检索 | `agent/retrieval/` |

### hermes-agent

| 组件 | 文件 |
|------|------|
| AIAgent 主类 | `run_agent.py` |
| 对话循环 | `agent/conversation_loop.py` |
| Turn 上下文构建 | `agent/turn_context.py` |
| 系统提示组装 | `agent/conversation_loop.py: _restore_or_build_system_prompt()` |
| 图像路由 | `agent/image_routing.py` |
| 消息净化 | `agent/message_sanitization.py` |
| 记忆管理器 | `agent/memory_manager.py` |
| Prompt 缓存 | `agent/prompt_caching.py` |
| 错误分类器 | `agent/error_classifier.py` |
| 上下文压缩 | `agent/context_compressor.py` |
| 背景审查 | `agent/background_review.py` |
| Provider Adapters | `agent/anthropic_adapter.py`, `agent/gemini_native_adapter.py`, `agent/bedrock_adapter.py` |

### Cogito-Agent

| 组件 | 文件 |
|------|------|
| CLI 入口 | `cli/chat.py` |
| API 入口 | `api/app.py` |
| RuntimeKernel | `runtime/kernel.py` |
| Ports 定义 | `runtime/ports.py` |
| 消息模型 | `models/messages.py` |
| ContextEngine | `context/engine.py` |
| PromptBuilder | `context/prompt_builder.py` |
| 记忆检索 | `retrieval/service.py` |
| 能力执行器 | `execution/executor.py`（GovernedCapabilityExecutor） |
| 策略引擎 | `governance/policy.py` |
| 审计日志 | `governance/audit.py` |
| 持久化 | `storage/repositories.py` |
| 追踪 | `trace/tracer.py` |
| 应用服务 | `application/runtime_factory.py`（build_runtime_kernel） |
| 记忆合并 | `memory/consolidation.py` |

---

*文档版本 1.0 — 2026-06-22*
*基于 akashic-agent、hermes-agent、Cogito-Agent 源码分析*
