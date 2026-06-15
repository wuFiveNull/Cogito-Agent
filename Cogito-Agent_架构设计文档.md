# Cogito-Agent 架构设计文档

**项目名称**：Cogito-Agent  
**目标**：构建一个本地优先、可主动服务、可扩展技能、具备长期记忆、安全治理和链路可追溯能力的个人 Agent 系统。

---

## 1. 架构定位

Cogito-Agent 是一个面向个人长期使用的 Agent Runtime。系统不只是一个聊天机器人，而是一个围绕用户上下文、长期记忆、工具能力、技能工作流、主动服务、安全治理和链路追踪构建的个人智能操作层。

系统的核心目标包括：

- 支持多渠道入口。
- 支持长期记忆和上下文治理。
- 支持工具、MCP、插件和 Skill 扩展。
- 支持主动任务、定时任务和后台维护任务。
- 支持多模型路由与多 Agent 工作区。
- 支持安全权限控制、审批、审计和回放。
- 支持完整链路追踪和行为溯源。
- 支持本地优先部署，并保留云端扩展能力。
- 支持数据导出、迁移、备份和删除。

---

## 2. 总体架构

```text
┌──────────────────────────────────────────────────────────┐
│                     用户入口层                            │
│        Web / Telegram / 飞书 / CLI / API / Webhook         │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                     Gateway Layer                         │
│        Auth / Session Binding / Rate Limit / Delivery      │
│        WebSocket / Channel Adapter / Request Normalize     │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                  Agent Runtime Kernel                     │
│        Turn State Machine / Event Bus / Budget Control     │
│        Interrupt / Retry / Trace / Runtime Orchestration   │
└──────────────┬────────────────┬────────────────┬──────────┘
               │                │                │
┌──────────────▼───────┐ ┌──────▼────────┐ ┌────▼───────────┐
│ Context & Reasoning  │ │ Capability    │ │ Autonomy Plane │
│ Plane                │ │ Plane         │ │                │
│ Prompt Builder       │ │ Tool Registry │ │ Scheduler      │
│ Context Engine       │ │ MCP Registry  │ │ Proactive Loop │
│ Memory Retrieval     │ │ Skill Runtime │ │ Drift Runtime  │
│ Compression          │ │ Plugin Runtime│ │ Notification   │
│ Model Router         │ │ Subagent      │ │ Gate           │
└──────────────┬───────┘ └──────┬────────┘ └────┬───────────┘
               │                │               │
┌──────────────▼────────────────▼───────────────▼──────────┐
│                    Governance Plane                       │
│        Policy Engine / Approval / Safety Guard             │
│        Capability Grant / Audit / Eval / Replay            │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                 Trace & Observability Plane               │
│        Trace Tree / Span / Run Log / Cost / Replay         │
│        Source Lineage / Decision Log / Behavior Review     │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                      Storage Plane                        │
│        SQL State / Memory Store / Vector + BM25 Index      │
│        Object Storage / Secret Store / Trace Store         │
│        Workspace Files / Logs / Backup                     │
└──────────────────────────────────────────────────────────┘
```

整体架构采用运行时分层设计。用户入口层负责多渠道交互，Gateway Layer 负责接入控制和请求标准化，Agent Runtime Kernel 负责运行时状态推进，Context & Reasoning Plane 负责上下文和模型推理，Capability Plane 负责工具、技能和子 Agent 能力，Autonomy Plane 负责主动服务和后台任务，Governance Plane 统一处理安全、审批和审计，Trace & Observability Plane 负责链路追踪、行为回放和问题复盘，Storage Plane 负责状态、记忆、文件、日志和密钥的持久化。

---

## 3. 核心架构原则

### 3.1 Runtime Kernel 最小化

Agent Runtime Kernel 只负责运行时编排，不直接绑定具体渠道、具体模型、具体工具、具体数据库或具体 Skill。

它只处理以下抽象：

- 输入事件。
- 会话状态。
- 上下文请求。
- 能力调用。
- 安全策略。
- 执行预算。
- 状态迁移。
- 运行轨迹。

