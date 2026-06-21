# Cogito-Agent 个人本地版架构改造计划

> 文档状态：Completed（个人本地版必做范围）  
> 适用范围：单用户、单机、本地优先、非公开服务  
> 建议目标版本：v0.17.0-dev ～ v0.19.0-dev  
> 编写日期：2026-06-20  
> 最后更新：2026-06-21

## 0. 实施状态

当前状态：**个人本地版必做架构改造与质量门禁均已完成，文档标记为 Completed**。

截至 2026-06-21 已落地：

- 统一验证脚本和首批架构边界测试。
- ContextEngine 通过 `ContextTraceSink` 持久化，不再接收 `Any db`。
- Chat 的 CLI、API、Console 调用统一经过 `ChatApplicationService`。
- 新增 `GovernedCapabilityExecutor`；Runtime、Scheduler、Skill 不再直接调用 Registry。
- 新增 Path、Shell、Network、Secret Egress Guardian。
- MCP Server 待信任、工具 schema hash 授权、最小 subprocess 环境变量。
- 新增 `runs/run_events/run_outputs` 和 Scheduler 原子 claim、lease 恢复。
- 新增 Autonomy alert/content/context Channel、TTL、Evidence 和 ACK 接口。
- 新增 Prompt stable/context/volatile 哈希及 token 统计。
- 大 ToolResult 可卸载为 Artifact。
- Scheduler/Skill/Webhook 自动运行默认不生成普通记忆候选。
- RuntimeKernel 已删除 Database、PolicyEngine 和 CapabilityRegistry 的具体构造依赖，
  Policy、Capability Catalog、Persistence、Trace、Audit 和 Executor 均由 Runtime Ports 注入。
- Drift、Skill approval resume 和 Scheduler 已统一使用 Durable Run；Skill 失败重试复用原 Run。
- Console 已增加统一 Runs、MCP Grant/Revoke 和受限 Backup/Restore 页面。
- API/Console mutation 已迁移到 Application Service，并增加架构守卫测试。
- Decision、Notification、Outbox 在同一事务提交；ACK 使用 token hash 持久化状态，
  失败错误经过脱敏并写入 Audit。
- 新增 `cogito-console` 本地入口，默认绑定配置中的持久化 SQLite 数据库。
- Audit、Trace 和结构化/文本日志统一执行最终输出脱敏。

仍未实施但不阻塞个人本地版完成定义的可选项：

- Plugin 和 Task 属于可选阶段，尚未实施。
- Playwright 未安装，因此条件式浏览器 smoke 保持跳过；Console 路由、安全回归和实际
  Backup/Restore 本地工作流已由后端集成测试覆盖。
- Python 3.12 和跨平台发布矩阵仍属于后续发布工程，不阻塞本次个人本地验收。

最终验收结果：共收集 1709 个测试，采用完整分组运行规避宿主进程约 25 秒的硬终止限制，
结果为 **1705 passed、4 skipped**；daemon 子进程测试 4/4 通过；`ruff check src tests scripts`
和 `mypy src` 均通过；Python 3.13 无隔离构建 wheel 成功，并核对 Console 模板、静态资源、
migration 18–20 和 `cogito-console` 入口。指定 `cogito-agent` Conda 环境为 Python 3.11.15，
低于项目声明的 Python 3.12+，因此仅用于测试、Ruff 和 mypy，wheel 使用兼容的 Python 3.13.13 构建。

## 1. 文档目的

本文档用于指导 Cogito-Agent 从“功能覆盖较完整的开发版本”演进为“可以由个人长期、稳定、安全地在本机使用的 Agent Runtime”。

本次改造不以 SaaS、团队协作、互联网公开部署或商业化为目标。重点是：

1. 收紧已经出现的架构边界漂移，降低继续增加功能时的维护成本。
2. 确保 Tool、Skill、MCP、Plugin 和 Autonomy 都无法绕过治理链路。
3. 保证本地后台任务在崩溃、重启和重复扫描时不会产生明显的重复执行或状态丢失。
4. 改善长期对话、工具输出和记忆整理对上下文窗口及 Prompt Cache 的影响。
5. 为本地插件、任务和受限 Subagent 留出清晰的扩展接口，但不建设插件市场和复杂多 Agent 网络。
6. 保留 Cogito-Agent 已有的本地优先、SQLite、可审计、可追踪、确定性治理优势。

本文档不是一次性重写方案。所有改造应在现有测试和功能基础上渐进完成。

---

## 2. 当前状态判断

### 2.1 完成度

按当前架构目标估算：

| 领域 | 当前完成度 | 判断 |
|---|---:|---|
| Runtime Turn Pipeline | 95% | Runtime Ports、统一 Chat Service、多轮工具和流式处理已落地 |
| Memory / Retrieval | 90% | 生命周期、混合检索、文件上下文及自动任务隔离已具备 |
| Context / Model Routing | 90% | Prompt 分层、哈希、token 统计和大型结果卸载已落地 |
| Capability / Skill / MCP | 90% | 统一执行器、Guardian、MCP trust/grant 已落地 |
| Governance / Approval | 90% | Capability 主路径统一经过治理、审批、审计和追踪 |
| Trace / Audit | 90% | Run 关联和统一最终脱敏已落地 |
| Autonomy / Scheduler | 90% | Durable Run、原子 claim、lease 恢复和事务信封已落地 |
| Console | 90% | Runs、MCP、Backup/Restore 和 Application Service 边界已落地 |
| Plugin / Task / Subagent | 40% | Plugin/Task 仍为可选项；受限 Subagent 仅保留基础能力 |

