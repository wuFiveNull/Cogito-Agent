# 03 数据、记忆与上下文规格

## 核心领域实体

| 实体 | 目的 |
|---|---|
| Workspace | Session、Memory、Capability 和 Policy 的隔离边界。 |
| Session | Workspace 内的会话容器。 |
| Message | 用户、Assistant、System 或 Tool 消息。 |
| Memory | 长期保存的事实或偏好。 |
| MemoryCandidate | 等待接受、拒绝或纠正的候选记忆。 |
| ContextItem | 被纳入或考虑纳入模型调用的排序上下文项。 |
| SourceLineage | 输出/上下文到原始消息、文件、记忆、工具或模型调用的链接。 |
| FileArtifact | 本地文件引用或生成产物元数据。 |

## 数据库表

| 表 | 重要字段 |
|---|---|
| `workspaces` | `id`, `name`, `created_at`, `deleted_at` |
| `sessions` | `id`, `workspace_id`, `title`, `status`, `created_at`, `updated_at`, `deleted_at` |
| `messages` | `id`, `workspace_id`, `session_id`, `role`, `content`, `metadata_json`, `created_at`, `deleted_at` |
| `memories` | `id`, `workspace_id`, `type`, `status`, `text`, `summary`, `confidence`, `sensitivity`, `source_id`, `created_at`, `updated_at`, `deleted_at` |
| `memory_candidates` | `id`, `workspace_id`, `session_id`, `text`, `type`, `reason`, `status`, `source_message_id`, `created_at` |
| `context_items` | `id`, `trace_id`, `workspace_id`, `source_type`, `source_id`, `rank`, `token_estimate`, `included`, `reason` |
| `source_lineage` | `id`, `trace_id`, `output_ref`, `source_type`, `source_id`, `span_id`, `note` |
| `file_artifacts` | `id`, `workspace_id`, `path`, `mime_type`, `sha256`, `created_at`, `deleted_at` |

关系：Workspace 拥有所有数据；Session 拥有 Message；Memory 和 Candidate 引用来源 Message；ContextItem 和 Lineage 引用 Trace/Span。

## 隔离和删除

所有用户数据表必须包含 `workspace_id`。查询必须按 Workspace 过滤。除非运行明确的迁移/导出服务，否则禁止跨 Workspace 读取。

软删除使用 `deleted_at`。默认查询排除已删除行。用户请求数据擦除时必须硬删除，并尽可能删除或脱敏派生索引和来源链路。

## 记忆类型

| 类型 | 示例 |
|---|---|
| `profile` | 用户偏好简洁的工程回答。 |
| `project` | Cogito-Agent MVP 使用本地 SQLite。 |
| `relationship` | 联系人或组织事实。 |
| `task` | 待跟进事项或承诺。 |
| `preference` | 输出格式或工作流偏好。 |
| `episodic` | 重要历史交互。 |
| `skill` | 可复用工作流经验。 |

## 记忆生命周期

```text
candidate -> pending -> accepted -> consolidated -> indexed
-> stale -> archived/deleted
```

MVP 可以只实现 `candidate`、`pending`、`accepted` 和 `deleted`。

## 候选记忆提取

每个完成的 turn 后，只提取持久事实、用户偏好、项目决策、任务和纠正信息。不要在没有明确接受的情况下存储 secret、临时指令、原始凭证或敏感个人数据。

候选字段：`text`、`type`、`reason`、`confidence`、`sensitivity`、`source_message_id`。

## 接受和纠正

已接受记忆变为可检索。被拒绝候选只作为审计/调试数据保留，除非用户要求硬删除。纠正会创建新的记忆版本，并将旧版本标记为 `stale` 或 `archived`。

## 索引和检索

MVP 使用 SQLite FTS5 或简单关键词搜索。排序依据：Workspace 匹配、类型优先级、时间新近度、置信度、关键词直接匹配和来源可靠性。未来可加入 Embedding 和 BM25/向量混合排序。

## 上下文来源

- 当前用户消息。
- 最近 Session 消息。
- 已接受记忆。
- 相关文件/产物。
- 当前 turn 的工具结果。
- Skill 激活时的 Skill 指令。
- System/Developer 策略文本。

## 排序、裁剪和预算

默认 token 分配：

| 来源 | MVP 预算占比 |
|---|---|
| System/Runtime 指令 | 20% |
| 当前请求 | 必需 |
| 最近消息 | 30% |
| 检索记忆 | 20% |
| 工具/文件上下文 | 20% |
| 响应预留 | 10% |

先裁剪低排序上下文。对已纳入项和高排序但被排除项保留来源链路。只有当源文本超出预算并且摘要可保留链路时才压缩。

## 来源链路

每个依赖记忆、文件、工具或历史消息的答案片段，都应可追踪到 `source_type`、`source_id`、`span_id` 和可选 quote/hash。MVP 可在响应级别而非句子级别存储链路。

## 导出和删除

导出必须包含 Session、Message、Memory、Candidate、Artifact 元数据、Trace 摘要和 Audit 日志。删除必须支持 Workspace 级和 Memory 级删除，并包含索引。

## MVP 行为

单 Workspace、SQLite 表、最近消息上下文、已接受记忆搜索、记忆候选、响应级链路、软删除，以及通过仓储/服务函数进行的手动导出。

## 未来扩展

多 Workspace、记忆审核 UI/API、向量搜索、记忆合并任务、加密存储、备份/恢复、选择性同步和细粒度链路。