### 3.2 能力插件化

工具、MCP、Skill、插件和子 Agent 都以 Capability 的形式接入系统。

所有 Capability 必须声明：

- 能力名称。
- 输入输出 schema。
- 权限范围。
- 风险等级。
- 可调用场景。
- 审批要求。
- 审计要求。

### 3.3 上下文集中治理

系统不直接把所有记忆、文件、工具结果和历史对话塞入模型上下文，而是由 Context Engine 统一治理。

Context Engine 负责：

- 上下文来源选择。
- 上下文优先级排序。
- token 预算分配。
- 长上下文压缩。
- 检索结果裁剪。
- 工具结果整理。
- Prompt 结构组装。
- 上下文来源追溯。

### 3.4 安全策略前置

所有外部能力调用、文件访问、写操作、消息发送、日程修改、Shell 执行、插件启用和后台任务执行，都必须经过 Governance Plane 的策略判断。

系统默认遵循：

- 读操作可控放行。
- 写操作记录审计。
- 外部发送操作需要审批。
- 高风险操作默认禁止或逐次确认。
- 后台自动任务使用更严格权限。
- Secret 与用户数据隔离存储。
- 所有自动行为可暂停、可追踪、可回滚。

### 3.5 主动服务独立运行

主动推送和后台维护不直接复用主对话循环，而是由 Autonomy Plane 独立运行。

主动服务必须满足：

- 有明确触发来源。
- 有去重机制。
- 有打扰成本评估。
- 有安静时间策略。
- 有推送配额。
- 有决策日志。
- 有用户反馈入口。

### 3.6 链路追踪内建化

系统需要把 Trace 作为运行时的一等能力，而不是普通日志的附属品。

每一次用户请求、主动任务、后台任务、Skill 执行和工具调用，都应能够追溯到：

- 触发来源。
- 运行路径。
- 上下文来源。
- 模型调用。
- 工具调用。
- 权限判断。
- 审批记录。
- 中间产物。
- 记忆变更。
- 最终输出。

---

## 4. 主要架构层

## 4.1 用户入口层

用户入口层负责承接不同渠道的输入和输出。

支持的入口包括：

- Web。
- Telegram。
- 飞书。
- CLI。
- API。
- Webhook。

该层不包含 Agent 推理逻辑，只负责渠道适配、消息格式转换、用户交互呈现和推送送达。

---

## 4.2 Gateway Layer

Gateway Layer 是系统的接入控制层，负责把外部请求转换为标准运行时事件。

主要职责包括：

- 用户身份认证。
- 会话绑定。
- 渠道识别。
- 请求标准化。
- 限流。
- 长连接管理。
- 消息投递。
- 回调处理。
- Webhook 接入。

Gateway Layer 向下只提交标准事件，不直接调用模型、工具或记忆系统。

---

## 4.3 Agent Runtime Kernel

Agent Runtime Kernel 是系统的运行时核心，负责一次用户交互、一次主动任务或一次后台任务的状态推进。

核心职责包括：

- 维护 Turn State Machine。
- 管理运行时事件。
- 控制任务预算。
- 支持中断与恢复。
- 处理失败重试。
- 记录运行轨迹。
- 协调 Context、Capability、Governance、Trace 和 Storage。

Agent Runtime Kernel 不关心具体能力的实现，只关心能力调用的声明、结果和状态变化。

---

## 4.4 Context & Reasoning Plane

Context & Reasoning Plane 负责将用户请求、历史会话、长期记忆、文件资料、工具结果、Skill 指令和系统策略组合成适合模型处理的上下文。

主要模块包括：

| 模块 | 职责 |
|---|---|
| Prompt Builder | 构建模型输入结构。 |
| Context Engine | 管理上下文来源、预算、排序和裁剪。 |
| Memory Retrieval | 从长期记忆中检索相关信息。 |
| Context Compression | 对长会话、长文档和工具结果进行压缩。 |
| Model Router | 根据任务类型、成本、延迟和能力选择模型。 |
| Result Composer | 汇总模型输出、工具结果和引用来源，生成最终响应。 |

