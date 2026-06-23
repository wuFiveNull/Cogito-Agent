# 三项目架构对比分析：Cogito-Agent、Akashic-Agent、Hermes-Agent

> 本文档从层级结构、组织架构、组件组装方式与低耦合设计四个维度，深入分析三个 Agent 系统的架构设计，揭示其共性规律与各自特色。

---

## 目录

1. [总体架构定位](#1-总体架构定位)
2. [层级结构与分层原则](#2-层级结构与分层原则)
3. [组件组装与依赖注入](#3-组件组装与依赖注入)
4. [端口适配器（Hexagonal）模式应用](#4-端口适配器hexagonal模式应用)
5. [插件系统与生命周期钩子](#5-插件系统与生命周期钩子)
6. [工具/能力注册与治理](#6-工具能力注册与治理)
7. [主循环与状态推进](#7-主循环与状态推进)
8. [配置加载与环境适配](#8-配置加载与环境适配)
9. [消息处理流水线](#9-消息处理流水线)
10. [对比总结矩阵](#10-对比总结矩阵)

---

## 1. 总体架构定位

### Cogito-Agent

面向个人长期使用的 **Agent Runtime**，定位为「个人智能操作层」。强调**本地优先、多渠道入口、长期记忆、技能扩展、安全治理、链路追踪**。以**分层运行时（Runtime Kernel + 六个 Plane）** 为架构核心，是典型的企业级/个人助理级架构。

### Akashic-Agent

面向**多渠道接入的对话 Agent**，核心是**主循环 + 插件系统 + 生命周期钩子（Lifecycle Hooks）** 的架构。重视**渠道适配（Telegram/QQ/CLI）和被动消息处理**，以及**基于 EventBus 的事件驱动插件机制**。

### Hermes-Agent

面向**重度代码开发与工具使用**的 **AIAgent**（Claude Code 风格），核心是**单 Agent 实例的庞大状态机**。系统围绕一个 `AIAgent` 类的属性初始化展开，通过大量的**回调注入、可插拔 Provider、可替换 ContextEngine** 实现扩展性。

---

## 2. 层级结构与分层原则

### 2.1 Cogito-Agent 的分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户入口层                              │
│           CLI / Web Console / API / MCP                      │
├─────────────────────────────────────────────────────────┤
│                    应用服务层 (Application Services)        │
│     Chat / Session / Workspace / Memory / MCP              │
├─────────────────────────────────────────────────────────┤
│                    Runtime Kernel                           │
│     TurnStateMachine / Budget / Interrupt / Retry           │
├──────────┬────────────────┬──────────┬───────────────┤
│ Context  │ Capability     │Autonomy  │ Governance    │
│ Plane    │ Plane          │ Plane    │ Plane         │
│ Engine   │ Tool/MCP/Skill │ Drift    │ Policy/Audit  │
│ Retrieval│ Subagent       │Scheduler │ Approval      │
├──────────┴────────────────┴──────────┴───────────────┤
│                    Trace Plane                          │
│         Trace Tree / Span / Lineage / Replay            │
├─────────────────────────────────────────────────────────┤
│                    Storage Plane                         │
│     SQLite / Memory Store / FTS5 / Workspace Files        │
└─────────────────────────────────────────────────────────┘
```

**分层原则：**
- **Runtime Kernel 最小化**：只做编排，不绑定模型、工具、数据库实现
- **每层固定职责**：层之间通过构造函数注入依赖，禁止跨层直接 import
- **所有外部调用必经 Governance**：安全策略前置

**接口契约**：`runtime/ports.py` 定义了 7 个 Protocol 接口作为 SPI（Service Provider Interface）边界：
- `RuntimePersistencePort` — 消息持久化
- `RuntimeTracePort` — 链路追踪
- `RuntimeAuditPort` — 审计日志
- `RuntimeCapabilityExecutorPort` — 能力执行
- `RuntimePolicyPort` — 策略判定
- `RuntimeCapabilityCatalogPort` — 能力目录
- `RuntimeArtifactWriterPort` — 产物写入

### 2.2 Akashic-Agent 的分层架构

```
┌────────────────────────────────────────────────────────┐
│                    渠道接入层                              │
│     Telegram / QQ / CLI / Socket / Webhook                │
├────────────────────────────────────────────────────────┤
│                    MessageBus                              │
│     事件分发 / 队列 / Inbound→Outbound                      │
├────────────────────────────────────────────────────────┤
│                    AgentLoop (主循环)                       │
│     消费 InboundMessage → 驱动 CoreRunner → 发送 Outbound  │
├────────────────────┬───────────────────────────────────┤
│    CoreRunner      │    Plugin Manager                    │
│    AgentCore       │    ┌─ Lifecycle Hooks               │
│    Reasoner        │    │  before_turn / after_turn      │
│    ContextBuilder  │    │  before_reasoning / after_step │
│    MemoryRetrieval │    │  Tool handlers / Channels      │
│    LLMProvider     │    └─────────────────────────────   │
├────────────────────┴───────────────────────────────────┤
│                    Infrastructure                          │
│     SessionManager / PresenceStore / EventBus               │
└────────────────────────────────────────────────────────┘
```

**分层原则：**
- **基于 EventBus 的事件驱动**：生命周期钩子全是 EventBus 上的 Typed Event
- **Plugin 为主体的扩展**：插件可以注册工具、生命周期钩子、Tool Hooks、渠道（Channel）
- **CoreRunner 作为消息路由**：根据消息类型（InboundMessage / SpawnCompletion）分派到不同处理链

### 2.3 Hermes-Agent 的分层架构

```
┌────────────────────────────────────────────────────────┐
│                    CLI / Gateway                           │
│     命令行入口 / WebSocket Gateway / Slack / Telegram     │
├────────────────────────────────────────────────────────┤
│                    AIAgent (单体 Agent)                    │
│     ┌──────────────────────────────────────────────┐   │
│     │  init_agent() — 60+ 参数初始化                  │   │
│     │  · Provider 自动探测（anthropic, openai,      │   │
│     │    bedrock, ollama, openrouter...）             │   │
│     │  · 回调系统（thinking/stream/tool/status）      │   │
│     │  · ContextCompressor（可替换插件引擎）           │   │
│     │  · MemoryStore / Memory Provider Plugin        │   │
│     │  · ToolRegistry / Toolset 过滤                 │   │
│     │  · 断点续跑 / Interrupt / Steer 机制           │   │
│     │  · Provider Fallback 链                        │   │
│     └──────────────────────────────────────────────┘   │
├────────────────────────────────────────────────────────┤
│                    Conversation Loop                     │
│     run_conversation() — 单次用户消息的完整生命周期       │
│     build_turn_context → model_call → tool_dispatch       │
│     → compress → post_turn_hooks → memory_review         │
├────────────────────────────────────────────────────────┤
│                    Tool System                            │
│     Toolset Distributions / Tool Registry / Checkpoints   │
├────────────────────────────────────────────────────────┤
│                    Compressor / Memory / Skills           │
│     ContextCompressor (ABC) / MemoryManager / Skills     │
└────────────────────────────────────────────────────────┘
```

**分层原则：**
- **无显式分层，靠函数提取和回调解耦**：核心代码集中在 `AIAgent` 类的属性与方法上，通过 `agent_init.py` / `conversation_loop.py` / `conversation_compression.py` 等文件做垂直切分
- **ABC（Abstract Base Class）开放扩展点**：`ContextEngine` 作为抽象基类，第三方可实现 `should_compress()` / `compress()` / `get_tool_schemas()`
- **依赖注入通过参数+属性传递**：不是严格 DI 容器，而是通过 `init_agent()` 函数传递 60+ 参数赋值到 agent 实例属性上

---

## 3. 组件组装与依赖注入

### 3.1 Cogito-Agent：工厂函数 + Hexagonal Ports

**核心组装点**：`application/runtime_factory.py::build_runtime_kernel()`

```python
def build_runtime_kernel(
    db: Database,
    *,
    budget: TurnBudget | None = None,
    model_adapter: ModelAdapter | None = None,
    capability_registry: CapabilityRegistry | None = None,
    policy_engine: PolicyEngine | None = None,
    ...
) -> RuntimeKernel:
    # 1. 从 Database 创建持久化/追踪/审计/策略等运行时服务
    services = db.create_runtime_services(...)
    
    # 2. 按需构建记忆服务、检索管线、合并服务
    memory_svc = MemoryApplicationService(db, retrieval_service=...)
    consolidation_svc = ConsolidationService(memorizer=..., model_adapter=...)
    
    # 3. 将服务注入 Kernel
    kernel = RuntimeKernel(services, ...)
    kernel.set_memory_service(memory_svc)
    kernel.set_consolidation_service(consolidation_svc)
    return kernel
```

**低耦合手段**：
- **依赖倒置**：Kernel 只依赖 `ports.py` 中的 Protocol 接口，具体实现在 storage/ 目录中
- **工厂不暴露内部构造细节**：调用方只传入高层抽象（Database, ModelAdapter），工厂内部负责组装
- **默认值惰性构造**：policy_engine / retrieval_service 等参数在未传入时由工厂内部 new 出默认实现

### 3.2 Akashic-Agent：消息总线 + Dataclass 依赖分组

**核心组装点**：`looping/core.py::AgentLoop.__init__()`

```python
class AgentLoop:
    def __init__(self, deps: AgentLoopDeps, config: AgentLoopConfig):
        # 1. 服务对象通过依赖分组传入
        self._llm_services = deps.llm_services or LLMServices(
            provider=deps.provider,
            light_provider=deps.light_provider or deps.provider,
        )
        self._session_services = deps.session_services or SessionServices(
            session_manager=deps.session_manager,
            presence=deps.presence,
        )
        # 2. 内部装配被动运行时链
        self._assemble_passive_runtime(deps=deps, config=config)
```

**依赖分组设计**：
```python
@dataclass
class AgentLoopDeps:
    bus: "MessageBus"         # 消息总线
    provider: "LLMProvider"   # 主模型提供者
    tools: "ToolRegistry"     # 工具注册表
    session_manager: "SessionManager"
    workspace: Path
    event_bus: "EventBus | None" = None
    llm_services: LLMServices | None = None    # 可选覆盖
    memory_services: MemoryServices | None = None
    session_services: SessionServices | None = None
```

**低耦合手段**：
- **Dataclass 作为 DI 参数对象**：所有依赖打包为 `AgentLoopDeps` 一个 dataclass，避免函数参数爆炸
- **配置/服务分离**：`AgentLoopConfig` 只放配置参数（模型名、窗口大小等），`AgentLoopDeps` 只放运行时对象
- **可选覆盖**：每个服务字段都有默认 `None`，在构造函数中用 `or` 模式构造默认实现

### 3.3 Hermes-Agent：大初始化函数 + 属性注入

**核心组装点**：`agent_init.py::init_agent()`

```python
def init_agent(
    agent,
    base_url=None, api_key=None, provider=None,
    model="", max_iterations=90,
    enabled_toolsets=None, disabled_toolsets=None,
    thinking_callback=None, stream_delta_callback=None,
    session_id=None,
    # ... 共 60+ 参数
):
    agent.model = model
    agent.max_iterations = max_iterations
    agent.iteration_budget = iteration_budget or IterationBudget(max_iterations)
    agent.provider = provider_name or ""
    # ... 大量属性赋值，无显式分层
```

**低耦合手段**：
- **回调代替继承**：tool_progress_callback / thinking_callback / stream_delta_callback 等几十个回调，让不同层可以观察 Agent 行为而不侵入其逻辑
- **属性覆盖模式**：每个可配置项都遵循「参数 > 配置文件 > 环境变量 > 默认值」的优先级链
- **ABC 开放基类**：`ContextEngine(ABC)` 定义标准接口，第三方实现可完全替换默认的 ContextCompressor

---

## 4. 端口适配器（Hexagonal）模式应用

### 4.1 Cogito-Agent：纯正 Hexagonal Architecture

`runtime/ports.py` 定义了完整的**端口（Ports）** 集合，使用 `typing.Protocol` 标记运行时可检查的接口：

```python
class RuntimePersistencePort(Protocol):
    def list_messages(self, session_id: str, workspace_id: str) -> list[dict[str, object]]: ...
    def persist_user_message(self, *, message_id, workspace_id, session_id, content, title_if_empty) -> None: ...
    # ...

class RuntimeTracePort(Protocol):
    def create_trace(self, workspace_id, root_event_id, session_id=None) -> Trace: ...
    def create_span(self, trace_id, name, kind, parent_span_id=None) -> Span: ...
    # ...
```

**适配器（Adapters）** 分散在 `storage/` 目录：
- `storage/runtime_persistence.py` — 实现 `RuntimePersistencePort`
- `storage/context_sink.py` — 实现 Trace 持久化
- `governance/policy.py` — 实现 `RuntimePolicyPort`
- `execution/executor.py` — 实现 `RuntimeCapabilityExecutorPort`

**组合边界**也使用 Protocol：
```python
@runtime_checkable
class RuntimeServicesProvider(Protocol):
    def create_runtime_services(self, *, capability_registry=None, policy_engine=None, artifact_writer=None) -> RuntimeServices: ...
```
`Database` 类实现了这个 Protocol，作为整个后端的组合入口。

### 4.2 Akashic-Agent：Typed Dataclass + EventBus 模式

Akashic 不使用 Protocol 定义端口，而是通过 **Typed Dataclass 分组** + **EventBus 事件契约** 实现类似效果：

```python
@dataclass
class LLMServices:
    provider: LLMProvider
    light_provider: LLMProvider

@dataclass
class SessionServices:
    session_manager: SessionManager
    presence: PresenceStore | None = None
```

**事件契约**通过 Typed Context Object 传递：
```python
class BeforeTurnCtx: ...
class BeforeReasoningCtx: ...
class AfterStepCtx: ...
class PromptRenderCtx: ...
```

插件通过 EventBus 订阅这些事件，实现观察者模式解耦。

### 4.3 Hermes-Agent：ABC + Callback 模式

Hermes 使用 **ABC（抽象基类）** 定义扩展点：

```python
class ContextEngine(ABC):
    @abstractmethod
    def should_compress(self, prompt_tokens=None) -> bool: ...
    @abstractmethod
    def compress(self, messages, current_tokens=None, focus_topic=None) -> list: ...
    @abstractmethod
    def update_from_response(self, usage) -> None: ...
```

此外，大量的 **Callback** 函数作为 Port 的轻量替代：
```python
# 协议就是可调用签名
thinking_callback: callable = None,
stream_delta_callback: callable = None,
tool_progress_callback: callable = None,
status_callback: callable = None,
```

三方项目也可通过 `plugins/context_engine/<name>/` 目录放置新的 ContextEngine 实现。

---

## 5. 插件系统与生命周期钩子

### 5.1 Akashic-Agent：最完善的插件系统

Akashic 的插件系统最为完整，分为三个层面：

#### 5.1.1 生命周期事件钩子（Lifecycle Hooks）

`agent/lifecycle/` 定义了 **TurnLifecycle** 作为门面，通过 EventBus 实现事件传播：

```python
class TurnLifecycle:
    def on_before_turn(self, handler)    # Gate handler：可以修改上下文或中断流程
    def on_before_reasoning(self, handler)
    def on_before_step(self, handler)
    def on_prompt_render(self, handler)
    def on_after_reasoning(self, handler)  # Gate handler
    def on_after_step(self, handler)      # Tap handler：只观察不修改
    def on_after_turn(self, handler)      # Tap handler
```

- **Gate handler**：返回 `ctx | None`，可以修改上下文或阻断流程
- **Tap handler**：返回 `None`，只观察副作用

#### 5.1.2 装饰器驱动

`agent/plugins/decorators.py` 提供一系列装饰器让插件声明能力：

```python
@on_before_turn()       # 注册 before_turn 生命周期钩子
@on_before_reasoning()
@on_after_step()
@on_tool_call()         # 工具调用前观察
@on_tool_pre(tool_name="xxx")  # 特定工具的预处理钩子
@tool(name="my_tool", risk="read-write")  # 注册为工具
```

#### 5.1.3 插件加载管理器

`agent/plugins/manager.py::PluginManager` 实现了完整的插件生命周期：
1. **扫描**：从 `plugin_dirs` 目录发现可加载的 `plugin.py`
2. **导入**：使用 `importlib.util` 从文件路径加载，不依赖 `sys.path`
3. **实例化**：创建插件类实例，注入 `PluginContext`（含 EventBus、ToolRegistry、KVStore）
4. **注册**：绑定生命周期 handler、注册工具、收集 ToolHook、收集 Channel
5. **初始化**：调用 `instance.initialize()`，失败时自动回滚所有注册

#### 5.1.4 回滚机制

插件初始化失败时，PluginManager 会自动回滚所有已注册的工具、事件监听和钩子，保证系统不会处于半加载状态。

### 5.2 Cogito-Agent：内置 Skill 系统

Cogito 的扩展能力通过 **Skill 系统** 和 **Capability Registry** 实现，目前没有暴露插件 API：

- **Skill**：`skill/builtin/` 包含内置技能（daily_brief、inbox_digest、memory_consolidation、trace_review、task_extraction）
- **Capability Registry**：`capability/registry.py` 注册和发现工具能力
- **MCP 集成**：`mcp/manager.py` 管理 MCP Server 的生命周期

### 5.3 Hermes-Agent：ContextEngine 插件与 Memory Provider

Hermes 通过 **目录发现** 加载 ContextEngine 插件：

1. 配置 `context.engine` 指定引擎名
2. 尝试 `plugins/context_engine/<name>/` 目录加载
3. 尝试通用插件系统 `get_plugin_context_engine()`
4. 兜底使用内置 `ContextCompressor`

**Memory Provider** 也是插件化的：
1. 配置 `memory.provider` 指定名称
2. `plugins/memory/load_memory_provider()` 加载
3. 通过 `MemoryManager.add_provider()` 注册
4. `inject_memory_provider_tools()` 将提供者的工具注入 Agent

---

## 6. 工具/能力注册与治理

### 6.1 Cogito-Agent：Capability Registry + Governance

```
Tool Intent → CapabilityRegistry → SchemaValidation → PolicyCheck
  → Approval(if needed) → ToolExecution → ResultNormalize → Trace
```

所有能力调用必须经过 **Governance Plane**：
- `PolicyEngine` 根据主体+能力+资源+操作+上下文做决策
- `GovernedCapabilityExecutor` 封装策略检查、Guardians（Network/Path/Shell/SecretEgress）、审计
- 能力声明包含名称、schema、权限范围、风险等级、可调用场景、审批要求

### 6.2 Akashic-Agent：ToolRegistry + MCP

```python
# agent/tools/registry.py — 统一工具注册
self._tool_registry.register(
    wrapper,
    risk="external-side-effect",
    source_type="mcp",
    source_name=name,
)
```

- MCP 工具通过 `McpServerRegistry` 从 MCP Server 同步到 ToolRegistry
- 插件工具通过 `PluginManager._register_tools()` 注册
- 工具可以声明 risk 等级（read / read-write / external-side-effect / dangerous）
- `ToolDiscoveryState` 跟踪工具搜索状态

### 6.3 Hermes-Agent：Toolset Distributions + Filtering

Hermes 通过 **toolsets.py** 和 **toolset_distributions.py** 管理工具：

```python
agent.tools = _ra().get_tool_definitions(
    enabled_toolsets=enabled_toolsets,
    disabled_toolsets=disabled_toolsets,
)
```

- 工具按 Toolset 分组（filesystem, code, terminal, memory, MCP, ...）
- 支持 enable/disable 过滤，Channel 可配置不同 Toolset
- 通过 Provider 路由到不同 API 模式（chat_completions / codex_responses / anthropic_messages / bedrock_converse）
- MCP 工具通过 `refresh_agent_mcp_tools()` 动态刷新

---

## 7. 主循环与状态推进

### 7.1 Cogito-Agent：RuntimeKernel.process()

```python
class RuntimeKernel:
    def process(self, event: RuntimeEvent) -> TurnResult:
        # 7 phases in a state machine:
        # 1. Init — 初始化 Turn 上下文
        # 2. Context — 构建 Prompt
        # 3. Reason — 模型调用
        # 4. Extract — 处理工具调用意图
        # 5. Execute — 执行工具
        # 6. Observe — 处理工具结果
        # 7. Complete — 完成 Turn
```

- 使用 `TurnStateMachine`（PREPARING → REASONING → EXECUTING → OBSERVING → COMPLETED）管理状态
- 内置 `TurnBudget` 限制模型调用次数
- 支持 `process_stream()` 流式输出
- 每个 Turn 有完整的 Trace（Span 树）

### 7.2 Akashic-Agent：AgentLoop.run()

```python
class AgentLoop:
    async def run(self):
        while self._running:
            item = await self.bus.consume_inbound()
            task = asyncio.create_task(self._process(item))
            await task
    
    async def _process(self, msg, session_key=None):
        # 1. 检查中断续跑
        msg, resumed = self._resume_interrupted_message(msg, key)
        # 2. 发布 TurnStarted 事件
        await self._observe_turn_started(msg, key)
        # 3. 进入 CoreRunner
        outbound = await self._core_runner.process(msg, key)
        return outbound
```

- 基于 `asyncio` 的事件循环，从 MessageBus 消费 InboundMessage
- 每个 session_key 有独立的 `TurnInterruptState` 管理中断态
- 支持中断续跑：从 `_interrupt_states` 恢复，拼装补全提示

### 7.3 Hermes-Agent：run_conversation()

```python
def run_conversation(agent, user_message, ...):
    # 1. build_turn_context — 构建消息列表
    # 2. 检查是否需压缩
    # 3. 发送模型请求（带重试/降级）
    # 4. 处理工具调用循环
    # 5. 后处理：记忆审查、技能审查
    # 6. 返回响应
```

- 单次调用（无常驻事件循环），每个用户请求调用一次
- 工具调用循环按 iteration_budget 控制最多 max_iterations 轮
- 支持 provider failover（fallback chain）
- 内建 `CompressionChecker` 在每次调用前判断是否需要压缩

---

## 8. 配置加载与环境适配

### 8.1 Cogito-Agent：`config/loader.py`

- 分层配置：从 yaml/env/defaults 多源合并
- `compose_from_env()` 将环境变量映射为配置对象
- `Database.from_config()` 支持从配置对象创建持久化层

### 8.2 Akashic-Agent：`agent/config.py` + `config_models.py`

**配置+模型分离**：

```python
# config_models.py — 纯数据类，无导入逻辑
@dataclass
class Config:
    provider: str
    model: str
    api_key: str
    channels: ChannelsConfig
    memory: MemoryConfig
    plugins: dict
    wiring: WiringConfig

# config.py — 加载逻辑，返回 Config 实例
def load_config(path: str = "config.toml") -> Config
```

- 支持 `toml` 格式 + `${ENV_VAR}` 环境变量插值
- 内置 provider 预设（`_PRESETS`：qwen/deepseek/openai 的 base_url）
- 验证：时区验证、embedding dimensionality 验证

### 8.3 Hermes-Agent：YAML 配置文件

- `config.yaml` + `hermes config set` CLI 命令
- 多 profile 支持（`hermes model` 切换 provider）
- 工具集启用/禁用区分全局和 per-channel
- provider 自动探测（根据 base_url 和模型名推断 api_mode）

---

## 9. 消息处理流水线

### Cogito-Agent 的消息链路

```
User Input
  → api/app.py / cli/chat.py
  → ChatApplicationService.process_message()
  → RuntimeKernel.process()
    → ContextEngine 构建 Prompt
    → ModelRouter 选取模型 → ModelAdapter.chat()
    → 工具调用 → CapabilityExecutor.execute()
    → Governance Plane 策略检查
    → Trace 记录
  → 结果返回
```

### Akashic-Agent 的消息链路

```
InboundMessage
  → MessageBus 队列
  → AgentLoop._process()
    → CoreRunner.process()
      → match msg type:
        SpawnCompletionItem → process_spawn_completion_event()
        InboundMessage → AgentCore.process()
          → ContextStore 加载上下文
          → Plugin before_turn hooks
          → Reasoner.run()
            → LLM call
            → Tool call loop
          → Plugin after_turn hooks
          → Memory consolidation
    → OutboundMessage → MessageBus 发送
```

### Hermes-Agent 的消息链路

```
User message
  → run_conversation()
    → build_turn_context() 构建消息列表
      → 加载 memory / context 文件
      → 构建系统提示
    → check_and_compress() 检查压缩
    → model_call() 带重试/降级
    → tool_call_loop()
      → handle_function_call() 执行工具
      → 检查中断/预算
    → post_turn: memory review / skill nudge
    → 返回响应
```

---

## 10. 对比总结矩阵

| 维度 | Cogito-Agent | Akashic-Agent | Hermes-Agent |
|------|-------------|---------------|-------------|
| **架构风格** | 分层 Hexagonal | 事件驱动 + 插件 | 单体 Agent + 回调 |
| **解耦方式** | Protocol 端口 + 工厂 | EventBus + Dataclass DI | Callback + ABC |
| **扩展机制** | Capability Registry + Skill | 装饰器插件 + Lifecycle Hooks | ContextEngine 插件 + Memory Provider |
| **主循环** | RuntimeKernel 状态机 | AgentLoop asyncio 事件循环 | run_conversation 单次调用 |
| **消息总线** | 无显式总线 | MessageBus (inbound/outbound) | 无显式总线（回调桥接） |
| **工具治理** | PolicyEngine + Guardians | risk 等级 + ToolRegistry | Toolset filter + tool guardrails |
| **多模型支持** | ModelRouter / ModelAdapter | LLMProvider + 策略模式 | Provider 自动探测 + Fallback 链 |
| **追踪/审计** | 内建 TraceSpan + Audit | EventBus + Presence | 无内建追踪（靠 Session 日志） |
| **记忆系统** | Memory v2: structured + BM25+密集 | Markdown + MemoryEngine | MEMORY.md + Memory Provider Plugin |
| **配置格式** | yaml + env | toml + ${ENV_VAR} | yaml + CLI 命令 |
| **依赖注入** | 工厂函数注入 | Dataclass Deps 分组注入 | 60+ 参数属性赋值 |
| **安全策略** | Capability-based Policy | 工具 risk 等级 | Tool guardrails |
| **多渠道** | Web Console / CLI / API | Telegram / QQ / CLI / Socket | CLI / Gateway / Telegram / Discord |
| **主动服务** | Autonomy Plane (Scheduler + Drift + ProactiveLoop) | Proactive runtime | 无内建主动服务 |

---

## 核心启示与工程总结

### 低耦合的共同手法

1. **依赖倒置**：三个项目都通过「面向接口编程」实现核心与实现的解耦（Cogito 用 Protocol，Akashic 用 Dataclass+EventBus，Hermes 用 ABC+Callback）
2. **工厂模式**：Cogito 有 `build_runtime_kernel()`，Akashic 有 `_assemble_passive_runtime()`，Hermes 有 `init_agent()`
3. **可替换默认值**：所有依赖都有一个「参数传入 → 默认构造」的 fallback 链
4. **观察者模式**：Akashic 的 EventBus、Hermes 的 Callback 系统、Cogito 的 Trace/Observe 机制

### 各自特色

- **Cogito-Agent**：架构最严谨，分层最清晰，Ports/Adapters 模式最纯正。适合需要长期演进、团队协作的大型项目
- **Akashic-Agent**：插件系统最完善，装饰器驱动的 API 最易用。适合需要频繁扩展渠道和功能的中型项目
- **Hermes-Agent**：Provider 兼容性最强，几乎支持所有主流 LLM 后端。适合需要灵活切换模型和深度工具调用的代码开发场景

### 消息处理的共同链路

三个项目在处理用户消息时都遵循类似的逻辑链：

```
接收 → 标准化 → 构建上下文 → 策略检查 → 模型推理
 → 工具执行（循环） → 结果组合 → 持久化 → 返回响应
```

关键区别在于：
- **Cogito** 将此链编码为显式的 `RuntimeKernel.process()` 状态机
- **Akashic** 将此链拆分为 EventBus 事件触发的各个 Hook
- **Hermes** 将此链实现为 `run_conversation()` 中的顺序调用
