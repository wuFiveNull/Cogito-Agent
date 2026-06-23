# AI Agent 工具调用、沙箱安全与 MCP 设计深度分析

> 基于以下四个项目的源码分析：
>
> - **akashic-agent** — 事件驱动、插件化、多通道 AI Agent 框架（TypeScript + Python）
> - **hermes-agent** — 通用 Agent 运行时，支持多 provider、多工具集（Python，单文件 700KB+）
> - **QwenPaw** — 基于 AgentScope ReAct 的编码助手 Agent（Python）
> - **Cogito-Agent** — 六边形架构的生产级 Agent 框架（Python）
>
> 本文聚焦**三个关键维度**：工具调用机制的设计与实现、沙箱/安全机制的架构与原理、MCP（Model Context Protocol）的设计与集成。

---

## 目录

1. [工具调用机制](#一工具调用机制)
   - [1.1 akashic-agent：ToolRegistry + ToolExecutor + ToolHook 链](#11-akashic-agent)
   - [1.2 hermes-agent：model_tools + tool_guardrails + 并发分发](#12-hermes-agent)
   - [1.3 QwenPaw：ReActAgent + Toolkit + Mixin 链](#13-qwenpaw)
   - [1.4 Cogito-Agent：CapabilityRegistry + GovernedCapabilityExecutor](#14-cogito-agent)
   - [1.5 横向对比：工具调用的架构模式](#15-横向对比)
2. [沙箱与安全机制](#二沙箱与安全机制)
   - [2.1 akashic-agent：插件级安全 Hook 链](#21-akashic-agent-插件级安全-hook-链)
   - [2.2 hermes-agent：OS 级隔离 + 多层守卫](#22-hermes-agent-os-级隔离--多层守卫)
   - [2.3 QwenPaw：ToolGuardEngine + 四层执行等级](#23-qwenpaw-toolguardengine--四层执行等级)
   - [2.4 Cogito-Agent：防护者模式 + 策略引擎](#24-cogito-agent-防护者模式--策略引擎)
   - [2.5 横向对比：安全架构设计哲学](#25-横向对比安全架构设计哲学)
3. [MCP 设计与集成](#三mcp-设计与集成)
   - [3.1 akashic-agent：McpClient + McpServerRegistry + McpToolWrapper](#31-akashic-agent)
   - [3.2 hermes-agent：全功能 MCP Client Runner](#32-hermes-agent)
   - [3.3 QwenPaw：StatefulClient + 热重载 Manager](#33-qwenpaw)
   - [3.4 Cogito-Agent：MCPTrustStore + MCPServerManager](#34-cogito-agent)
   - [3.5 横向对比：MCP 设计考量](#35-横向对比mcp-设计考量)
4. [综合对比表](#四综合对比表)
5. [总结：各项目设计哲学与最佳实践](#五总结各项目设计哲学与最佳实践)

---

## 一、工具调用机制

### 1.1 akashic-agent

#### 架构总览

akashic-agent 的工具系统分为三层：

```
Tool (抽象基类)          → 工具定义层
ToolRegistry             → 注册中心层 (管理生命周期 + Schema 生成)
ToolExecutor + ToolHook  → 执行层 (pre-hooks → invoker → post-hooks)
```

#### Tool 抽象基类

位于 `agent/tools/base.py`，要求子类实现三个类字段：

```python
class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema 格式

    async def execute(self, **kwargs) -> str | ToolResult: ...
```

- 通过 `__init_subclass__` 在子类化时自动校验完整性（name/description/parameters 不能为空）
- 内建参数校验器 `validate_params()`，支持递归的 JSON Schema 子集校验
- `to_schema()` 转换为 OpenAI function calling 格式

#### ToolRegistry — 注册中心

位于 `agent/tools/registry.py`，是整个工具系统的**数据中心**：

```python
class ToolRegistry:
    register(tool, *, risk, always_on, search_hint, source_type, source_name)
    get_schemas(names=None) → list[dict]    # 生成 OpenAI 格式 Schema
    execute(name, arguments) → str           # 执行工具
    search(query, top_k) → list[dict]       # 关键词搜索工具目录
    get_deferred_names(visible) → dict       # 延迟加载工具目录
```

**关键特性：**

1. **风险等级元数据**：每个工具有 `risk` 标记（`read-only` / `write` / `external-side-effect`），安全 hook 可据此决策
2. **Always-on 与延迟加载**：`always_on` 标记为 True 的工具始终暴露 Schema；其他工具通过 `tool_search` 机制动态加载，减小初始 prompt 体积
3. **工具搜索后端**：内建 `KeywordSearchBackend`，支持关键词匹配；可替换为向量搜索
4. **多源注册**：工具可来自 Built-in / MCP / Plugin / Peer Agent，通过 `source_type` / `source_name` 追踪来源

#### ToolExecutor — 执行引擎

位于 `agent/tool_hooks/executor.py`，负责串联 ToolHook 链：

```
ToolExecutionRequest
  → _run_pre_hooks()     # pre_hooks：匹配、改参、拒绝决策
      → denied? 返回 denied 结果
  → invoker()           # 真实执行（ToolRegistry.execute）
  → _run_post_hooks()   # post_hooks：审计、记录、附加信息
  → ToolExecutionResult
```

**三阶段设计：**

| 阶段 | 事件 | 可修改参数 | 可拒绝 | 用途 |
|------|------|-----------|--------|------|
| Pre | `pre_tool_use` | ✓ | ✓ | 沙箱检查、参数重写、安全拦截 |
| Execute | 调用 invoker | - | - | 真实工具逻辑 |
| Post | `post_tool_use` / `post_tool_error` | ✗（只读） | ✗ | 审计、追踪、进度通知 |

**Hook 匹配机制**：每个 `ToolHook` 实现 `matches(ctx)` 方法，根据 `tool_name`、`arguments` 等条件决定是否生效。所有匹配的 pre-hook 按注册顺序执行——**前一个可修改参数传递给下一个**。

#### 工具来源注册方式

通过 `ToolsetProvider` Protocol 实现**可插拔注册**：

```python
class ToolsetProvider(Protocol):
    def register(self, registry: ToolRegistry, deps: ToolsetDeps) -> ToolsetRegistrationResult: ...
```

在组合根（`bootstrap/tools.py`）中，按配置文件 `config.toml` 的 `wiring.toolsets` 启用：

```python
# bootstrap/tools.py 中的组装流程
MemoryToolsetProvider.register(tools, deps)     # 记忆读写
SpawnToolsetProvider.register(tools, deps)      # spawn 子 Agent
CommonMetaToolsetProvider.register(tools, deps) # web_fetch 等
McpToolsetProvider.register(tools, deps)        # MCP 工具
SchedulerToolsetProvider.register(tools, deps)  # 定时任务
```

---

### 1.2 hermes-agent

#### 架构总览

hermes-agent 的工具系统是**过程式大循环**中的核心组成部分。与 akashic-agent 的精心分层不同，hermes-agent 的代码组织更自由：

```
tools/registry.py           → 中央注册中心（自注册模式）
tools/*.py                  → 各工具实现（模块级 registry.register() 调用）
model_tools.py              → 工具分派中枢（~57KB）
agent/tool_executor.py      → 执行引擎（顺序/并发）
agent/tool_guardrails.py    → 纯函数式循环防护控制器
```

#### 工具注册：自发现 + 自注册

位于 `tools/registry.py`，采用**自发现模式**：

```python
class ToolEntry:
    """Metadata for a single registered tool."""
    name: str
    handler: Callable
    schema: dict
    toolset: str              # 所属工具集名
    availability: Callable    # 可用性检查函数

# 自发现入口
def discover_builtin_tools(tools_dir=None) -> List[str]:
    # 扫描 tools/*.py，用 AST 解析判断是否包含 registry.register()
    # 导入匹配的模块（触发模块级的 registry.register() 调用）
```

每个工具文件在模块级别调用 `registry.register()`：

```python
# tools/file_operations.py 示例
registry.register(
    name="read_file",
    schema={...},
    handler=read_file_handler,
    toolset="filesystem",
)
```

#### 工具执行引擎

位于 `agent/tool_executor.py`，支持两种模式：

**顺序执行**（默认）：
```python
for tool_call in tool_calls:
    result = await execute_single_tool(agent, tool_call)
    messages.append(result)
```

**并发执行**（`_should_parallelize_tool_batch` 判定）：
```python
# 使用 ThreadPoolExecutor（最多 8 个 worker）
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(execute_tool, ...) for tc in tool_calls]
```

#### Tool Guardrails — 循环防护控制器

位于 `agent/tool_guardrails.py`，是一个**纯函数式、无副作用**的控制器：

```python
class ToolCallGuardrailController:
    def before_call(self, tool_name, args) -> ToolGuardrailDecision:
        # 检查：同签名失败次数 → block；幂等工具无进展 → block
    def after_call(self, tool_name, args, result, *, failed) -> ToolGuardrailDecision:
        # 检查：精确失败次数 → warn；同工具失败次数 → halt；幂等工具无进展 → warn
```

**决策类型**：`allow` → `warn` → `block` → `halt`（从通过到终止的递进）

**关键区别**：与 akashic-agent 的 ToolHook 不同，hermes-agent 的 guardrail 是一个独立的状态机，**不嵌入执行器链**，而是由调用方（`run_agent.py` / `conversation_loop.py`）主动查询。

#### 工具分派中枢

`model_tools.py` 是 ~57KB 的工具分派枢纽，包含：

- `handle_function_call()` — 根据工具名路由到对应 handler
- `get_toolset_for_tool()` — 查找工具所属的工具集
- `_emit_post_tool_call_hook()` — 工具调用后发射 hook 事件
- Shell hooks 桥接（`agent/shell_hooks.py`）— 支持用户自定义 shell 脚本作为 hook

---

### 1.3 QwenPaw

#### 架构总览

QwenPaw 基于 AgentScope 框架的 `ReActAgent`，通过**继承 + Mixin 链**扩展工具调用能力：

```
ReActAgent (AgentScope)
  └─ ToolGuardMixin      → 安全拦截层
       └─ CodingModeMixin → 编码模式层
            └─ QwenPawAgent → 最终 Agent
```

#### ReAct 循环中的工具调用

AgentScope 的 `ReActAgent.reply()` 是核心循环：

```
_reasoning()  → LLM 推理，返回 tool_plan / tool_use / text
_acting()     → 执行工具，返回 tool_result
_observe()    → 将 tool_result 放入 memory，供下一轮推理
```

QwenPaw 通过重写 `_reasoning()` 和 `_acting()` 插入自定义逻辑：

```
QwenPawAgent._reasoning()
  → 计划门控 (Plan Gate)
  → 媒体过滤（双层：Proactive + Passive）
  → super()._reasoning() → AgentScope 调用 LLM
  → _filter_plan_tools()
  → Auto-continue 处理

QwenPawAgent._acting()
  → 计划门控 (Plan Tool Gate)
  → ToolGuardMixin._acting()（安全拦截）
  → CodingModeMixin._acting()（内联 diff 模式）
  → ReActAgent._acting() → Toolkit.execute()
```

#### 工具注册方式

QwenPaw 直接在 Agent 初始化时注册工具：

```python
# QwenPawAgent.__init__()
self.toolkit = Toolkit()
self.toolkit.register(execute_shell_command)
self.toolkit.register(read_file)
self.toolkit.register(write_file)
self.toolkit.register(browser_use)
# ... 注册 20+ 个工具
```

工具是普通的 Python 异步函数，通过 `@tool` 装饰器或 `Toolkit.register()` 注册。AgentScope 自动将它们包装为 LLM 可调用的 tool schema。

#### 技能系统的工具加载

QwenPaw 支持从工作目录动态加载技能（skill）：

```python
# skill_system.py
resolve_effective_skills()  → 解析启用的技能
materialize_skill()         → 将技能函数注册到 toolkit
```

---

### 1.4 Cogito-Agent

#### 架构总览

Cogito-Agent 采用**六边形架构**，工具调用能力系统设计最为规范：

```
capability/registry.py      → CapabilityRegistry（能力注册中心）
capability/tools.py          → 内建工具实现（文件读写、沙箱路径解析）
execution/executor.py        → GovernedCapabilityExecutor（受治理的执行器）
execution/guardians.py       → Guardian 基类 + 具体防护者
governance/policy.py         → PolicyEngine（策略引擎）+ PolicyStrategy
```

#### CapabilityRegistry — 能力注册中心

```python
class CapabilityRegistry:
    def register(
        self,
        name: str,
        manifest: CapabilityManifest,
        invoker: Callable,
    ) -> None: ...

class CapabilityManifest:
    name: str
    type: CapabilityType       # builtin / mcp_server / subagent
    risk_level: RiskLevel      # low / medium / high / critical
    allowed_contexts: list[str]  # interactive / background / ...
    approval_required: bool
    audit_required: bool
    idempotent: bool
```

与 akashic-agent 的 `ToolMeta` 类似但更加正式——每个能力有完整的 `CapabilityManifest` 元数据声明，治理层据此决策。

#### GovernedCapabilityExecutor — 受治理的执行器

这是 Cogito-Agent 的关键创新点——**治理与执行合一**：

```python
class GovernedCapabilityExecutor:
    async def execute(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult:
        # 1. 策略评估 (PolicyEngine)
        decision = self._policy.evaluate(request.to_policy_request())

        # 2. 防护者检查 (Guardians)
        for guardian in self._guardians:
            reason = guardian.inspect(request, manifest)
            if reason:
                return CapabilityExecutionResult(status="blocked", ...)

        # 3. 审批流 (Approval)
        if decision == "require_approval":
            approved = await self._approval.create(...)
            if not approved:
                return CapabilityExecutionResult(status="pending_approval", ...)

        # 4. 审计 (Audit)
        self._audit.log(...)

        # 5. 追踪 (Trace)
        with self._tracer.span(...):
            result = await invoker(request.arguments)

        return CapabilityExecutionResult(status="ok", ...)
```

**六步流水线**：策略评估 → 防护者检查 → 审批流 → 审计 → 追踪 → 真实执行

#### 工具实现

`capability/tools.py` 包含核心内建工具：

- `read_file` / `write_file` / `edit_file` — 文件操作，含沙箱路径校验
- `shell` — Shell 执行，含 ShellGuardian 检查
- `web_search` / `web_fetch` — 网络操作，含 NetworkGuardian

每个工具有严格的沙箱边界：

```python
def _resolve_safe_path(requested: str) -> Path | None:
    resolved = Path(requested).resolve()
    root = get_sandbox_root()
    if not str(resolved).startswith(str(root)):
        return None  # 路径逃逸检测
    return resolved
```

---

### 1.5 横向对比

| 维度 | akashic-agent | hermes-agent | QwenPaw | Cogito-Agent |
|------|---------------|-------------|---------|-------------|
| **注册方式** | ToolRegistry + ToolsetProvider | registry.register() 自发现 | Toolkit.register() | CapabilityRegistry |
| **Schema 生成** | OpenAI function calling 格式 | OpenAI 格式（可选 Anthropic） | AgentScope 自动 | JSON Schema + Manifeset |
| **执行引擎** | ToolExecutor + Hook 链 | tool_executor (顺序/并发) | ReAct _acting() | GovernedCapabilityExecutor |
| **工具钩子** | ToolHook (pre/post 链) | tool_guardrails (状态机) | ToolGuardMixin._acting() | Guardian.inspect() |
| **延迟加载** | tool_search + deferred | 无专门机制 | 无 | 无 |
| **元数据** | ToolMeta (risk/always_on) | ToolEntry (toolset/availability) | 无（AgentScope 隐式） | CapabilityManifest (完整声明) |
| **扩展方式** | ToolsetProvider Protocol | 自发现 + registry | 继承重写 + Mixin | Ports/Adapters + DI |

---

## 二、沙箱与安全机制

### 2.1 akashic-agent：插件级安全 Hook 链

akashic-agent 的安全机制以**插件 + ToolHook** 为核心，通过 EventBus 的 Gate/Tap 模式和 ToolExecutor 的 pre-hook 链实现。

#### Shell Safety 插件 (`plugins/shell_safety/`)

阻止 shell 工具执行高风险命令：

```python
class ShellSafety(Plugin):
    @on_tool_pre(tool_name="shell")
    async def block_interactive_shell(self, event: PreToolCtx) -> HookOutcome | None:
        command = event.arguments.get("command", "")
        reason = self._deny_reason(command)  # 检查交互式命令、sudo、包管理器等
        if reason:
            return HookOutcome(decision="deny", reason=reason)
```

**检测范围**：
- 交互式编辑器（`vim`/`nano`/`nvim` 等）
- 缺少 `-n` 标志的 `sudo` 命令（可能等待密码）
- 包管理器写操作缺少 `--noconfirm`（`pacman -S` 等）
- 打开系统编辑器的命令（`systemctl edit`、`crontab -e`）

#### Shell Restore 插件 (`plugins/shell_restore/`)

将 `rm` 命令重写为 `mv` 到恢复目录：

```python
class ShellRestore(Plugin):
    @on_tool_pre(tool_name="shell")
    async def rewrite_rm_to_mv(self, event: PreToolCtx) -> dict | None:
        rewritten = self._rewrite_command(command)  # rm → mv 到 ~/restore/
        if rewritten:
            return dict(event.arguments, command=rewritten)
```

这是一个**参数改写型安全机制**——不是简单地阻止，而是安全地转换破坏性操作。

#### Tool Loop Guard (`plugins/tool_loop_guard/`)

检测连续重复的工具调用并截断：

```python
class ToolLoopGuard(Plugin):
    @on_tool_pre()
    async def detect_repeated_tool_call(self, event: PreToolCtx) -> HookOutcome | None:
        signature = f"{tool_name}:{json.dumps(args)}"
        if signature == state.signature:
            state.repeat_count += 1
        if state.repeat_count >= repeat_limit:
            return HookOutcome(decision="deny", reason="连续重复调用已截断")
```

支持**批量调用检测**——在一次 LLM 返回多个 tool_call 时，对整个批次做签名检查。

### 2.2 hermes-agent：OS 级隔离 + 多层守卫

hermes-agent 的安全哲学非常明确：**唯一的安全边界是操作系统**。所有进程内检查都是启发式手段。

#### 信任模型 (`SECURITY.md`)

```
Trust Model 分层：
  Layer 0: 操作系统级隔离（唯一的安全边界）
    ├─ Terminal-backend isolation（容器/远程主机执行 shell）
    └─ Whole-process wrapping（Docker / 沙箱包装整个 Agent 进程）
  Layer 1: 进程内启发式检查（非安全边界）
    ├─ 工具执行守卫 (ToolGuardrailController)
    ├─ 文件安全规则 (file_safety.py)
    ├─ URL 安全 (url_safety.py)
    ├─ 威胁模式扫描 (threat_patterns.py)
    ├─ Tirith 二进制扫描 (tirith_security.py)
    ├─ Schema 清洗 (schema_sanitizer.py)
    ├─ 路径安全 (path_security.py)
    └─ 审批流 (write_approval.py)
```

#### 文件安全 (`agent/file_safety.py`)

拒绝向敏感路径写入：

```python
def build_write_denied_paths(home: str) -> set[str]:
    # 保护：~/.ssh/authorized_keys, ~/.ssh/id_rsa, ~/.env,
    #       ~/.anthropic_oauth.json, /etc/sudoers, /etc/shadow 等
def build_write_denied_prefixes(home: str) -> list[str]:
    # 保护：~/.ssh/, ~/.aws/, ~/.gnupg/, ~/.kube/, /etc/sudoers.d/ 等
```

#### URL 安全 (`tools/url_safety.py`)

阻止 SSRF 攻击——禁止访问内网/私有地址：

```python
def is_private_url(url: str) -> bool:
    # 解析域名 → IP
    # 检查是否为私有网络 (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12,
    #                    192.168.0.0/16, 169.254.0.0/16 等)
    # 始终阻止云元数据端点 (169.254.169.254, metadata.google.internal)
```

文档中明确记录了**已知局限**：DNS rebinding (TOCTOU) 和重定向绕过无法在预检层解决。

#### 威胁模式扫描 (`tools/threat_patterns.py`)

跨上下文的安全扫描——用于检测 prompt 注入、C2 指令、身份劫持等：

```python
_PATTERNS = [
    # 经典注入（全局应用）
    (r'ignore\s+previous\s+instructions', "prompt_injection", "all"),
    (r'system\s+prompt\s+override', "sys_prompt_override", "all"),

    # 角色劫持（context + strict 范围）
    (r'you\s+are\s+now\s+a', "role_hijack", "context"),

    # C2 模式
    (r'register\s+as\s+a\s+node', "c2_node_registration", "context"),
    (r'heartbeat\s+to\s+', "c2_heartbeat", "context"),

    # 严格模式（仅记忆写入 + 技能安装时检查）
    (r'rm\s+-rf\s+/', "destructive_command", "strict"),
]
```

**三等作用域**：`all`（所有输入检查）→ `context`（上下文+记忆+工具结果）→ `strict`（仅记忆写入+技能安装）

#### Tirith 安全扫描 (`tools/tirith_security.py`)

用独立的二进制文件做内容级安全扫描：

```python
# 启动 tirith 子进程扫描命令
# exit code: 0=allow, 1=block, 2=warn
result = subprocess.run(["tirith", "scan", "--input", command],
                       capture_output=True, timeout=5)
```

- 自动从 GitHub Release 下载 tirith，验证 SHA256 校验和
- 支持 cosign 签名验证（供应链安全）
- `fail_open` 配置：tirith 失败时默认放行

#### Schema 清洗 (`tools/schema_sanitizer.py`)

解决不同 LLM 后端对 JSON Schema 的兼容性问题：

```python
def sanitize_tool_schemas(tools: list[dict]) -> list[dict]:
    # 修复：空 properties、null 联合类型、additionalProperties 问题、
    #       $ref + default 共存、type 为数组等
```

#### Code Execution 沙箱 (`tools/code_execution_tool.py`)

代码执行工具的沙箱设计：

- **环境变量过滤**：只传 `PATH`/`HOME`/`LANG` 等安全前缀；排除含 `KEY`/`TOKEN`/`SECRET` 的变量
- **白名单工具**：沙箱内仅允许 7 个工具（`web_search`、`web_extract`、`read_file`、`write_file`、`search_files`、`patch`、`terminal`）
- **资源限制**：超时 5 分钟、最多 50 次工具调用、stdout 50KB、stderr 10KB

### 2.3 QwenPaw：ToolGuardEngine + 四层执行等级

QwenPaw 的安全体系是四个项目中最正式化的——有完整的安全引擎、分级执行策略和多渠道审批 UI。

#### ToolGuardEngine (`security/tool_guard/engine.py`)

```python
class ToolGuardEngine:
    def guard(self, tool_name: str, params: dict) -> ToolGuardResult:
        start = time.time()
        findings = []
        for guardian in self._guardians:
            try:
                finding = guardian.guard(tool_name, params)
                if finding:
                    findings.append(finding)
            except Exception as e:
                # 记录 guardian 失败，继续其他检查
                self._guardians_failed.append(...)
        return ToolGuardResult(findings=findings, duration=...)
```

**三默认防护者**：
1. `FilePathToolGuardian` — 检查敏感文件路径
2. `RuleBasedToolGuardian` — 规则匹配（命令注入、路径穿越等）
3. `ShellEvasionGuardian` — Shell 绕过检测（命令替换、ANSI-C 引号、反斜杠逃逸等）

#### 四层执行等级 (`security/tool_guard/execution_level.py`)

```python
class ToolExecutionLevel(Enum):
    STRICT = "strict"   # 所有工具需审批
    SMART  = "smart"    # 智能分级：INFO/LOW 自动放行，MEDIUM+ 需审批
    AUTO   = "auto"     # 仅守卫工具需审批（向后兼容）
    OFF    = "off"      # 完全禁用守卫
```

#### ToolGuardMixin 的审批流

```python
# ToolGuardMixin._acting() 中的决策逻辑：
guard_result = self._tool_guard_engine.guard(tool_name, params)
if not guard_result.is_safe:
    if execution_level == STRICT:
        approval_decision = await approval_service.request_approval(...)
        if approval_decision.decided:
            if approval_decision.approved:
                return await super()._acting(tool_call)
            else:
                return {"content": "用户拒绝了此工具调用"}
    elif execution_level == SMART and guard_result.max_severity in (MEDIUM, HIGH, CRITICAL):
        # 类似审批流
    # AUTO 模式：只在 guarded_tools 列表中有检查
```

#### 通知渠道集成

QwenPaw 将安全审批 UI 集成到多个消息渠道：

```
tool_guard/
  └── cards/          ← 各渠道的审批卡片渲染
      ├── feishu/cards/tool_guard.py
      ├── qq/cards/tool_guard.py
      ├── telegram/cards/tool_guard.py
      ├── wecom/cards/tool_guard.py
      └── ...
```

#### Shell Evasion Guardian (`security/tool_guard/guardians/shell_evasion_guardian.py`)

专门检测 Shell 命令中的绕过技术：

```python
# 检测清单：
_COMMAND_SUBSTITUTION_PATTERNS：$()、``、${}、=()、<() 等
_ANSI_C_QUOTE_RE：$'...' 和 $"..." 引号绕过
# 引号状态机追踪：字符级解析，区分单引号/双引号/转义上下文
# 检测反斜杠逃逸的空白和运算符
# 检测嵌入的换行符/回车符
# 检测注释-引号失步攻击
```

#### Skill Scanner (`security/skill_scanner/`)

独立的技能安全扫描子系统：

```python
class SkillScanner:
    def scan_skill(self, skill_code: str) -> ScanResult:
        # PatternAnalyzer: 正则匹配危险模式
        # 扫描策略：可配置的 allow/deny/warn 规则
```

### 2.4 Cogito-Agent：防护者模式 + 策略引擎

Cogito-Agent 的安全机制是架构化程度最高的——**策略引擎 + 防护者链 + 审批流 + 审计/追踪**构成完整的治理层。

#### Guardian 基类 (`execution/guardians.py`)

```python
class Guardian(ABC):
    _tag: str  # 用于拦截消息中的标签
    
    def inspect(self, request: CapabilityExecutionRequest, manifest: CapabilityManifest) -> str | None:
        # 模板方法：先跑硬规则，再可选 LLM 检查
        reason = self._hard_rules(request)
        if reason:
            return reason
        if self._llm:
            reason = self._llm_checks(request)
            if reason:
                return f"LLM {self._tag} guard: {reason}"
        return None
```

**四种内置防护者**：

| 防护者 | 硬规则 | LLM 检查 | 用途 |
|--------|--------|----------|------|
| `PathGuardian` | Null 字节、`..` 穿越 | 可疑路径语义分析 | 文件操作安全 |
| `NetworkGuardian` | 私有 IP 正则 | 可疑 URL 分析 | 网络请求安全 |
| `ShellGuardian` | 危险命令列表 | 命令意图分析 | Shell 执行安全 |
| `SecretEgressGuardian` | 密钥模式匹配 | 语义检查 | 防数据泄露 |

**双阶段设计**：硬规则（确定性）→ LLM 检查（语义）。LLM 检查只在配置了 LLM adapter 时启用。

#### PolicyEngine (`governance/policy.py`)

策略引擎使用**策略模式**（Strategy Pattern）：

```python
class PolicyEngine:
    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        for strategy in self._strategies:
            decision = strategy.evaluate(request)
            if decision is not None:
                return decision
        return PolicyDecision(decision="deny", reason="No matching policy")  # 默认拒绝

# 内置策略策略
class InteractiveFilePolicy(PolicyStrategy):
    # 交互式文件操作规则
class ShellPolicy(PolicyStrategy):
    # Shell 执行规则
class NetworkPolicy(PolicyStrategy):
    # 网络访问规则
class BackgroundPolicy(PolicyStrategy):
    # 后台操作规则
```

**策略规则格式**：
```python
PolicyRule(actor="*", operation="write", context="interactive",
           capability="*", resource="workspace", decision="require_approval")
```

所有字段支持通配符 `*`，按 "最精确匹配优先" 排序。

#### 沙箱路径隔离 (`capability/tools.py`)

```python
_SANDBOX_ROOT: Path | None = None  # 全局沙箱根

def get_sandbox_root() -> Path:
    # 优先级：显式设置 > COGITO_WORKSPACE_ROOT 环境变量 > ./workspace

def _resolve_safe_path(requested: str) -> Path | None:
    resolved = Path(requested).resolve()
    root = get_sandbox_root()
    if not str(resolved).startswith(str(root)):
        return None  # 阻止路径逃逸
    return resolved
```

### 2.5 横向对比：安全架构设计哲学

| 维度 | akashic-agent | hermes-agent | QwenPaw | Cogito-Agent |
|------|---------------|-------------|---------|-------------|
| **核心理念** | 插件式安全 Hook | OS 级隔离唯一可信 | 引擎+等级+审批 | 治理层全链路覆盖 |
| **检查点** | ToolHook pre-hook | 多处分散 (注册/执行/结果) | _acting() 集中拦截 | Executor 统一流水线 |
| **确定性检查** | shlex 解析 + 模式匹配 | 路径/URL/模式/二进制扫描 | 3 个具体 Guardian | 4 个 Guardian (硬规则) |
| **语义检查** | 无 | 无 | 无（仅模式匹配） | LLM Guard（可选） |
| **审批流** | 无（工具级别可达） | write_approval.py | ApprovalService + 多渠道 UI | ApprovalService + 策略引擎 |
| **审计/追踪** | HookTrace | middleware_trace | Langfuse 追踪 | AuditPort + TracePort |
| **失败模式** | deny（由 Hook 返回） | fail_open / warn / block / halt | 根据 ExecutionLevel 决策 | deny / require_approval（默认拒绝） |
| **循环防护** | ToolLoopGuard 插件 | ToolCallGuardrailController | 无专门机制 | 无专门机制 |
| **Shell 加固** | Safety 插件 + Restore 插件 | Tirith + ShellHooks + Evasion检测 | ShellEvasionGuardian | ShellGuardian |
| **第三方扫描** | 无 | Tirith 二进制 | SkillScanner | 无 |

---

## 三、MCP 设计与集成

### 3.1 akashic-agent

#### 架构

```
McpClient              → 远端通信层（stdio 子进程 + JSON-RPC）
McpToolWrapper         → 适配器层（MCP 工具 → 本地 Tool）
McpServerRegistry      → 生命周期管理 + 持久化
McpAddTool / Remove / List → Agent 可用工具（mcp_add 等）
```

#### McpClient (`agent/mcp/client.py`)

最纯粹的 MCP stdio client 实现：

```python
class McpClient:
    async def connect(self) -> list[McpToolInfo]:
        # 1. asyncio.create_subprocess_exec 启动子进程
        # 2. 发送 initialize 握手（协议版本 2024-11-05）
        # 3. 发送 notifications/initialized
        # 4. tools/list 获取工具列表
        # 5. 返回 McpToolInfo 列表

    async def call(self, tool_name, arguments) -> str:
        # 1. 构建 tools/call JSON-RPC 请求
        # 2. 发送 + 等待响应
        # 3. 解析 content 块（支持 text 多块拼接）

    async def disconnect(self):
        # terminate → 5s 超时 → kill
```

**关键设计**：
- 自动推断 cwd：从 command 中第一个绝对路径文件取其父目录
- `_drain_stderr()` 后台任务读取子进程 stderr，防止缓冲区阻塞
- 超时设计：连接超时 8s、调用超时可配（默认 30s）
- 阈值：`_STREAM_LIMIT = 4MB` 防止大响应触发 StreamReader 行限制

#### McpToolWrapper (`agent/mcp/tool.py`)

**适配器模式**：将 MCP 远端工具包装为本地 `Tool`：

```python
class McpToolWrapper(Tool):
    name → f"mcp_{server_name}__{tool_name}"  # 命名空间隔离
    description → f"[MCP:{server_name}] ..."
    parameters → info.input_schema
    async execute → await client.call(real_name, kwargs)
```

#### McpServerRegistry (`agent/mcp/registry.py`)

```python
class McpServerRegistry:
    async def load_and_connect_all(self) -> None:
        # 从 mcp_servers.json 读取配置，并发重连所有 server

    async def add(self, name, command, env) -> str:
        # 连接 → 注册工具 → 持久化到 JSON

    async def remove(self, name) -> str:
        # 注销工具 → 断开连接 → 持久化
```

持久化格式（`mcp_servers.json`）：
```json
{
  "servers": {
    "calendar": {
      "command": ["python", "/path/to/server.py"],
      "env": {"KEY": "val"},
      "cwd": null
    }
  }
}
```

#### 管理工具

Agent 可通过三个内建工具动态管理 MCP：

| 工具 | 功能 | 参数 |
|------|------|------|
| `mcp_add` | 连接新 MCP server | name, command, (env) |
| `mcp_remove` | 注销 MCP server | name |
| `mcp_list` | 列出所有 server 及工具 | 无 |

这使得 Agent **在运行时具有自主管理 MCP 连接的能力**。

---

### 3.2 hermes-agent

#### 架构

hermes-agent 的 MCP 设计最为成熟——支持四种传输方式、自动重连、采样、并发标记：

```
tools/mcp_tool.py (207KB)  → MCP client 完整实现
  ├─ Stdio 传输 (command + args)
  ├─ Streamable HTTP (url)
  ├─ SSE 传输 (transport: sse)
  ├─ 自动重连 (指数退避，最多 5 次)
  ├─ 采样支持 (server-initiated LLM requests)
  └─ 并发工具调用标记

mcp_serve.py (32KB)  → 将自己作为 MCP server 暴露
  └─ 暴露 10 个工具：conversations_list, messages_send, ...
```

#### MCP Client (`tools/mcp_tool.py`)

**专有事件循环架构**：

```python
# 专用后台线程 + asyncio 事件循环
_mcp_loop: asyncio.AbstractEventLoop | None = None
_mcp_thread: threading.Thread | None = None

# 工具调用通过 run_coroutine_threadsafe 调度到后台线程
future = asyncio.run_coroutine_threadsafe(coro, _mcp_loop)
result = future.result(timeout=timeout)

# 线程安全：所有共享状态受 _lock 保护
_servers: dict[str, Any] = {}
_lock = threading.Lock()
```

**环境变量安全过滤**：

```python
def _filter_env(server_name: str, env: dict) -> dict:
    # 从 os.environ 中筛选安全的 env 传递给子进程
    # 过滤 secret 子串（KEY/TOKEN/SECRET/PASSWORD）
    # 仅允许 PATH/HOME/LC_/LANG 等安全前缀
    # 剔除 _SECRET_KEYWORDS = {"KEY", "TOKEN", "SECRET", "PASSWORD", ...}
```

**stderr 重定向**：所有 MCP 子进程的 stderr 统一写入 `~/.hermes/logs/mcp-stderr.log`，避免污染 TUI 渲染。

**支持协议版本**：`2025-03-26`（Streamable HTTP）、`2024-11-05`（标准）

#### 配置方式 (`config.yaml`)：

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    env: {}
    timeout: 120
    connect_timeout: 60
    keepalive_interval: 10
    supports_parallel_tool_calls: true
  remote_api:
    url: "https://my-server.example.com/mcp"
    headers:
      Authorization: "Bearer sk-..."
    transport: streamable-http  # 或 sse
  searxng:
    url: "http://localhost:8000/sse"
    transport: sse
```

#### MCP Serve (`mcp_serve.py`)

hermes-agent 可以**作为 MCP server 被其他 MCP 客户端调用**：

```python
# 使用 FastMCP 框架暴露 Hermes 功能
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("hermes")

@mcp.tool()
async def conversations_list() -> str:
    # 列出所有会话
@mcp.tool()
async def messages_read(conversation_id: str) -> str:
    # 读取消息历史
@mcp.tool()
async def messages_send(conversation_id: str, message: str) -> str:
    # 发送消息
@mcp.tool()
async def permissions_list_open() -> str:
    # 列出待审批请求
```

这使得 hermes-agent 既可以消费 MCP 服务，也可以被 MCP 客户端消费（双向 MCP）。

---

### 3.3 QwenPaw

#### 架构

```
app/mcp/manager.py          → 热重载 MCP 客户端管理器
app/mcp/stateful_client.py  → 状态化客户端（修复 AgentScope 的跨任务泄露 bug）
app/mcp/watcher.py          → 配置文件热监听器
```

#### StatefulClient (`app/mcp/stateful_client.py`)

QwenPaw 解决了 AgentScope MCP 客户端的一个**关键 bug**——跨任务生命周期问题：

```
问题：AgentScope 的 StatefulClientBase 在 uvicorn 中，
connect() 在 task A 进入 AsyncExitStack，
close() 在 task B 退出 AsyncExitStack，
anyio.CancelScope 要求 enter/exit 在同一 task → 错误被静默忽略

解决：在专用后台任务中运行完整的 context manager 生命周期，
通过事件信号控制 reload/stop
```

```python
class HttpStatefulClient(HttpStatefulClient):
    # 基于 mcp.client.streamable_http
    pass

class StdIOStatefulClient(StdIOStatefulClient):
    # 基于 mcp.client.stdio
    pass
```

**工具名消毒**：MCP 工具名可能包含 `.`/`/`/`:`，需要消毒以符合 OpenAI API 规范：

```python
_TOOL_NAME_ALLOWED = re.compile(r"^[a-zA-Z0-9_-]+$")
_TOOL_NAME_REPLACE = re.compile(r"[^a-zA-Z0-9_-]")

def _sanitize_tool_name(raw: str, taken: set[str]) -> str:
    # 将非法字符替换为 _，冲突时追加 _2/_3/...
```

#### MCPClientManager (`app/mcp/manager.py`)

```python
class MCPClientManager:
    def init_from_config(self, config, timeout=60.0) → None:
        # 从配置初始化所有 MCP 客户端

    def init_from_config_background(self, config, timeout=10.0) → None:
        # 后台初始化，不阻塞应用启动

    async def replace_clients(self, config) → None:
        # 运行时热替换——先初始化新 client，成功后关闭旧的
        # 用于配置文件热重载场景

    async def shutdown(self) → None:
        # 优雅关闭所有客户端
```

**热重载机制**：`watcher.py` 监听配置文件变更 → 触发 `replace_clients()` → 新客户端连接成功后替换旧客户端。

---

### 3.4 Cogito-Agent

#### 架构

Cogito-Agent 的 MCP 设计是最注重**安全治理**的：

```
mcp/client.py     → MCPClient (JSON-RPC 通信层)
mcp/server.py     → MCPServerConfig (Pydantic 配置模型)
mcp/manager.py    → MCPServerManager (生命周期 + 能力注册)
mcp/trust.py      → MCPTrustStore (信任/授权存储)
application/mcp.py → MCPApplicationService (应用层服务)
```

#### MCPTrustStore (`mcp/trust.py`)

Cogito-Agent 独有的一层——**MCP 信任管理**：

```python
class MCPTrustStore:
    def stage_server(self, config: MCPServerConfig) -> str:
        # 将 server 信息写入数据库，状态设为 "pending"
        # 计算 config_hash 供后续变更检测
        # env 值在持久化时替换为 [REDACTED]
        return "pending" | "trusted"

    def trust_server(self, name: str) -> bool:
        # 将 server 状态更新为 "trusted" → 允许连接

    def grant_tool(self, server_name, tool_name, *, schema_hash,
                   allowed_sources, requires_approval) -> bool:
        # 授权某个工具，记录 schema_hash 用于变更检测
        # 指定允许的来源（interactive/scheduler 等）和是否需要审批

    def revoke_tool(self, server_name, tool_name) -> bool:
        # 撤销工具授权
```

**关键流程**：
1. `add_server()` → 写入 `mcp_servers` 表，状态 "pending"
2. 用户（或自动化）调用 `trust_server()` → 状态 "trusted"
3. 连接 server → 获取工具列表 → 写入 `mcp_tool_grants` 表
4. 对每个工具：检查 schema_hash 是否匹配已授权版本 → 匹配才注册为可用能力

#### MCPServerManager (`mcp/manager.py`)

```python
class MCPServerManager:
    def add_server(self, config: MCPServerConfig) -> None:
        # 1. 检查信任状态：未信任 → 暂存 pending
        # 2. 已信任 → _connect_server()

    def _connect_server(self, config) -> None:
        # 1. 创建 MCPClient
        # 2. 获取工具列表
        # 3. 对每个工具：检查 grant → 检查 schema_hash → 注册为 Capability

    def _register_tool(self, config, tool) -> None:
        # 创建 CapabilityManifest
        #   name = f"mcp_{config.name}_{tool_name}"
        #   risk_level = high
        #   allowed_contexts = ["interactive"]  # 或从 grant 读取
        #   approval_required = True             # 或从 grant 读取
        # 注册到 CapabilityRegistry
```

**工具名映射**：`mcp_{server_name}_{tool_name}` 格式，避免与内建工具冲突。

#### MCPApplicationService (`application/mcp.py`)

应用层服务，提供面向用例的 API：

```python
class MCPApplicationService:
    def add(self, config: MCPServerConfig, *, name, command, env) → str
    def remove(self, name: str) → str
    def list_servers(self) → list[dict]
    def trust_server(self, name: str) → bool
    def grant_tool(self, server_name, tool_name, *, schema_hash, ...) → bool
    def revoke_tool(self, server_name, tool_name) → bool
    def list_recent_calls(self, server_name, limit=20) → list[dict]
```

**审计集成**：所有 MCP 管理操作通过 `MCPAuditPort` 记录。

### 3.5 横向对比：MCP 设计考量

| 维度 | akashic-agent | hermes-agent | QwenPaw | Cogito-Agent |
|------|---------------|-------------|---------|-------------|
| **传输协议** | stdio 子进程 | stdio + Streamable HTTP + SSE | stdio + HTTP | stdio 子进程 |
| **生命管理** | McpServerRegistry | 后台线程 + 专用事件循环 | MCPClientManager + 热重载 | MCPServerManager |
| **协议版本** | 2024-11-05 | 2024-11-05 + 2025-03-26 | AgentScope 封装 | 2024-11-05 |
| **持久化** | mcp_servers.json | config.yaml + 日志文件 | 配置文件 + 管理器 | SQLite (mcp_servers 表 + tool_grants) |
| **工具命名** | mcp_{name}__{tool} | 原始 MCP 名（可配置） | 消毒后命名 | mcp_{name}_{tool} |
| **信任机制** | 无（直接连接） | 无（配置即信任） | 无（配置即信任） | MCPTrustStore (pending→trusted) |
| **工具授权** | 无（全注册） | 无（全注册） | 无（全注册） | 逐工具授权 (schema_hash 校验) |
| **并发调用** | 顺序 | `supports_parallel_tool_calls` 标记 | 顺序 | 顺序 |
| **安全措施** | 无 | 环境变量过滤 + stderr 隔离 | 工具名消毒 + 跨任务修复 | 权限管理 + 审批 + 审计 |
| **反向 MCP** | 无 | mcp_serve.py（作为 MCP server） | 无 | 无 |
| **重连机制** | 无（启动时一次连接） | 指数退避（最多 5 次） | 无（配置热重载） | 无（需重新添加） |

---

## 四、综合对比表

### 工具调用

| 维度 | akashic-agent | hermes-agent | QwenPaw | Cogito-Agent |
|------|---------------|-------------|---------|-------------|
| **架构风格** | 插件化流水线 | 过程式大循环 | 继承式重写 | 六边形架构 |
| **注册方式** | ToolRegistry + ToolsetProvider | 自发现 + registry.register() | Toolkit.register() | CapabilityRegistry |
| **Schema 格式** | OpenAI function calling | OpenAI（兼容 Anthropic） | AgentScope 自动 | JSON Schema + Manifest |
| **执行引擎** | ToolExecutor + Hook 链 | 顺序/并发 ThreadPool | ReAct _acting() + Mixin | GovernedCapabilityExecutor |
| **工具钩子** | ToolHook pre/post 链 | tool_guardrails 状态机 | ToolGuardMixin._acting() | Guardian.inspect() |
| **延迟加载** | tool_search + deferred | 无 | 无 | 无 |
| **元数据** | ToolMeta (risk/always_on) | ToolEntry (toolset) | 无（隐式） | CapabilityManifest (完整声明) |
| **扩展性** | ToolsetProvider Protocol | 自发现 + 外部 provider | 继承重写 + Mixin | Ports/Adapters + DI |

### 沙箱/安全

| 维度 | akashic-agent | hermes-agent | QwenPaw | Cogito-Agent |
|------|---------------|-------------|---------|-------------|
| **核心理念** | 插件式 Hook | OS 级隔离 | 分级引擎 | 全链路治理 |
| **检查点** | ToolHook pre-hook | 多处分散 | _acting() 集中 | Executor 统一流水线 |
| **硬规则** | 模式匹配 + shlex | 多种 + Tirith 二进制 | 3 个 Guardian | 4 个 Guardian |
| **语义检查** | 无 | 无 | 无 | LLM Guard (可选) |
| **审批流** | 无 | write_approval | 多渠道 UI | PolicyEngine + ApprovalService |
| **循环防护** | ToolLoopGuard | ToolCallGuardrailController | 无 | 无 |
| **Shell 加固** | Safety + Restore | Tirith + ShellHooks + Evasion | ShellEvasionGuardian | ShellGuardian |
| **路径安全** | 无专门 | file_safety + path_security | FilePathToolGuardian | PathGuardian + 沙箱根 |
| **网络安全** | 无专门 | url_safety | 无专门 | NetworkGuardian |
| **审计/追踪** | HookTrace | middleware_trace | Langfuse | AuditPort + TracePort |
| **失败默认** | allow（无匹配时） | fail_open | 根据等级 | deny（拒绝） |

### MCP

| 维度 | akashic-agent | hermes-agent | QwenPaw | Cogito-Agent |
|------|---------------|-------------|---------|-------------|
| **传输** | stdio | stdio/HTTP/SSE | stdio/HTTP | stdio |
| **协议版本** | 2024-11-05 | 2024-11-05 + 2025-03-26 | AgentScope 封装 | 2024-11-05 |
| **工具命名** | mcp_{name}__{tool} | 原始名 | 消毒后 | mcp_{name}_{tool} |
| **信任机制** | 无 | 无 | 无 | MCPTrustStore |
| **工具授权** | 无 | 无 | 无 | 逐工具 + schema_hash |
| **持久化** | JSON 文件 | config.yaml | 配置文件 | SQLite |
| **反向 MCP** | 无 | 支持 (mcp_serve.py) | 无 | 无 |
| **并发** | 顺序 | 可选标记 | 顺序 | 顺序 |
| **热重载** | 无 | 无（需重启） | 支持 | 无（需重新添加） |

---

## 五、总结：各项目设计哲学与最佳实践

### akashic-agent：插件化流水线

**核心哲学**："一切皆 Phase，插件在 Gate/Tap 介入"

- **工具调用**：标准的注册中心 + 执行器 + Hook 链模式。`ToolRegistry` 的延迟加载和搜索机制最有特色，解决了大型工具集下的 prompt 体积问题。
- **安全**：以插件形式实现——`shell_safety`、`shell_restore`、`tool_loop_guard` 都是独立插件，通过 `@on_tool_pre` 装饰器挂接到 ToolHook 链。插件式安全的最大优势是**可组合**：用户可以按需启用/禁用安全插件。
- **MCP**：轻量、干净的 stdio 实现。`McpToolWrapper` 适配器模式清晰简洁。Agent 可通过 `mcp_add`/`mcp_remove` 工具自主管理 MCP 连接。

**最佳实践**：
- 使用 `ToolsetProvider` Protocol 实现可插拔的工具集注册
- 利用 `ToolHook` 链实现安全逻辑的模块化组装
- 延迟加载（`tool_search`）在工具数量庞大时效果显著

### hermes-agent：过程式大循环 + OS 级隔离

**核心哲学**："唯一的安全边界是操作系统"

- **工具调用**：过程式大循环中的工具分派。`model_tools.py` 和 `conversation_loop.py` 合起来 ~330KB，覆盖了从 LLM 调用、工具分派、错误处理、重试回退到记忆同步的完整流程。
- **安全**：最务实的架构——承认进程内检查都是启发式的，真正的安全依赖 OS 级隔离。同时提供了最丰富的进程内检查：文件安全、URL 安全、威胁模式扫描、Tirith 二进制扫描、Schema 清洗等。`ToolCallGuardrailController` 是纯函数式设计，可独立测试。
- **MCP**：功能最丰富的 MCP 实现——支持三种传输方式、自动重连、采样、并发标记。`mcp_serve.py` 使其能反向作为 MCP Server，是唯一支持双向 MCP 的项目。但 207KB 的 `mcp_tool.py` 过于臃肿。

**最佳实践**：
- 明确区分安全边界（OS 级）和启发式检查（进程内）
- `ToolCallGuardrailController` 的纯函数式设计易于测试和推理
- 环境变量过滤和 stderr 重定向是 MCP stdio 子进程的实用安全措施

### QwenPaw：继承式重写 + 分级安全引擎

**核心哲学**："继承基类，重写关键方法"

- **工具调用**：通过 AgentScope 的 ReAct 框架，以继承 + Mixin 链扩展。CodingModeMixin 和 ToolGuardMixin 通过 `super()._acting()` 调用链组合。
- **安全**：最正式化的安全引擎——`ToolGuardEngine` + `ToolExecutionLevel` 四等级 + 多渠道审批 UI。`ShellEvasionGuardian` 的引号状态机跟踪器是 shell 安全领域的精细实现。`SkillScanner` 是唯一有独立技能扫描子系统的项目。
- **MCP**：解决了 AgentScope 框架的跨任务生命周期 bug，支持运行时热重载。工具名消毒是独特需求（支持中文等 Unicode 工具名）。

**最佳实践**：
- MCP client 的当前类管理器生命周期管理需注意跨任务问题（AsyncExitStack + CancelScope）
- 多渠道审批 UI 是 MCP + 安全审批的优秀模式
- 工具名消毒对于多语言/特殊字符 MCP 工具名是必要的

### Cogito-Agent：六边形架构 + 全链路治理

**核心哲学**："治理与执行合一，安全贯穿全链路"

- **工具调用**：最符合 DDD 的设计——`CapabilityRegistry` + `CapabilityManifest` + `GovernedCapabilityExecutor`。每个能力有完整的声明元数据，治理层据此决策。
- **安全**：架构化程度最高——三阶段流水线（策略评估 → 防护者检查 → 审批/审计/追踪）。`Guardian` 基类的模板方法设计（硬规则 + LLM 检查）是创新点。`PolicyEngine` 的策略模式比硬编码规则矩阵更灵活。
- **MCP**：唯一带有完整信任管理（`MCPTrustStore`）的项目。逐工具授权 + schema_hash 校验 + SQLite 持久化 + 审计日志，是最安全审慎的 MCP 管理方案。

**最佳实践**：
- `CapabilityManifest` 作为能力的完整元数据声明，使得治理层可以基于声明做决策
- Guardian 的双阶段设计（硬规则 + LLM 语义）兼顾效率和深度
- MCP 信任管理是生产环境的必备品——先暂存、后授权、再连接
- "默认拒绝"（fail-closed）的安全姿态是最保守但最安全的

---

### 跨项目模式总结

1. **工具注册中心模式**：所有项目都有一个中央注册中心（`ToolRegistry` / `registry.py` / `CapabilityRegistry`），管理工具的声明周期、Schema 生成和执行调度。

2. **安全 Hook 链模式**：所有项目都在工具执行前/后插入安全检查点，形式包括：
   - akashic-agent：ToolHook pre/post 事件
   - hermes-agent：tool_guardrails + 分散的检查点
   - QwenPaw：ToolGuardMixin._acting() + ToolGuardEngine
   - Cogito-Agent：GovernedCapabilityExecutor + Guardian 链

3. **MCP 适配器模式**：所有项目都将 MCP 工具通过适配器包装为本地工具，隐藏 JSON-RPC 通信细节：
   - akashic-agent：`McpToolWrapper(Tool)`
   - hermes-agent：`mcp_client` 直接注册到 registry
   - QwenPaw：`MCPToolFunction` (AgentScope)
   - Cogito-Agent：`mcp_{name}_{tool}` → CapabilityRegistry

4. **安全深度递进**：从检查强度看，`akashic < QwenPaw < hermes < Cogito` 大致呈递进关系——从插件级检查到 OS 级隔离，再到全链路治理。

---

> 本文档基于源码分析，涵盖了四个 AI Agent 项目在工具调用、沙箱安全、MCP 集成三个维度的设计原理与实现细节。
> 撰写日期：2026-06-22