该层是 Agent 智能表现的核心，但不直接执行外部操作。

---

## 4.5 Capability Plane

Capability Plane 负责承载系统可调用的所有外部能力和可复用能力。

主要能力类型包括：

| 类型 | 说明 |
|---|---|
| Tool | 单次可调用的外部能力，例如搜索、文件读写、日历、邮件。 |
| MCP Server | 通过 MCP 协议接入的外部工具集合。 |
| Plugin | 可安装、可启用、可禁用的扩展能力。 |
| Skill | 可复用的多步骤工作流。 |
| Subagent | 面向复杂任务的临时或长期子 Agent。 |

Capability Plane 不直接决定是否允许调用某个能力。所有能力调用都必须经过 Governance Plane 的策略判断。

---

## 4.6 Skill Runtime

Skill Runtime 负责加载、校验、执行和管理可复用工作流。

Skill 采用声明式定义，包含：

- Skill 元信息。
- 输入输出定义。
- 所需工具。
- 所需权限。
- 风险等级。
- 执行步骤。
- 变更记录。

系统区分 Skill Pool 和 Workspace Skill Copy。

- Skill Pool 用于存放共享技能、内置技能和导入技能。
- Workspace Skill Copy 是某个 Agent 或工作区实际运行的技能副本。

这种设计保证共享技能、用户修改和运行环境之间保持隔离，便于变更管理、回滚和安全审查。

---

## 4.7 Memory Layer

Memory Layer 负责长期记忆的采集、整理、检索、更新和删除。

记忆类型包括：

| 类型 | 说明 |
|---|---|
| Profile Memory | 用户基本偏好和长期稳定信息。 |
| Project Memory | 项目背景、目标、进展和决策。 |
| Relationship Memory | 联系人、组织和协作关系。 |
| Task Memory | 长期待办、承诺和跟进事项。 |
| Preference Memory | 输出格式、推送频率、技术栈偏好。 |
| Episodic Memory | 重要历史事件和交互片段。 |
| Skill Memory | 已沉淀的可复用工作流经验。 |

记忆需要具备完整生命周期：

```text
Candidate
  → Pending
  → Accepted
  → Consolidated
  → Indexed
  → Stale
  → Archived / Deleted
```

每条记忆应保留来源、时间、置信度、敏感等级、可见范围和可追溯信息。

---

## 4.8 Autonomy Plane

Autonomy Plane 负责系统的主动服务、定时任务和后台维护能力。

它由三个核心部分组成：

| 模块 | 职责 |
|---|---|
| Scheduler | 创建和运行一次性任务、周期任务和系统任务。 |
| Proactive Loop | 根据外部事件、用户上下文和长期偏好判断是否主动通知用户。 |
| Drift Runtime | 在空闲时执行后台整理、研究、自省和维护任务。 |

Autonomy Plane 与主对话运行时相互独立，但共享 Memory、Capability、Governance、Trace 和 Storage。

主动服务的输出必须经过 Notification Gate，以确保不过度打扰用户。

---

## 4.9 Governance Plane

Governance Plane 是系统的安全、权限和审计中心。

主要模块包括：

| 模块 | 职责 |
|---|---|
| Policy Engine | 根据主体、能力、资源、操作和上下文判断是否允许执行。 |
| Approval Manager | 管理用户审批流程。 |
| Safety Guard | 拦截危险工具调用、敏感文件访问和高风险操作。 |
| Capability Grant | 管理工具、Skill、插件和子 Agent 的权限授予。 |
| Audit Log | 记录所有关键决策、工具调用和写操作。 |
| Eval & Replay | 支持运行回放、行为评估和问题复盘。 |

Governance Plane 对主对话、主动服务、后台任务和插件运行统一生效。

---

## 4.10 Trace & Observability Plane

Trace & Observability Plane 负责系统行为的链路追踪、运行观测、问题定位和行为回放。

Trace 关注系统如何执行，Audit 关注系统是否合规。二者共享同一条执行链，但面向不同用途。

Trace 主要记录：