按个人本地版的必做范围计算，**实现完成度与已验证完成度均为 100%**。
Plugin、Task、外部 Channel、Playwright 浏览器自动化以及跨平台发布矩阵是可选项，
不纳入本次必做完成度。

### 2.2 当前最值得保留的设计

- SQLite 本地持久化和 migration 体系。
- Policy、Approval、Audit、Trace 的结构化设计。
- Memory Candidate、版本和来源追踪。
- Capability Manifest 与 ToolResult。
- 确定性的 NotificationGate，而不是完全由 LLM 决策。
- Artifact、Workspace File 和 Console 已形成的本地工作流。
- Drift、Skill、Outbox 已经具备的最小闭环。

### 2.3 当前主要问题

#### A. Runtime 与具体实现耦合

`RuntimeKernel` 仍直接认识部分数据库、Repository、Registry 和具体服务。这与架构文档中“runtime 只依赖抽象接口”的要求不一致。

影响：

- 测试需要组装过多具体依赖。
- Console、CLI、API 容易形成不同调用路径。
- 新增 Tool、MCP、Plugin 时容易绕过 Governance。
- Bootstrap 会逐渐变成难以维护的全局服务定位器。

#### B. Capability 执行没有统一窄腰

当前 Registry 更接近“注册并调用能力”，治理检查主要由上层调用者保证。只要未来新增一个调用入口，就可能遗漏 Policy、Approval、Audit 或 Trace。

#### C. MCP 默认信任过高

MCP 工具来自外部进程或远程 Server。即使是个人使用，也可能读取文件、执行命令、访问网络或泄漏 Secret。个人本机环境实际上比隔离服务器更需要默认拒绝。

#### D. 后台任务缺乏完整恢复语义

Scheduler、Drift、Skill Run 和 Subagent Run 尚未共享统一的持久化运行模型。扫描任务后直接执行，可能在进程重启、超时或重复扫描时产生重复运行或状态不一致。

#### E. Prompt 和 Context 的稳定性不足

长期运行时，频繁变化的 Memory、工具大结果和运行状态可能进入 Prompt，造成：

- Token 不稳定增长。
- Prompt Cache 命中率下降。
- 历史上下文中保留大量低价值 ToolResult。
- 自动任务产生的内容污染正常聊天记忆。

#### F. Plugin、Task、Subagent 没有稳定产品边界

这些能力已经出现雏形，但还缺少权限、持久化、生命周期和失败恢复约束。继续横向扩展会增加维护负担。

---

## 3. 个人本地版的范围约束

### 3.1 必须支持

- 单用户、单机运行。
- CLI、Console 和本地 API 使用同一套应用服务。
- SQLite 作为唯一主数据库。
- 本地模型或 OpenAI-compatible Provider。
- 本地 Tool、Skill 和显式配置的 MCP Server。
- 可解释的 Policy、Approval、Audit 和 Trace。
- 进程崩溃后的任务恢复。
- 本地备份和恢复。
- Console 默认只监听 loopback。

### 3.2 可以支持，但不是近期必需

- Telegram 或飞书中的一个个人 Channel。
- 本地目录插件。
- 一次性、受限、可持久化的 Subagent。
- Git worktree 隔离的代码任务。
- 可选的 LLM 主动性相关度评分。

### 3.3 明确不做

- 多租户、组织、团队权限和 RBAC。
- OAuth、SSO、公开注册系统。
- Kubernetes、分布式队列、分布式锁和多节点调度。
- 云数据库、云同步和跨设备一致性。
- 高可用和零停机升级。
- 公共插件市场、在线自动安装任意插件。
- Agent 间自由组网、无限递归委派。
- 默认开放到公网的 Webhook、Console 或 API。
- 为了抽象而引入微服务或消息中间件。

---

## 4. 改造原则

### 4.1 不重写

使用适配器和门面逐步包住现有实现，再迁移调用方。每个阶段必须保持测试可运行，不能先删除旧路径再补新路径。

### 4.2 建立一个统一执行窄腰

所有有副作用的能力必须经过同一个执行入口：

```text
CLI / API / Console / Scheduler / Drift / Subagent
                         │
                         ▼
              Application Service
                         │
                         ▼
            GovernedCapabilityExecutor
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       Policy         Approval       Guardians
          └──────────────┼──────────────┘
                         ▼
                     Invocation
                         │
                         ▼
              Tool / Skill / MCP / Plugin
                         │
                         ▼
                 Audit + Trace + Result
```

Registry 只负责发现、解析和返回 Capability Descriptor，不负责绕过治理直接执行。

### 4.3 单机不等于不需要可靠性

不建设分布式共识，但要处理：

- 程序被关闭。
- 机器休眠或重启。
- SQLite 写入中断。
- 同一任务被重复扫描。
- 工具运行超时。
- 用户重复点击执行按钮。

SQLite 条件更新、事务、PID lock、lease 和幂等键足以覆盖个人使用场景。

### 4.4 外部能力默认不可信

本地 Tool 可以按内置清单获得默认权限；MCP、Plugin、Shell、网络访问必须默认拒绝或要求显式授权。

### 4.5 LLM 不能覆盖确定性安全结论

LLM 可以进行相关度排序、摘要和建议，但不能覆盖：

