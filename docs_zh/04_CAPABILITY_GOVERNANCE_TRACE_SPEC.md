# 04 能力、治理与 Trace 规格

## 能力类型

| 类型 | 含义 | MVP |
|---|---|---|
| Tool | 单个可调用函数，例如文件读取或搜索。 | 是，仅限安全本地工具。 |
| MCP Server | 外部 MCP 工具集合。 | 否。 |
| Plugin | 可安装扩展包。 | 否。 |
| Skill | 可复用多步骤工作流。 | 仅 Manifest；Runtime 在 V1。 |
| Subagent | 用于委派工作的子 Agent。 | 否。 |

## Capability Manifest

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 稳定标识，例如 `local.file_read`。 |
| `version` | 是 | Semver。 |
| `type` | 是 | `tool`、`mcp_server`、`plugin`、`skill`、`subagent`。 |
| `description` | 是 | 操作性描述。 |
| `input_schema` | 是 | JSON Schema 或 Pydantic 生成 schema。 |
| `output_schema` | 是 | 规范化结果 schema。 |
| `permissions` | 是 | 请求的资源和操作。 |
| `risk_level` | 是 | `low`、`medium`、`high`、`critical`。 |
| `allowed_contexts` | 是 | `interactive`、`approved_background`、`system_maintenance`。 |
| `approval_required` | 是 | 布尔值或规则引用。 |
| `audit_required` | 是 | 布尔值。 |
| `idempotent` | 是 | 重试决策必需。 |

示例：

```yaml
name: local.file_read
type: tool
risk_level: medium
permissions:
  - resource: workspace_file
    operations: [read]
allowed_contexts: [interactive]
approval_required: false
audit_required: true
idempotent: true
```

## Schema 和结果规则

输入必须在 Policy 评估前校验。输出必须规范化为：

| 字段 | 含义 |
|---|---|
| `status` | `ok`、`denied`、`error`、`partial` |
| `summary` | 适合模型读取的短摘要。 |
| `data` | 结构化结果，有大小限制。 |
| `artifacts` | 文件或对象引用。 |
| `redactions` | 被脱敏字段名和原因。 |
| `lineage` | 来源引用。 |

## 权限和风险规则

| 风险 | 示例 | 默认决策 |
|---|---|---|
| `low` | 纯计算、格式转换 | `allow` |
| `medium` | Workspace 文件读取、本地搜索 | `allow_with_audit` |
| `high` | 文件写入、网络请求、记忆变更 | `require_approval` |
| `critical` | 删除、Shell 执行、外部发送、Secret 访问 | MVP 中 `deny` |

## Policy Model

```text
Actor + Capability + Resource + Operation + Context -> Decision
```

决策类型：`allow`、`allow_with_audit`、`require_approval`、`deny`、`escalate`。

Policy 矩阵：

| Actor | Operation | Context | MVP decision |
|---|---|---|---|
| user | read workspace file | interactive | `allow_with_audit` |
| assistant | write workspace file | interactive | `require_approval` |
| assistant | delete file | interactive | `deny` |
| skill | call network | background | `deny` |
| scheduler | send notification | quiet hours | `deny` |
| system | write trace log | any | `allow_with_audit` |

`escalate` 表示本地策略无法决策，需要显式用户/管理员配置。MVP 可将 `escalate` 视为 `deny`。

## 审批规则

审批请求必须展示 Actor、Capability、Operation、Resource、Risk、Reason 和预期副作用。除非未来 Grant 系统显式扩大范围，否则审批只对单次调用生效。

## 审计规则

所有写入、发送、删除、审批、拒绝、记忆变更、文件读取和策略升级都必须审计。脱敏 Secret 和大 payload。存储足够元数据以解释谁在何时为何做了什么。

## Trace Model

Trace 用于执行可观测性。Audit 用于合规历史。二者共享标识但服务不同读者。

| Trace 字段 | 说明 |
|---|---|
| `id` | UUID。 |
| `workspace_id` | 必填。 |
| `session_id` | 后台任务可选。 |
| `root_event_id` | RuntimeEvent ID。 |
| `status` | `running`、`completed`、`failed`、`cancelled`。 |
| `started_at`, `ended_at` | UTC。 |

## Span Model

Span 字段：`id`、`trace_id`、`parent_span_id`、`name`、`kind`、`status`、`started_at`、`ended_at`、`input_summary`、`output_summary`、`error`、`metadata_json`。

Span 类型：`runtime`、`context`、`model`、`tool`、`policy`、`approval`、`memory`、`storage`、`result`。

## ToolCall 和 ModelCall 日志

ToolCall 字段：`id`、`trace_id`、`span_id`、`capability_name`、`input_summary`、`decision`、`approval_id`、`status`、`output_summary`、`latency_ms`、`error`。

ModelCall 字段：`id`、`trace_id`、`span_id`、`provider`、`model`、`input_token_count`、`output_token_count`、`prompt_summary`、`response_summary`、`latency_ms`、`stop_reason`、`error`。

## 回放和脱敏

回放必须重建状态迁移、策略决策、模型/工具摘要和来源链路。MVP 回放是只读 Trace 检查，不是确定性重执行。敏感数据脱敏适用于 Secret、Token、凭证、标记为敏感的个人标识和大型原始 prompt。

## MVP 行为

Manifest 注册表、静态 Policy 矩阵、行内审批、Trace/Span 日志、Tool/Model Call 日志、Audit 记录、响应级来源链路和脱敏工具。

## 未来扩展

动态 Grant、MCP/Plugin Manifest、Policy DSL、Audit 导出、确定性回放、Subagent Trace 树、签名日志和 Eval 集成。
