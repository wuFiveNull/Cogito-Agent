# 02 Runtime 规格

## 职责

Runtime Kernel 负责将一次 turn 从输入事件推进到最终结果。它协调上下文构建、模型调用、能力调用、策略检查、Trace/Audit 记录、记忆候选提取、重试、中断和结果组合。

它不得直接依赖 UI 渠道、Provider SDK、具体工具实现、数据库驱动或 Skill 内部逻辑。它只能使用接口。

## RuntimeEvent Schema

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | UUID。 |
| `workspace_id` | string | 是 | 隔离边界。 |
| `session_id` | string | 是 | 会话范围。 |
| `actor_id` | string | 是 | 用户、系统、调度器或 Skill。 |
| `source` | enum | 是 | `cli`、`api`、`scheduler`、`skill`、`webhook`。 |
| `type` | enum | 是 | `user_message`、`tool_result`、`approval_result`、`resume`、`interrupt`。 |
| `payload` | object | 是 | 按类型校验。 |
| `created_at` | datetime | 是 | UTC。 |
| `parent_trace_id` | string? | 否 | 用于恢复或后台任务。 |

## Turn 生命周期

```text
receive_event -> create_trace -> load_session -> build_context
-> plan_or_model_call -> maybe_call_capability -> compose_result
-> extract_memory_candidates -> persist -> deliver_result
```

## Turn 状态机

| 状态 | 允许迁移 |
|---|---|
| `received` | `loading_session`, `failed` |
| `loading_session` | `building_context`, `failed` |
| `building_context` | `awaiting_model`, `failed` |
| `awaiting_model` | `evaluating_result`, `calling_tool`, `failed` |
| `calling_tool` | `awaiting_approval`, `evaluating_result`, `retrying`, `failed` |
| `awaiting_approval` | `calling_tool`, `denied`, `interrupted` |
| `evaluating_result` | `composing_result`, `awaiting_model`, `calling_tool`, `failed` |
| `composing_result` | `persisting`, `failed` |
| `persisting` | `completed`, `failed` |
| `retrying` | 上一个可执行状态, `failed` |
| `interrupted` | `resuming`, `cancelled` |
| `resuming` | `building_context`, `calling_tool`, `awaiting_model` |
| `completed` | 终态 |
| `failed` | 终态 |
| `denied` | 终态 |
| `cancelled` | 终态 |

非法迁移必须被拒绝，并记录为 Trace 错误。

## 用户请求流程

1. Channel Adapter 创建 `RuntimeEvent`。
2. Kernel 创建 Trace 和 Root Span。
3. 加载 Session 和 Workspace。
4. Context Engine 返回带来源链路的排序上下文。
5. Policy 检查模型调用是否允许。
6. Model Adapter 返回 Assistant 消息或工具意图。
7. 工具意图经过 Capability Registry 和 Governance。
8. Result Composer 返回最终输出。
9. 持久化记忆候选、Trace、Audit 和会话消息。

## 工具调用流程

工具调用绝不能直接从模型输出执行。Runtime 必须校验工具意图、解析能力 Manifest、构建 Policy 请求、在需要时处理审批、通过 Capability 接口执行、规范化结果，并记录 `ToolCall`。

验收标准：被拒绝的工具调用必须产生用户可见说明；已批准调用必须包含 Trace Span、Audit 记录、按需脱敏的输入、输出摘要和来源链路。

## 模型调用流程

模型调用接收与提供方无关的消息、当前上下文允许的工具、token 预算和 Trace 元数据。Adapter 返回规范化内容、工具意图、用量、延迟和 provider 标识。

验收标准：每次调用都记录模型名、提供方、prompt hash 或脱敏摘要、token 用量、延迟、停止原因和错误。

## 审批等待流程

当 Policy 返回 `require_approval` 时，Runtime 将 turn 状态持久化为 `awaiting_approval`，并保存审批请求数据。CLI MVP 可以行内询问；API 后续返回审批 token，并通过 `approval_result` 恢复。

## 失败和重试

只重试临时性的模型、provider 或工具失败。默认最多重试 2 次，使用指数退避。非幂等的写入、发送、删除操作不得重试，除非能力声明幂等。

## 中断和恢复

中断必须持久化状态、Trace、待处理能力调用和上下文来源链路。恢复前必须重新校验 Policy 和预算。

## 预算控制

每个 turn 有墙钟时间、模型 token、模型调用次数、工具调用次数和成本估算预算。MVP 默认：1 次模型调用、2 次工具调用、60 秒墙钟时间、可配置 token 限制。

## 结果组合

最终输出包含 Assistant 文本、相关工具摘要、来源引用、待审批状态和错误摘要。不得向用户暴露 secret 或原始内部 Trace。

## MVP 行为

MVP 支持 `cli` 用户消息、一个 Session、一个 Workspace、一个模型 Adapter、简单上下文检索、同步工具调用、行内审批、Trace/Audit 持久化和终态。

## 未来扩展

API 恢复 token、流式输出、后台 turn、Subagent 子 Trace、多步计划、持久队列、部分结果和跨设备 Session 同步。