- Policy deny。
- 文件沙箱限制。
- Secret Egress 拒绝。
- 静默时间。
- 配额限制。
- 去重结果。
- 用户明确禁用的能力。

---

## 5. 目标模块结构

建议在现有包结构上增加 `application`、`execution` 和 `plugins`，不拆微服务：

```text
src/cogito_agent/
  application/
    chat_service.py
    memory_service.py
    approval_service.py
    autonomy_service.py
    task_service.py
    run_service.py
    ports.py

  runtime/
    kernel.py
    ports.py
    events.py
    state.py

  execution/
    executor.py
    request.py
    result.py
    guardians/
      base.py
      path.py
      shell.py
      network.py
      secret_egress.py

  capability/
    descriptor.py
    registry.py
    manifests.py

  plugins/
    manifest.py
    registry.py
    validator.py
    runtime.py

  runs/
    models.py
    repository.py
    coordinator.py

  channels/
    base.py
    cli.py
    console.py
    optional_telegram.py
```

说明：

- 不要求一次性移动所有现有文件。
- `application` 负责用例，不能包含 HTML、FastAPI Request 或 CLI 输出。
- `runtime` 负责 Turn 状态机，只依赖 Protocol。
- `execution` 是所有副作用能力的唯一执行入口。
- `runs` 统一后台运行、Skill、Drift、Scheduler 和 Subagent 的状态。
- `channels` 只转换输入输出，不直接访问数据库。

---

## 6. Phase 0：冻结基线与统一文档

优先级：**必须**  
建议版本：v0.17.0-dev 起点  
工作量：S

### 6.1 目标

在开始移动依赖前建立可比较的基线，避免架构改造与功能变化混在一起。

### 6.2 工作项

1. 明确唯一当前版本号和版本来源。
2. 将完整测试、Ruff、mypy 命令写入统一验证脚本或 Make/PowerShell 入口。
3. 记录测试数量、跳过原因、Python 版本和平台。
4. 生成依赖边界清单：
   - runtime 禁止依赖的包。
   - api/console 禁止直接访问的模块。
   - capability 必须经过的执行入口。
5. 增加架构依赖测试，可使用 AST 检查，不要求增加重量级依赖。
6. 清理 v0.16 同名目标或状态描述冲突。

### 6.3 建议测试

- `test_runtime_does_not_import_concrete_storage`
- `test_runtime_does_not_import_provider_implementations`
- `test_console_mutations_use_application_services`
- `test_version_is_consistent`

### 6.4 验收标准

- 一条命令可执行项目完整质量检查。
- 文档只声明一个当前版本和一个验证基线。
- 新的架构边界测试先以已知例外列表运行，后续阶段逐项清零。

---

## 7. Phase 1：Runtime Ports 与 Application Services

优先级：**必须**  
建议版本：v0.17.0-dev  
工作量：L

### 7.1 目标

让 RuntimeKernel 只负责 Turn 生命周期，让 CLI、API 和 Console 通过同一套应用服务进入系统。

### 7.2 Runtime Ports

建议定义最小 Protocol：

```python
class SessionPort(Protocol):
    def get_or_create(self, workspace_id: str, session_id: str) -> Session: ...
    def append_message(self, message: Message) -> None: ...
    def list_messages(self, session_id: str, limit: int) -> list[Message]: ...

class ContextPort(Protocol):
    def build(self, request: ContextRequest) -> ContextBundle: ...

class ModelPort(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...
    def stream(self, request: ModelRequest) -> Iterator[ModelEvent]: ...

class CapabilityExecutorPort(Protocol):
    def execute(self, request: CapabilityExecutionRequest) -> CapabilityExecutionResult: ...

class TracePort(Protocol):
    def start_span(self, request: SpanRequest) -> SpanHandle: ...

class MemoryCandidatePort(Protocol):
    def extract_and_store(self, turn: CompletedTurn) -> list[str]: ...
```

Protocol 应围绕 Runtime 的需要设计，不能只是给 Repository 原样套一层接口。

### 7.3 Application Services

首批建议建立：

- `ChatApplicationService`
- `SessionApplicationService`
- `MemoryApplicationService`
- `ApprovalApplicationService`
- `AutonomyApplicationService`
- `BackupApplicationService`

职责示例：

```text
Console Route
  -> 校验 HTTP 表单
  -> 调用 MemoryApplicationService.accept_candidate()
  -> Service 开事务、调用 Repository、写 Audit
  -> Route 将结果渲染为 HTML
```

Route 不应自行拼装 Repository、执行 SQL 或决定审计字段。

### 7.4 迁移顺序

1. 先给现有 Repository 和 Service 编写 Adapter。
2. RuntimeKernel 构造函数改为接收 Ports。
3. Bootstrap 负责创建 Adapter 并注入。
4. CLI Chat 迁移到 `ChatApplicationService`。
5. API Chat 迁移。
6. Console Chat 迁移。
7. 逐页迁移 Console mutation。
8. 最后删除旧的直连调用。

### 7.5 明确不做

- 不引入全功能 DI 框架。
- 不使用运行时反射自动注入。
- 不把每个 Repository 方法包装成同名 Service 方法。
- 不把查询页面强行套进复杂 CQRS。

### 7.6 验收标准

- Runtime 不 import 具体 Database、SQLite Repository 或具体 Provider。
- Chat 的 CLI、API、Console 共享同一个用例服务。
- Console 所有写操作均由 Application Service 完成。
- Bootstrap 只负责对象装配，不包含业务判断。
- 现有行为测试不回退。