- 请求入口。
- 运行状态。
- 上下文构建。
- 记忆检索。
- 模型调用。
- 工具调用。
- Skill 执行。
- 文件读写。
- 主动推送决策。
- Drift 后台运行。
- 成本与耗时。
- 错误与重试。
- 最终响应。

Audit 主要记录：

- 谁触发了行为。
- 是否涉及敏感资源。
- 是否经过审批。
- 是否访问或修改用户数据。
- 是否向外部系统发送信息。
- 是否创建、修改或删除文件。
- 是否创建、修改或删除记忆。
- 是否命中安全策略。

系统应支持从最终回复反向追溯到使用过的记忆、文件、工具、模型调用、权限判断和审批记录。

---

## 4.11 Storage Plane

Storage Plane 负责系统所有持久化数据。

主要存储类型包括：

| 类型 | 说明 |
|---|---|
| SQL State | 用户、会话、任务、权限、配置和运行状态。 |
| Memory Store | 长期记忆、用户画像、项目上下文和历史事件。 |
| Vector + BM25 Index | 语义检索和关键词检索。 |
| Object Storage | 文件、附件、报告、图片和中间产物。 |
| Secret Store | API Key、OAuth Token 和敏感凭证。 |
| Trace Store | 工具调用、模型调用、任务状态和审计日志。 |
| Workspace Files | 用户工作区、本地文件和技能副本。 |

Storage Plane 应支持本地优先部署，同时保留迁移到服务化数据库、对象存储和分布式任务系统的能力。

---

## 5. 多 Agent 工作区

系统支持多个 Agent 工作区。每个工作区拥有独立的：

- Agent 配置。
- 会话历史。
- 长期记忆。
- Skill 副本。
- 工具权限。
- 渠道绑定。
- 运行日志。
- 安全策略。

多 Agent 工作区适用于不同角色隔离，例如：

- 个人助理。
- 项目助理。
- 代码助理。
- 研究助理。
- 信息监控助理。

系统也支持任务级 Subagent。Subagent 可由主 Agent 临时创建，用于处理复杂任务中的局部问题，并在完成后返回结构化结果。

---

## 6. 运行时流程

### 6.1 用户请求流程

```text
User Message
  → Channel Adapter
  → Gateway Normalize
  → Session Binding
  → Agent Runtime Kernel
  → Context Engine
  → Policy Check
  → Model Router
  → Capability Call, if needed
  → Result Composer
  → Response Delivery
  → Memory Candidate Extraction
  → Trace & Audit Persist
```

### 6.2 工具调用流程

```text
Tool Intent
  → Capability Registry
  → Schema Validation
  → Policy Check
  → Approval, if needed
  → Tool Execution
  → Result Normalize
  → ToolCall Log
  → Context Update
  → Trace Persist
```

### 6.3 Skill 执行流程

```text
Skill Request
  → Skill Resolve
  → Workspace Copy Load
  → Permission Check
  → Context Prepare
  → Step Execution
  → Result Compose
  → Skill Run Log
  → Reflection Candidate
  → Trace Persist
```

### 6.4 主动服务流程

```text
Tick / External Event
  → Event Normalize
  → Context Match
  → Relevance Judge
  → Deduplication
  → Notification Gate
  → Push or Skip
  → Decision Log
  → Feedback Capture
  → Trace Persist
```

### 6.5 后台 Drift 流程

```text
Idle Window
  → Drift Runtime
  → Background Skill Select
  → Context Prepare
  → Safe Capability Call
  → Maintenance / Research / Reflection
  → Candidate Output
  → Persist or Notify
  → Trace Persist
```

---

## 7. 链路追踪模型

系统需要为每一次运行生成完整 Trace。

一次 Trace 由多个 Span 组成，每个 Span 表示一次运行步骤，例如：

- Gateway 接收请求。
- Session 加载。
- Context 构建。
- Memory 检索。
- Prompt 组装。
- Model 调用。
- Policy 判断。
- Tool 调用。
- Skill 步骤执行。
- 文件读写。
- 记忆更新。
- 主动推送判断。
- 最终响应生成。

