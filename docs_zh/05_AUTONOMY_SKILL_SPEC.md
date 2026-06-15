# 05 Autonomy 与 Skill 规格

## Skill Manifest

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 稳定标识。 |
| `version` | 是 | Semver。 |
| `description` | 是 | Skill 的作用。 |
| `inputs` | 是 | JSON Schema。 |
| `outputs` | 是 | JSON Schema。 |
| `steps` | 是 | 有序步骤声明。 |
| `permissions` | 是 | 请求的能力权限。 |
| `risk_level` | 是 | 所有步骤中的最高风险。 |
| `rollback` | 否 | 写操作的补偿步骤。 |
| `owner` | 否 | 内置、用户、导入。 |

Step 字段：`id`、`name`、`kind`、`uses_capability`、`input_mapping`、`output_mapping`、`on_error`、`trace_required`。

## Skill Pool 和 Workspace Skill Copy

Skill Pool 存储共享的内置或导入 Skill 定义。Workspace Skill Copy 是绑定到单个 Workspace 的可执行副本，包含本地配置、权限、版本 pin 和用户编辑。

规则：

- 不得直接从 Skill Pool 执行。
- 执行前必须复制到 Workspace。
- Pool 版本变化不得修改已有 Workspace 副本。
- Workspace 副本可以禁用而不删除历史。

## 版本管理

使用 Semver。Patch 变更不得改变权限。Minor 变更可以增加可选步骤。Major 变更可以改变输入、输出、权限或行为，并且需要重新审批。

## Skill 执行

Runtime 流程：

```text
resolve workspace skill -> validate input -> policy preflight
-> create trace -> execute steps -> normalize output
-> rollback if needed -> persist run log
```

每个步骤创建一个子 Span。使用 Capability 的步骤必须经过 Governance。Skill 输出必须包含摘要、结构化结果、产物和来源链路。

## 权限和安全

Skill 权限是所有步骤权限的并集。后台 Skill 执行比交互式执行更严格。MVP 中 Skill 不得请求 critical 操作。V1 中写操作需要每次运行显式审批或已保存 Grant。

## 回滚

回滚是尽力补偿，不保证事务性。任何写文件、修改记忆或发送外部数据的步骤，都必须声明是否可回滚。MVP 只记录回滚元数据，不执行复杂回滚。

## Autonomy 组件

| 组件 | 职责 | MVP |
|---|---|---|
| Scheduler | 运行一次性或周期任务。 | 否。 |
| Proactive Loop | 根据上下文判断是否通知用户。 | 否。 |
| Drift Runtime | 空闲维护、摘要、清理、研究。 | 否。 |
| Notification Gate | 应用安静时间、去重、配额和安全策略。 | 否。 |

## Scheduler

未来 Scheduler Job 包含 `run_at`、`interval`、`workspace_id`、`actor`、`payload`、`max_retries`、`quiet_hours_policy` 和 `enabled`。Job 必须创建 Trace 并审计决策。

## Proactive Loop

Proactive Loop 评估外部事件和记忆/上下文信号。它只能提出通知建议，不能直接发送。它必须评分相关性、紧急性、置信度、打扰成本和去重匹配。

## Drift Runtime

Drift 执行后台维护，例如记忆合并、陈旧记忆检测、索引刷新、Trace 清理和报告准备。未经审批，它不能发送外部消息或执行高风险写操作。

## Notification Gate

规则：

- 安静时间阻止非关键通知。
- 按事件 hash、主题和最近通知历史去重。
- 默认配额：MVP 没有主动通知；未来默认每 Workspace 每天最多 3 条。
- 用户反馈选项：有用、没用、太频繁、上下文错误、不再显示。

## 后台任务安全限制

后台任务不得访问 Secret、删除数据、发送外部消息、运行 Shell 命令或安装插件。只有当 Policy 允许时，它们才可以读取已接受记忆，并写入低风险维护记录。

## MVP 行为

MVP 只包含 Skill Manifest schema 草案。不实现 Scheduler、Proactive Loop、Drift Runtime、通知发送或后台 Skill 执行。Runtime 必须保留扩展点，但不实现自主行为。

## V1 行为

Workspace Skill Copy、交互式 Skill 执行、Step Trace、权限预检、写步骤审批、简单回滚记录和 Skill 运行历史。

## V2 行为

Scheduler、Proactive Loop、Drift Runtime、Notification Gate、配额、安静时间、反馈学习、后台安全 Skill 子集和更完整的回滚/补偿。