---

## 8. Phase 2：统一 Governed Capability Execution

优先级：**必须**  
建议版本：v0.17.0-dev  
工作量：L

### 8.1 目标

确保 Tool、Skill、MCP、Plugin、Autonomy 和 Subagent 使用相同的治理、审批、审计和追踪流程。

### 8.2 执行请求模型

```python
class CapabilityExecutionRequest(BaseModel):
    capability_id: str
    arguments: dict[str, Any]
    actor: ActorContext
    source: ExecutionSource
    workspace_id: str
    session_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    grants: set[str] = set()
    budget: ExecutionBudget
```

`ExecutionSource` 至少包括：

- user
- console
- api
- scheduler
- drift
- skill
- subagent
- system

### 8.3 标准执行顺序

1. 从 Registry 解析 Descriptor。
2. 校验参数 JSON Schema。
3. 计算静态风险等级。
4. 执行 Guardian 检查。
5. PolicyEngine evaluate。
6. 如果需要，创建或恢复 Approval。
7. 检查预算、超时和幂等键。
8. 开启 Trace Span。
9. 调用 Capability Adapter。
10. 对 ToolResult 做 Secret Redaction。
11. 保存 Audit、Trace 和 Run Event。
12. 返回统一结果。

### 8.4 Guardian 链

个人版首批只实现高价值 Guardian：

#### PathGuardian

- 拒绝 workspace 外路径。
- 拒绝 symlink escape。
- 区分 read、write、delete。
- 删除和覆盖默认需要审批。

#### ShellGuardian

- 识别管道、重定向、子命令和编码绕过。
- 拒绝已知破坏性命令。
- workspace 外写入要求审批。
- 后台 Autonomy 默认禁止 Shell。

#### NetworkGuardian

- 阻止 loopback 绕过、link-local、metadata endpoint 和私网 SSRF。
- 允许用户显式授权的域名。
- 默认禁止外发 Secret。

#### SecretEgressGuardian

- 检查参数和请求正文中的已知 Secret pattern。
- Secret 只能注入到已授权 Provider/MCP Server。
- Audit 中只能记录 secret reference，不能记录原值。

### 8.5 Registry 改造

Registry 的公开职责限制为：

- register
- unregister
- resolve
- list_descriptors
- validate_manifest

逐步废弃或设为内部方法：

- `registry.invoke()`
- 任意不经过 Executor 的直接 handler 调用

### 8.6 验收标准

- 全仓库只有 Executor 可以调用 Capability handler。
- denied、approval-required、timeout、failure 和 success 都有统一 Trace/Audit。
- Scheduler、Drift 和 Skill 不能使用专用旁路执行 Tool。
- 新增 Capability 时无需在多个 Channel 重复接治理逻辑。

---

## 9. Phase 3：MCP 本地信任与权限模型

优先级：**必须**  
建议版本：v0.17.0-dev  
工作量：M

### 9.1 目标

允许个人安全地使用自己配置的 MCP Server，但不默认信任 Server 暴露的所有工具。

### 9.2 数据模型

建议新增：

#### `mcp_servers`

- server_id
- name
- transport
- command_or_url
- cwd
- config_hash
- trust_status: pending / trusted / blocked
- enabled
- created_at / updated_at

#### `mcp_tool_grants`

- server_id
- tool_name
- tool_schema_hash
- risk_level
- allowed_sources
- requires_approval
- allow_file_read
- allow_file_write
- allow_network
- allow_secrets
- granted_at
- revoked_at

### 9.3 行为规则

- 新 Server 首次发现：`pending`。
- 新 Tool 首次发现：不可调用。
- Tool schema 发生变化：旧授权失效。
- Server command、URL、cwd 或 env 发生变化：Server 回到 pending。
- MCP subprocess 只获得最小环境变量集合。
- Secret 必须通过显式 secret reference 注入。
- 后台来源默认不能调用未明确授权的 MCP Tool。

### 9.4 Console 最小页面

无需建设市场，只增加本地管理页面：

- Server 列表和状态。
- 工具列表、schema hash 和风险等级。
- 授权来源选择。
- 审批要求开关。
- 撤销授权。
- 最近调用和失败原因。

### 9.5 验收标准

- MCP Tool 不再统一标记为 low-risk。
- 未授权工具无法从聊天、Skill 或 Drift 调用。
- Tool schema 改变后必须重新授权。
- MCP 子进程不能自动继承全部环境变量。
- MCP 调用仍经过统一 Executor。

---

## 10. Phase 4：统一 Durable Run 与本地调度可靠性

优先级：**必须**  
建议版本：v0.18.0-dev  
工作量：L

### 10.1 目标

用一个统一 Run 模型承载 Scheduler、Drift、Skill、Maintenance 和未来 Subagent。

### 10.2 个人版简化模型

不需要独立分布式 lease 服务。建议使用一个 `runs` 主表和事件表：

#### `runs`

- run_id
- run_type: scheduled / drift / skill / maintenance / subagent
- definition_id
- parent_run_id
- workspace_id
- status: pending / claimed / running / waiting_approval / succeeded / failed / cancelled / abandoned
- priority
- idempotency_key
- scheduled_at
- claimed_by
- lease_expires_at
- heartbeat_at
- attempt_count
- max_attempts
- input_json
- result_json
- error_code
- error_message_redacted
- trace_id
- created_at / started_at / finished_at