Trace 之间需要能够表达父子关系，使复杂任务、子 Agent、工具链和后台任务都能被串联为完整执行树。

典型用户请求链路：

```text
Trace
├── Gateway Receive
├── Session Load
├── Context Build
│   ├── Memory Retrieval
│   ├── File Retrieval
│   └── Prompt Assembly
├── Model Call
├── Tool Call
│   ├── Policy Check
│   ├── Approval
│   └── Execution
├── Result Compose
├── Memory Extraction
├── Response Delivery
└── Persist Audit
```

典型主动服务链路：

```text
Trace
├── Scheduler Tick
├── Source Pull
├── Event Normalize
├── Relevance Judge
├── Deduplication
├── Notification Gate
├── Push / Skip
└── Decision Log
```

典型 Skill 执行链路：

```text
Trace
├── Skill Resolve
├── Skill Permission Check
├── Step 1
│   ├── Model Call
│   └── Tool Call
├── Step 2
│   ├── Model Call
│   └── File Write
├── Skill Result
└── Skill Reflection
```

系统应支持根据一次最终响应反向追溯到：

- 使用了哪些长期记忆。
- 使用了哪些文件或外部资料。
- 进行了哪些模型调用。
- 调用了哪些工具。
- 触发了哪些安全策略。
- 是否经过用户审批。
- 生成了哪些中间产物。
- 写入了哪些记忆或文件。
- 为什么产生最终响应。

---

## 8. 安全模型

系统采用 Capability-based Policy，而不是单纯依赖工具风险等级。

一次能力调用由以下因素共同决定是否允许：

```text
Actor + Capability + Resource + Operation + Context → Decision
```

其中：

| 因素 | 示例 |
|---|---|
| Actor | 用户、Agent、Skill、Plugin、Scheduler、Proactive Loop。 |
| Capability | 文件读取、文件写入、Shell、网络访问、邮件发送、日历修改。 |
| Resource | 文件路径、域名、账号、频道、工作区、密钥。 |
| Operation | 读取、写入、删除、执行、发送、导出。 |
| Context | 是否用户在线、是否后台运行、是否安静时间、是否可信 Skill。 |

安全决策结果包括：

- Allow。
- Allow with Audit。
- Require Approval。
- Deny。
- Escalate。

---

## 9. 数据治理

系统必须支持用户对自身数据的完整控制。

数据治理能力包括：

- 数据导出。
- 数据删除。
- 记忆纠错。
- 记忆禁用。
- 会话清理。
- 文件清理。
- 日志保留策略。
- 备份与恢复。
- 本地与云端迁移。

长期记忆、敏感文件、密钥和审计日志应采用不同的存储域和访问策略。

---

## 10. 可观测性与审计

系统需要对所有关键行为建立可追踪记录。

需要记录的事件包括：

- 用户请求。
- 模型调用。
- 工具调用。
- Skill 执行。
- 插件启用。
- 权限审批。
- 主动推送决策。
- 后台 Drift 运行。
- 文件读写。
- 外部消息发送。
- 错误与重试。
- 记忆创建、更新和删除。

审计记录应支持查询、导出、回放和问题复盘。

---

## 11. 最终架构边界

Cogito-Agent 的最终架构边界如下：

- 用户入口层只负责渠道接入。
- Gateway Layer 只负责请求标准化、身份和会话绑定。
- Agent Runtime Kernel 只负责运行时状态推进。
- Context & Reasoning Plane 只负责上下文、推理和模型路由。
- Capability Plane 只负责提供可调用能力。
- Autonomy Plane 只负责主动服务和后台任务。
- Governance Plane 统一负责安全、权限、审批和审计。
- Trace & Observability Plane 统一负责链路追踪、运行观测和行为回放。
- Storage Plane 统一负责状态、记忆、文件、密钥和日志。

该架构的核心目标是让个人 Agent 具备长期运行能力、可扩展能力、主动服务能力、安全治理能力和完整链路追溯能力，同时保持本地优先、模块解耦和可持续演进。
