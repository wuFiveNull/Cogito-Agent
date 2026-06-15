# 01 项目规格

## 身份

| 字段 | 值 |
|---|---|
| 项目名称 | Cogito-Agent |
| 一句话描述 | 一个本地优先的个人 Agent Runtime，具备记忆、受治理能力、可追踪执行、可复用 Skill 和受约束的主动行为。 |
| 核心目标 | 帮助单个用户在长期个人上下文中安全运行可复用的 Agent 工作流。 |
| 目标用户 | 希望拥有本地个人助理的技术用户，用于编码、研究、规划和信息管理。 |

## 主要用例

- 通过 CLI 或 API 与持久会话聊天。
- 将相关项目/用户记忆检索进模型上下文。
- 通过能力注册表调用已批准的本地工具。
- 记录 Trace、Audit、模型调用、工具调用和来源链路。
- 从完成的 turn 中提取待审核记忆候选。
- 后续支持 Skill 和有限的主动/后台任务。

## 非目标

- 多租户 SaaS。
- MVP 阶段的完整桌面或 Web UI。
- MVP 阶段的自主外部消息发送。
- MVP 阶段的插件市场安装。
- MVP 阶段的分布式执行、云同步或高可用存储。

## 原则

本地优先：状态、记忆、Trace、文件和配置默认存储在本地。未来任何远程提供方都必须可替换并显式配置。

安全优先：每次能力调用都按 `Actor + Capability + Resource + Operation + Context -> Decision` 评估；写入、发送、删除和执行操作必须审计，并可能需要审批。

## 范围

| 阶段 | 范围 |
|---|---|
| MVP | Python 包、SQLite 存储、CLI 聊天循环、单一模型适配器、Runtime 状态机、Policy MVP、能力注册表、Trace/Audit 日志、基础记忆/上下文检索、本地 demo。 |
| V1 | HTTP API、Skill Runtime、工作区 Skill 副本、更完整的记忆审核/纠正、BM25/向量检索、审批持久化、导出/删除流程。 |
| V2 | Proactive Loop、Scheduler、Drift Runtime、多工作区、Plugin/MCP 集成、Subagent、云迁移适配器。 |

## 推荐技术栈

- 语言：Python 3.12+。
- API：CLI MVP 稳定后使用 FastAPI。
- 存储：MVP 使用 SQLite；如果 schema 复杂度增加，再使用 SQLAlchemy 或 SQLModel。
- 校验：RuntimeEvent、Manifest、Policy 输入和日志使用 Pydantic 模型。
- 测试：pytest。
- 质量：Ruff 和 mypy。
- 检索：MVP 使用 SQLite FTS5；后续再加入向量索引。

## 仓库结构

```text
src/cogito_agent/
  runtime/
  models/
  storage/
  memory/
  context/
  capability/
  governance/
  trace/
  cli/
  api/
tests/
docs/
```

## 包/模块边界

| 包 | 负责 | 不负责 |
|---|---|---|
| `runtime` | Turn 生命周期、状态机、编排 | Provider SDK、具体工具代码、SQL 细节 |
| `models` | 与提供方无关的模型接口 | 策略或存储决策 |
| `storage` | 表、仓储、迁移 | Runtime 分支逻辑 |
| `memory` | 记忆实体、生命周期、检索 | Prompt 组装策略 |
| `context` | 上下文排序、裁剪、来源链路 | 长期存储持久化 |
| `capability` | Manifest、注册表、调用接口 | 审批决策 |
| `governance` | 策略、审批、审计决策 | 工具执行 |
| `trace` | Trace/Span/模型/工具日志 | 业务策略 |
| `cli`/`api` | 渠道适配 | Runtime 内部细节 |

禁止依赖：`runtime` 必须调用抽象接口而非具体 provider；`capability` 不得绕过 `governance`；`memory` 不得直接调用模型；`api` 不得绕过应用服务直接写存储。

## 假设

- MVP 是单用户、本地运行。
- 初始实现使用 Python。
- 模型凭证通过本地环境变量或配置提供，永不提交到 git。
- 根目录现有架构文档作为参考材料，不作为实现合同。

## 未决问题

- 第一个模型提供方选 OpenAI 兼容 HTTP、本地 Ollama，还是两者都支持？
- MVP 中记忆接受是手动审核，还是只记录 pending？
- SQLite 迁移从一开始使用 Alembic，还是先用简单 schema 初始化器？
- 能力工具应执行怎样的本地文件沙箱规则？