#### `run_events`

- event_id
- run_id
- sequence
- event_type
- payload_redacted
- created_at

#### `run_outputs`

- output_id
- run_id
- output_type: artifact / inbox / memory_candidate / task_candidate
- reference_id
- created_at

### 10.3 原子 Claim

SQLite 中使用事务和条件更新：

```sql
UPDATE runs
SET status = 'claimed',
    claimed_by = :worker_id,
    lease_expires_at = :lease_expires_at
WHERE run_id = :run_id
  AND status = 'pending';
```

只有 `rowcount == 1` 的 worker 获得执行权。单机也应保留该约束，以防 daemon、Console 和手工命令同时触发。

### 10.4 恢复规则

- `claimed/running` 且 lease 过期：标记 abandoned。
- 如果 capability 具备幂等键，可重新排队。
- 非幂等写操作不自动重试，转为用户确认。
- waiting_approval 不消耗 lease，但保存 approval_id。
- 进程启动时执行一次 recovery sweep。

### 10.5 调度语义

个人版至少支持：

- once
- interval
- cron
- timezone
- pause/resume
- next_fire_at
- misfire policy: skip / fire_once
- overlap policy: skip / queue_one

不支持并行重叠执行作为默认行为。

### 10.6 Daemon

- 保留单机 PID lock。
- worker_id 使用稳定 installation_id + process id。
- 每个运行周期刷新 heartbeat。
- Windows 休眠恢复后按 misfire policy 处理，不批量补跑全部历史任务。

### 10.7 验收标准

- 同一个到期任务不会因重复 scan 运行两次。
- 运行中强制关闭进程后，重启能够发现 abandoned run。
- 可安全重试和不可安全重试有明确区别。
- Drift、Skill 和 Scheduler 在 Console 中呈现相同的状态与事件模型。

---

## 11. Phase 5：Autonomy 输入协议与通知闭环

优先级：**建议**  
建议版本：v0.18.0-dev  
工作量：M

### 11.1 目标

借鉴 Akashic 的输入分类和 ACK 语义，同时保留 Cogito 的确定性 NotificationGate。

### 11.2 统一输入 Envelope

```python
class AutonomyEnvelope(BaseModel):
    event_id: str
    source_id: str
    channel: Literal["alert", "content", "context"]
    occurred_at: datetime
    expires_at: datetime | None
    priority: PriorityLevel
    dedup_key: str
    title: str
    content: str
    evidence: list[EvidenceRef]
    ack_token: str | None
```

三类输入：

- `alert`：定时任务失败、审批超时、备份失败等高价值事件。
- `content`：新文件、记忆候选、收件箱内容等需要判断价值的输入。
- `context`：低优先级提示，仅在系统空闲和配额允许时考虑。

### 11.3 决策顺序

```text
Source Fetch
  -> Normalize + TTL
  -> Deterministic Eligibility Gate
  -> 可选 LLM Relevance Scorer
  -> NotificationGate
  -> Persist Decision + Outbox（同一事务）
  -> Delivery
  -> ACK Source
```

LLM Scorer 只能降低或排序可通知事件，不能将 deterministic deny 变为 allow。

### 11.4 ACK 规则

- push 成功：ack delivered。
- skip：ack skipped，并记录 reason。
- defer：不最终 ack，保存 next_evaluate_at。
- expired：ack expired。
- require_approval：等待审批，不重复拉取生成新 decision。

### 11.5 个人版限制

- 默认只投递到 Console Inbox。
- 每日总通知量保持较低。
- 不做复杂“能量模型”；只根据最近用户活动设置两个或三个 tick 档位。
- Drift 默认只能调用 proposal-only Skill。

### 11.6 验收标准

- Source 失败相互隔离。
- 相同 dedup_key 不会重复推送。
- Decision、Outbox 和 ACK 状态可以完整追溯。
- 禁用 LLM Scorer 后系统仍能正常工作。

---

## 12. Phase 6：Prompt、Context 与 Memory 稳定化

优先级：**建议**  
建议版本：v0.18.0-dev  
工作量：M

### 12.1 Prompt 三层模型

#### Stable Layer

长期保持字节稳定：

- Agent identity。
- 核心安全规则。
- Tool schema 的稳定排序版本。
- 用户显式长期偏好摘要。

#### Context Layer

每个 Session 或阶段变化：

- Session summary。
- 当前任务。
- 检索到的 Memory/File Context。
- 最近有效工具结果摘要。

#### Volatile Layer

每轮变化：

- 当前用户消息。
- 当前时间。
- 本轮临时状态。
- Pending approval 状态。

每层记录 hash 和 token_count，用于诊断 Prompt Cache 和上下文膨胀。

### 12.2 Tool Result Offload

规则：

- 小结果直接保留。
- 大 JSON、日志和文件内容存入 Artifact。
- Context 只保留摘要、artifact_id、来源和关键字段。
- 后续模型需要细节时，通过受治理的 artifact.read 获取。

### 12.3 Memory 分层

保留数据库作为事实来源，增加逻辑分层：

- pending：近期提取、尚未整理。
- stable：已接受、适合进入长期 Prompt。
- archived：不主动检索。
- automation：后台任务产生，默认不进入普通聊天检索。

借鉴 Akashic 的 Pending→Stable 思路，但不把 Markdown 文件作为唯一存储。

### 12.4 自动记忆隔离

- Scheduler、Heartbeat、Drift 的系统消息默认不生成用户记忆。
- Skill 输出只能生成 candidate，不能直接写 stable memory。
- Subagent 结果由父 Run 或用户确认后进入 Memory。

### 12.5 Context Lifecycle

建议固定以下 Hook，不建设任意事件总线：

- `before_context_build`
- `after_context_build`
- `before_model_call`
- `after_model_call`
- `before_capability`
- `after_capability`
- `after_turn`
- `on_compression`

Hook 必须有固定输入输出类型、执行顺序、超时和失败策略。

### 12.6 验收标准

- Stable Prompt 在普通连续对话中 hash 不变。
- 大 ToolResult 不再完整重复进入后续模型请求。
- 自动任务不会污染普通用户记忆。
- Context 每一项都有 lineage、token_count 和保留原因。

---

## 13. Phase 7：本地 Plugin Runtime MVP

优先级：**可选**  
建议版本：v0.19.0-dev  
工作量：L

如果个人使用没有安装第三方插件的明确需求，可以暂缓本阶段，继续使用内置 Skill 和显式 MCP 配置。

### 13.1 Plugin Manifest

```toml
id = "local.example"
name = "Example Plugin"
version = "0.1.0"
min_cogito_version = "0.19.0"
entrypoint = "plugin.py:plugin"
sha256 = "..."

[permissions]
capabilities = ["artifact.create"]
file_read = ["workspace://notes/**"]
file_write = []
network_domains = []
secrets = []
background = false
```

### 13.2 生命周期

```text
discovered
  -> staged
  -> validated
  -> awaiting_permission
  -> enabled
  -> disabled / failed
```

### 13.3 安全要求

- 只支持用户显式指定的本地目录。
- 安装/验证阶段先做 AST 和静态规则扫描。
- 未经同意不能自动 import 并执行插件代码。
- 记录文件 hash，变化后重新验证。
- Plugin 只能通过 `PluginContext` 获取受限接口。
- Plugin 注册的 Capability 仍必须经过 Executor。
- 不允许 Plugin 直接拿 Database connection。

### 13.4 不做

- 插件市场。
- 自动在线更新。
- 远程代码下载并执行。
- 完整 Python 沙箱承诺；Python 进程内无法提供真正安全沙箱。

### 13.5 验收标准

- 插件权限在启用前可预览。
- 插件文件变化后自动禁用等待复核。
- 插件不能绕过 Capability Executor。
- 禁用插件后不影响历史 Audit、Trace 和 Artifact。

---

## 14. Phase 8：Task Domain 与受限 Subagent

优先级：**可选**  
建议版本：v0.19.0-dev  
工作量：L

### 14.1 先建立 Task，不先扩展多 Agent

Task 最小字段：

- task_id
- title
- description
- status: candidate / planned / running / blocked / completed / cancelled
- source_type / source_id
- priority
- due_at
- assigned_agent
- parent_task_id
- run_id
- artifact_ids
- created_at / updated_at / completed_at

`task_extraction` 只能创建 candidate。用户接受后才能进入 planned。

### 14.2 Subagent MVP 只支持一次性运行

首版约束：

- 一个父 Run 创建一个 Subagent Run。
- 最大深度为 1。
- 默认没有 Shell、网络和文件写权限。
- 显式权限快照保存在 Run input 中。
- 有独立预算、超时和 Context。
- 结果为结构化 `SubagentResult`，不能直接修改父状态。
- 父 Agent 或用户对结果进行重新验证。

### 14.3 可选 worktree 隔离

仅用于代码任务：

- 每个 Subagent 使用独立 Git worktree。
- 创建分支前检查工作区状态。
- 不自动合并。
- 结束后保留变更供用户检查。
- 删除 worktree 必须显式确认。

### 14.4 暂不支持

- Agent 间自由聊天网络。
- 无限递归 spawn。
- 多 Agent 共享可写 workspace。
- 自动合并代码。
- 无上限后台 Agent。

### 14.5 验收标准

- 进程重启后可以查询 Subagent 最终状态。
- 父子 Run、Trace 和权限链可追踪。
- 超时、取消和失败不会丢失中间 Artifact。
- Subagent 不能获得父 Agent 未授予的权限。

---

## 15. Phase 9：Console 收口与个人使用体验

优先级：**建议**  
工作量：M

Console 不需要继续追求页面数量，重点改为本地运维和可解释性。

### 15.1 首页重点信息

- 当前 Provider 和模型是否可用。
- 数据库、Secret Store 和 Workspace 状态。
- Pending Approval。
- Failed/Abandoned Run。
- 未读 Inbox。
- 最近备份时间。
- MCP/Plugin 待授权变化。

### 15.2 Run Detail

统一展示：

- 输入来源。
- 权限快照。
- 生命周期事件。
- Capability 调用。
- Approval。
- Trace。
- Artifact/Inbox 输出。
- 重试或取消操作。

### 15.3 本地安全默认值

- 默认 bind `127.0.0.1`。
- 非 loopback 绑定时强制显示风险并要求显式配置。
- 保留 API key、CSRF、CSP 和 Body Limit。
- 不为个人模式移除认证中间件。
- 下载 Artifact 时再次验证 workspace 和路径。

### 15.4 验收标准

- 用户可以从首页定位失败运行和待审批操作。
- Console mutation 全部经过 Application Service。
- 页面不展示原始 Secret 和未脱敏异常栈。
- 常见恢复操作不要求手工操作 SQLite。

---

## 16. 数据库迁移策略

### 16.1 原则

- 只做向前 migration。
- 每次 migration 可在备份副本上独立验证。
- 新表先双写或旁路记录，再迁移读取路径。
- 不在同一个版本同时删除旧表和迁移全部调用方。
- JSON 字段必须有 schema version。

### 16.2 建议迁移顺序

1. 新增 `runs/run_events/run_outputs`。
2. Scheduler 新运行写入 Run，同时保留旧记录。
3. Drift 和 Skill Run 迁移。
4. Console 改为读统一 Run View。
5. 验证一段时间后停止旧表写入。
6. 旧表保留至少一个开发版本，再决定是否清理。
7. MCP Server/Grant 独立 migration。
8. Plugin/Task 表只在对应功能正式开始时增加。

### 16.3 备份要求

- Migration 前自动创建不含 Secret 的默认备份。
- 如果使用 encrypted secret DB，备份时记录是否包含 Secret。
- Restore dry-run 检查 schema version 和文件完整性。

---

## 17. 测试策略

### 17.1 架构测试

- 禁止包依赖测试。
- 单一执行入口测试。
- Route 不直接写 Repository 测试。
- Plugin/MCP 不能获得 Database 对象测试。

### 17.2 治理负向测试

必须覆盖：

- 未授权 MCP Tool。
- Tool schema 变化。
- Path traversal 和 symlink escape。
- Shell 重定向、管道和子命令绕过。
- SSRF、localhost 编码变体和 metadata endpoint。
- Secret 出现在参数、日志、Trace 和错误中。
- 后台来源调用交互式高风险能力。

### 17.3 可靠性测试

- 两个 worker 同时 claim，仅一个成功。
- 执行中模拟进程崩溃。
- lease 过期恢复。
- 重复 idempotency_key。
- Windows 休眠后的 misfire。
- Approval 等待后恢复。
- Outbox 写入成功但 Delivery 失败。

### 17.4 Context 测试

- Stable Prompt hash 稳定。
- ToolResult 超阈值后 offload。
- Memory lineage 完整。
- Automation memory 默认不进入聊天。
- Compression 前后保留关键 Task/Approval 状态。

### 17.5 Plugin/Subagent 测试

- Plugin hash 变化自动禁用。
- Manifest 权限与实际请求不一致时拒绝。
- Subagent 权限不能升级。
- Subagent timeout/cancel/restart recovery。
- Worktree 路径逃逸和未提交改动保护。

---

## 18. 推荐实施顺序

### 必做闭环

```text
Phase 0 基线
  -> Phase 1 Runtime/Application 边界
  -> Phase 2 Governed Executor
  -> Phase 3 MCP 安全
  -> Phase 4 Durable Run/Scheduler
```

完成以上阶段后，项目已经适合个人长期运行。此时应暂停增加新功能，进行一次完整回归和实际使用观察。

### 建议体验改进

```text
Phase 5 Autonomy Envelope
  -> Phase 6 Prompt/Context/Memory
  -> Phase 9 Console 收口
```

### 按需求启用

```text
有本地扩展需求 -> Phase 7 Plugin Runtime
有复杂任务需求 -> Phase 8 Task + Subagent
```

Plugin 与 Subagent 不应成为核心改造的前置条件。

---

## 19. 工作量和里程碑建议

这里使用相对工作量，不绑定发布日期。

| 里程碑 | 内容 | 工作量 | 完成后的价值 |
|---|---|---:|---|
| M1 架构收口 | Phase 0～1 | L | Runtime 可测试、Channel 调用路径一致 |
| M2 安全窄腰 | Phase 2～3 | L | 所有能力统一治理，MCP 不再默认信任 |
| M3 本地可靠运行 | Phase 4 | L | Scheduler/Drift/Skill 可恢复、少重复 |
| M4 长期对话优化 | Phase 5～6 | M～L | Prompt 更稳定、上下文更干净 |
| M5 使用体验收口 | Phase 9 | M | 失败、授权、备份可在 Console 处理 |
| M6 可选扩展 | Phase 7～8 | XL | 本地插件、Task、受限 Subagent |

个人开发时建议每个里程碑单独合并，不要同时进行 M1、M2 和新的 UI 功能开发。

---

## 20. 参考项目的具体映射

### 20.1 Hermes Agent

采用：

- Narrow Waist：核心循环稳定，扩展放到边缘。
- 能力 Footprint Ladder：优先 Skill/MCP/Plugin，最后才增加核心 Tool。
- Stable/Context/Volatile Prompt 分层。
- Context Engine、Memory Provider 的生命周期接口。
- Cron claim TTL。
- MCP subprocess 最小环境变量。
- SSRF、危险命令和运行后端隔离思路。

不采用：

- 把所有功能继续集中进巨型 Agent 类。
- import-time 大规模自动注册。
- 为产品渠道数量牺牲核心模块边界。

### 20.2 Akashic Agent

采用：

- alert/content/context 主动输入分类。
- ACK、TTL、去重和来源失败隔离。
- Pending→Stable Memory。
- Proactive 与 Drift 分开。
- 有界的阶段 Hook。

不采用：

- 让 LLM 成为最终通知安全决策者。
- Drift 默认获得通用高风险工具。
- 用 Markdown 文件替代结构化数据库主记录。

### 20.3 QwenPaw

采用：

- Tool Guardian 链。
- Skill 静态安全扫描。
- Context 生命周期与 ToolResult offload。
- Cron timezone、heartbeat 和执行记录。
- 一次性 Subagent 和可选 worktree 隔离。

不采用：

- 复杂 Mixin MRO 作为核心扩展机制。
- 默认开启大量工具。
- 验证插件时直接执行未知 Python。
- 在没有权限模型前建设插件市场。

---

## 21. 风险与控制

### 风险 1：抽象层增加但代码没有减少

控制：每个 Port 必须对应清晰的 Runtime 需求；迁移完成后删除旧直连路径，不长期保留双重 API。

### 风险 2：Executor 成为新的 God Object

控制：Executor 只编排流程，Policy、Guardians、Approval、Invocation、Audit 分别由独立接口负责。

### 风险 3：迁移 Run 模型破坏现有 Scheduler/Drift

控制：先双写和影子读取；建立旧记录与新 run_id 的映射；至少经过一次真实重启测试再切换。

### 风险 4：安全规则影响个人使用便利性

控制：允许用户创建持久 Grant，但 Grant 必须限定 capability、来源、路径、域名和 schema hash，不能只有全局“永远允许”。

### 风险 5：Plugin 产生虚假安全感

控制：明确 Python 进程内插件不是强沙箱。未知代码应放到 subprocess/container；可信本地插件仍需最小权限。

### 风险 6：继续追逐参考项目功能数量

控制：以个人真实使用路径决定 Phase 7/8 是否实施。Channel、市场、多 Agent 数量不作为完成度指标。

---

## 22. 最终完成定义

个人本地版达到“架构改造完成”应满足：

1. Runtime 只依赖 Ports，不依赖具体 SQLite、Provider 和 Tool 实现。
2. CLI、API、Console 使用同一 Application Service。
3. 所有 Capability 调用统一经过治理、Guardian、Approval、Audit 和 Trace。
4. MCP Tool 默认不可执行，必须有明确 Grant。
5. Scheduler、Drift 和 Skill 使用统一 Durable Run，可从崩溃中恢复。
6. 大型 ToolResult 自动卸载到 Artifact。
7. 自动任务不污染普通用户记忆。
8. Console 能处理失败 Run、Approval、MCP 授权和备份恢复。
9. 所有 Secret 在配置、日志、Trace、Audit 和错误中保持脱敏。
10. 完整测试、Ruff、mypy、打包安装和至少一个实际本地工作流通过。

Plugin、Task、Subagent、Telegram/飞书不属于上述完成定义；它们是按个人需求添加的可选能力。

### 22.1 当前验收矩阵（2026-06-21）

| # | 完成定义 | 实现证据 | 验收状态 |
|---:|---|---|---|
| 1 | Runtime 只依赖 Ports | `runtime/ports.py`、`application/runtime_factory.py`、架构 import 测试 | 通过 |
| 2 | Channel 共享 Application Service | Chat 三 Channel、Console mutation 架构测试 | 通过 |
| 3 | Capability 统一治理 | `execution/executor.py`，Registry invoke 单入口测试 | 通过 |
| 4 | MCP 明确信任和 Grant | migration 18、`mcp/trust.py`、schema hash/revoke/secret 测试 | 通过 |
| 5 | Durable Run 与恢复 | migration 19、Scheduler/Drift/Skill、Run Console | 通过 |
| 6 | ToolResult 卸载 Artifact | Executor 阈值卸载与引用测试 | 通过 |
| 7 | 自动任务隔离普通记忆 | automation memory isolation 测试 | 通过 |
| 8 | Console 恢复操作 | Runs、Approval、MCP、Backup/Restore 页面 | 通过；Playwright 条件式 smoke 因依赖未安装跳过 |
| 9 | Secret 全链路脱敏 | Redacting formatter、Tracer、Audit、MCP config、ACK error | 通过 |
| 10 | 完整质量门禁 | `scripts/verify.py`、wheel 内容契约、`cogito-console` | **通过**：1709 collected，1705 passed、4 skipped；Ruff clean；mypy clean（189 source files）；daemon 4/4；Python 3.13 wheel 构建与内容契约通过 |

个人本地版必做完成定义已全部满足，本文档状态为 Completed。单进程全量 pytest 会被当前宿主约
25 秒的进程限制终止，因此使用覆盖全部收集用例的分组执行结果作为等价验收证据。

---

## 23. 建议立即开始的首批任务

按依赖顺序建议创建以下开发任务：

1. 建立架构 import boundary 测试并记录现有例外。
2. 定义 Runtime Ports，不修改行为。
3. 为现有实现编写 Port Adapters。
4. 将 RuntimeKernel 构造改为依赖 Ports。
5. 新建 `ChatApplicationService`，迁移 CLI/API/Console Chat。
6. 定义 `CapabilityExecutionRequest/Result`。
7. 建立 `GovernedCapabilityExecutor`，先迁移内置 Tool。
8. 迁移 Skill、MCP 和 Drift 调用路径。
9. 增加 MCP Server/Tool Grant migration。
10. 修复 MCP 默认 low-risk 和无审批的问题。
11. 设计并增加统一 `runs/run_events/run_outputs` migration。
12. 迁移 Scheduler 到原子 claim 和 recovery sweep。

前六项完成后先做一次架构评审；第十二项完成后再开始新的用户功能。
