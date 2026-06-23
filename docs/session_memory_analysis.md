# 会话管理与跨会话长期记忆系统分析

> 分析对象：**Cogito-Agent**、**Akashic Agent**、**Hermes Agent**
> 日期：2026-06-22
> 范围：会话生命周期管理、上下文构建、跨会话长期记忆的持久化与检索

---

## 1. 概述

### 三个项目简介

| 项目 | 定位 | 语言 | 架构风格 |
|------|------|------|----------|
| **Cogito-Agent** | 本地优先的个人 Agent 运行时 | Python 3.12+ | 六边形架构（Ports/Adapters），Application Service |
| **Akashic Agent** | 会主动找你的 AI 伙伴 | Python 3.12+ | 事件驱动 + 插件链 + Phase 生命周期 |
| **Hermes Agent** | 自我进化的 AI Agent（Nous Research） | Python 3.11+ | 插件化 + 可插拔 Provider + 辅助模型 |

三个项目共享核心挑战：**如何在一个会话内管理上下文窗口，以及在会话之间保持对用户的长期记忆**。

---

## 2. Cogito-Agent

### 2.1 会话管理

#### 2.1.1 数据模型

会话存储在 SQLite 数据库的 sessions 表中，由 SessionRepository 封装。每个会话包含 id（UUID v4）、workspace_id、title（默认 New Chat，最长 80 字符）、created_at、updated_at、deleted_at（软删除支持）。消息存储在 messages 表中，包含 role、content、session_id、workspace_id 等字段。

#### 2.1.2 会话生命周期

由 SessionApplicationService（src/cogito_agent/application/sessions.py）管理：

- create() -- 新建会话
- rename() -- 重命名（最多 80 字符，首尾空格折叠）
- branch() -- 从已有会话复制全部消息创建分支会话
- archive() -- 软删除（标记 deleted_at）
- delete() -- 硬删除（物理删除）

分支（Branch）机制：branch() 读取源会话的全部消息，在目标会话中逐条复制形成完整拷贝。这是 Cogito-Agent 中唯一的多会话编排能力。

#### 2.1.3 一次对话回合（Turn）的完整流程

由 RuntimeKernel（src/cogito_agent/runtime/kernel.py）驱动，通过状态机（TurnStateMachine）控制：

TurnState: received -> loading_session -> building_context -> model_calling -> planning_tool -> composing_result -> completed（或 failed / denied / waiting_approval）

process() / process_stream() 的管道：
1. _prepare_turn_setup() -- 重置状态，创建 Trace + Span
2. _run_pre_model_phase() -- 持久化用户消息 -> 构建上下文 -> 预算/策略检查
3. _generate_reply() -- 模型调用（含工具 schema）
4. _dispatch_tools() 循环 -- 执行工具（最多 max_tool_rounds 轮）
5. _run_after_turn() -- 结果组装 -> 持久化 -> 更新摘要 -> 记忆 Consolidation -> 审计

#### 2.1.4 上下文构建

ContextEngine.build()（src/cogito_agent/context/engine.py）组装最终的上下文列表，按顺序包含：

1. System 指令（固定基础提示）
2. 当前用户消息（必含，不参与预算裁剪）
3. Session 摘要（增量式，由 _update_session_summary() 维护）
4. Memory 文件（SELF.md、MEMORY.md、RECENT_CONTEXT.md、SESSION_SUMMARY.md）
5. 最近消息（最近 6 条，不参与预算裁剪）
6. 检索到的记忆（通过混合检索获得，标记 retrieval_source: resident/dynamic）
7. 工具结果
8. 文件上下文

Token 预算总额 4096 token，按来源类型分配：

| 来源类型 | 占比 | Token 上限 |
|----------|------|-----------|
| system | 15% | ~614 |
| recent_messages | 35% | ~1434 |
| retrieved_memory | 10% | ~410 |
| memory_file | 10% | ~410 |
| tool_file_context | 20% | ~819 |
| response_reserve | 10% | ~410 |

超过预算的项被标记 included=False，从发送给模型的列表中剔除。

### 2.2 跨会话长期记忆

Cogito-Agent 的记忆系统在 v0.10 后经历重大重构（Memory v2），从基于文件转向结构化数据库 + 文件视图模式。

#### 2.2.1 存储层

主要存储：SQLite memory_items 表。每条记忆包含：id、workspace_id、memory_type、summary、status（active/archived/candidate）、source_ref、confidence、emotional_weight。

支持的 memory_type：
- profile -- 用户画像（身份事实、背景）
- preference -- 偏好
- procedure -- 流程和规则
- task -- 任务
- fact -- 一般事实
- event -- 时间线事件
- _recent_context -- 近期语境压缩摘要（内部类型）
- general -- 其他

辅助存储：Markdown 文件视图。自动从 memory_items 同步的只读文件：MEMORY.md（profile/preference/procedure）、RECENT_CONTEXT.md（JSON 格式近期语境）、SESSION_SUMMARY.md（增量摘要）。

向量索引存储：通过 MemoryEmbeddingIndexService 生成向量（如 text-embedding-v3），用于密集检索。

#### 2.2.2 写入流程：Consolidation（记忆固化）

由 ConsolidationService（src/cogito_agent/memory/consolidation.py）在每次回合后触发：

- 触发条件：自上次 consolidation 新消息数 >= consolidation_min_new（默认 10）
- Backlog 保护：超过 _CONSOLIDATION_GUARD_THRESHOLD（30）时阻塞后续回合

回合完成后：
1. _extract_and_write() -- 仅当阈值满足
   - Step A: LLM 提取
     - history_entries[] -> Memorizer.save(type=event) -> memory_items
     - pending_items[] -> Memorizer.save(type=auto_map) -> memory_items
   - Step B: LLM 压缩近期语境
     - Memorizer.save(type=_recent_context) -> memory_items
     - 结果：active_topics, user_preferences, follow_ups, avoidances, ongoing_threads
   - Step C: 同步 .md 视图文件
     - _sync_memory_md() -> MEMORY.md
     - _sync_recent_context_md() -> RECENT_CONTEXT.md
2. 滑动窗口裁剪（keep_count=20，message_count > keep_count + prev_count 时裁旧消息）

LLM 提取原则：
- 不信任 assistant 的延伸：只根据 USER 明确表达的内容输出
- 保守原则：宁可漏掉，也不要脑补
- 去重：读取最近 10 条 active 记忆作为上下文做无引用去重

#### 2.2.3 检索流程：混合检索

RuntimeKernel._load_context_memories() -> MemoryQueryBuilder.build()（输入 current_message、recent_user_messages、session_topic_summary）-> MemoryRetrievalService.recall(limit=5, min_score=0.35)

混合检索：
- Sparse: BM25/FTS5 全文检索（MarkdownChunkIndex）
- Dense: 向量嵌入检索（DenseRetrievalService）
- Fusion: RRF + recency/confidence/pinned boost

结果：MemoryRecallResult（resident_memories + dynamic_memories），注入 ContextItem（标记 retrieval_source: resident/dynamic）

#### 2.2.4 查询工具

| 工具名 | 触发场景 | 实现 |
|--------|----------|------|
| recall_memory | 需要回忆细节 | 调 recall_search() -> 混合检索 |
| memory.search | 更彻底搜索 | 调 recall() -> 混合检索 |
| memory.store_candidate | 用户表达偏好/事实 | Memorizer.save() |

### 2.3 关键设计决策

1. 结构化记忆优先：所有记忆写入 memory_items 表，Markdown 文件降级为只读视图
2. 消极提取：LLM 提取明确禁止脑补
3. 增量会话摘要：每次回合后更新，保留核心信息同时缩减上下文
4. Token 预算制：严格按类分配预算，超限自动裁剪
5. 全链路治理：每次写操作经审计，每次检索有 Trace

---

## 3. Akashic Agent

### 3.1 会话管理

采用事件驱动架构，通过 CoreRunner（agent/core/runner.py）统一分发。

#### 3.1.1 消息入口

InboundMessage -> AgentCore.process()；SpawnCompletionItem -> process_spawn_completion_event()

AgentCore 由 6 个 Phase 串联：BeforeTurn -> BeforeReasoning -> PromptRender -> Reasoner -> AfterReasoning -> AfterTurn。每个 Phase 可通过 PhaseModule 插件或 EventBus 装饰器扩展。

#### 3.1.2 会话持久化

通过 SessionServices 协议抽象。关键事件 TurnCommitted 包含输入消息、回复、所用工具、思考过程，是记忆提取的触发器。

### 3.2 跨会话长期记忆（Markdown 文件层）

五个 Markdown 文件存储在 ~/.akashic/workspace/memory/ 下。

#### 3.2.1 文件体系

| 文件 | 写入者 | 读取场景 | 用途 |
|------|--------|----------|------|
| MEMORY.md | Optimizer（定时） | 每轮 system prompt | 长期记忆 |
| SELF.md | Optimizer（定时） | 每轮 system prompt | 自我认知 |
| HISTORY.md | Consolidation（追加） | grep 检索 | 时间线日志 |
| RECENT_CONTEXT.md | Consolidation | 每轮 system prompt | 近期摘要 |
| PENDING.md | Consolidation（追加） | Optimizer 消费 | 待归档缓冲区 |

#### 3.2.2 Consolidation 流程

回合完成 -> TurnCommitted 事件 -> 检查新消息数 >= min（默认 10）-> 一次 LLM 调用提取：
1. history_entries[] - 时间线事件
2. pending_items[] - 长期事实候选（tag: identity/preference/...）

写入 HISTORY.md（幂等）、PENDING.md（幂等）、RECENT_CONTEXT.md（LLM 压缩）、journal/YYYY-MM-DD.md

幂等性保证：consolidation_writes.db（SQLite）用 source_ref 做主键，配合文件内隐藏标记双重保障。

PENDING.md 两阶段提交（崩溃安全）：
- snapshot_pending() -> rename PENDING.md -> PENDING.snapshot.md
- commit_pending_snapshot() -> delete snapshot
- rollback_pending_snapshot() -> 合并 snapshot + 新追加 -> 写回

#### 3.2.3 Optimizer：PENDING -> MEMORY

核心设计动机：保护 prompt cache。MEMORY.md 全文注入 system prompt，若每次 consolidation 都改写，prompt cache 永远无法命中。PENDING.md 做缓冲区后，MEMORY.md 的更新频率降到 18 小时一次（memory_optimizer_interval_seconds = 64800）。

consolidation（每 ~10 条消息触发）-> 写入 PENDING.md（不改 MEMORY.md）-> prompt cache 持续命中 -> Optimizer（18 小时一次）-> 合并 PENDING.md -> MEMORY.md -> 清空 PENDING.md

#### 3.2.4 向量层

独立的 memory2.db 向量数据库，通过 ConsolidationCommitted 事件桥接。向量引擎是 plugin，[memory].engine 配置项指定。

### 3.3 Prompt Block 系统

SystemPromptBuilder 按 priority 依次渲染：

| Priority | 块名 | 来源 | 静态 |
|----------|------|------|------|
| 10 | Identity | 工作区路径 | 是 |
| 15 | BehaviorRules | 固定规范 | 是 |
| 20 | SkillsCatalog | skills/ 目录 | 是 |
| 30 | SelfModel | SELF.md | 否 |
| 35 | LongTermMemory | MEMORY.md | 否 |
| 40 | SessionContext | 环境 | 否 |
| 45 | RecentContext | RECENT_CONTEXT.md | 否 |
| 50 | ActiveSkills | 当前技能 | 否 |
| 55 | MemoryBlock | 检索结果 | 否 |

静态块缓存：static block 渲染后缓存，只有 workspace 或 skills 目录变化时重新渲染。

### 3.4 关键设计决策

1. 缓存意识架构：PENDING.md 缓冲层保护 prompt cache，三个项目中最独特的优化
2. 文件优先：记忆以 Markdown 存储，人类可直接阅读编辑
3. 两阶段提交：崩溃安全的 snapshot/commit/rollback
4. 幂等写入：SQLite 索引 + 文件标记双重保障
5. Plugin 式向量引擎：可插拔后端
6. LLM 提取严格约束：宁漏勿编

---

## 4. Hermes Agent

### 4.1 会话管理

SessionDB（hermes_state.py）使用 SQLite + WAL 模式，支持 FTS5 全文搜索。

#### 4.1.1 数据模型

sessions 表：id、parent_session_id、source、model_config、started_at、ended_at、end_reason。消息存储在 messages 表，支持 FTS5。

#### 4.1.2 会话分叉（Session Splitting）

上下文压缩触发时创建新的子会话，通过 parent_session_id 链关联：session_A -> (compression) -> session_B -> (compression) -> session_C

类型区分：
- Root -- 原始会话
- Branch -- 用户主动分支（保持可见）
- Compression child -- 压缩产物（picker 中隐藏）
- Subagent run -- 子 Agent 运行（级联删除目标）

#### 4.1.3 上下文压缩

可插拔 ContextEngine，默认 context_compressor：预检估算 -> 辅助模型摘要 -> 创建新会话。保护机制：protect_first_n=3，protect_last_n=6。

### 4.2 跨会话长期记忆

#### 4.2.1 可插拔 Memory Provider

MemoryProvider ABC 定义标准接口：initialize()、system_prompt_block()、prefetch()、sync_turn()、shutdown()。可选钩子包括 on_session_end()、on_pre_compress() 等。

限制：同时只能激活一个外部 provider。

#### 4.2.2 内置记忆

- 用户画像：周期性提醒 Agent 总结用户知识
- FTS5 搜索：messages_fts 跨会话全文检索
- 上下文围栏：<memory-context> 标签标注记忆来源

<memory-context>
[System note: The following is recalled memory context, NOT new user input.]
{记忆内容}
</memory-context>

#### 4.2.3 外部提供商

| 提供商 | 特点 |
|--------|------|
| Honcho | dialectic 对话式用户建模 |
| Hindsight | 事后反思提取知识 |
| Holographic | 分布式记忆（固定大小空间） |
| Byterover | 文件系统记忆 |

### 4.3 技能即记忆（Procedural Memory）

技能本身就是长期程序化记忆：Agent 完成复杂任务后自动创建技能，下次匹配时执行并自我优化，长期不用则标记 stale 后归档。

Curator 系统（默认 7 天运行一次）：
- 确定式阶段：超过 30 天未用 -> stale，超过 90 天 -> 归档
- LLM 聚合阶段（默认关）：分析全量技能，合并重叠技能为类级伞技能

### 4.4 关键设计决策

1. 会话即历史链：压缩导致会话分裂，形成可追溯的 parent_session_id 链
2. Provider 化记忆：MemoryProvider ABC 支持即插即用
3. 技能 = 程序化记忆：闭环学习，操作流程可执行、可优化、可归档
4. 辅助模型护城河：压缩、Curator 都用 auxiliary model，不干扰主模型
5. 上下文围栏：<memory-context> 标签防止模型混淆
6. FTS5 跨会话搜索：为 insights 提供聚合能力

---

## 5. 横向对比

### 5.1 会话管理对比

| 维度 | Cogito-Agent | Akashic Agent | Hermes Agent |
|------|-------------|---------------|--------------|
| 存储 | SQLite（结构化） | SQLite + 事件总线 | SQLite + FTS5 |
| 会话分叉 | branch() 复制全量消息 | 事件 outbound 分发 | 压缩分叉（parent_session_id 链） |
| 状态机 | TurnStateMachine（8 状态） | 6 Phase + EventBus | run_conversation() |
| 窗口管理 | 基于 consolidation 滑动窗口 | TurnCommitted 的 history_window | protect_first_n/last_n |
| 中断恢复 | resume() + interrupt() | spawn completion 事件 | Ctrl+C / /stop |

### 5.2 长期记忆对比

| 维度 | Cogito-Agent | Akashic Agent | Hermes Agent |
|------|-------------|---------------|--------------|
| 主要存储 | memory_items 表（结构化） | Markdown 文件 + memory2.db | 可插拔 Provider + FTS5 |
| 记忆类型 | profile/preference/fact/event | identity/preference/key_info | 用户画像 + 技能 |
| 提取方式 | LLM consolidation（异步） | LLM consolidation（自动） | Provider.prefetch()/sync_turn() |
| 写入粒度 | 每次回合后检查阈值 | 每次回合后检查阈值 | 每轮同步 |
| 去重 | 无引用去重 | SQLite 主键 + 文件标记 | Provider 自定 |
| 缓存策略 | 无特殊优化 | PENDING.md 缓冲保护 cache | 辅助模型做护城河工作 |
| 向量检索 | dense + sparse + RRF fusion | plugin（default_memory） | 由 Provider 决定 |
| 可观测性 | Trace + Audit 全链路 | Dashboard + DEBUG 日志 | Insights + state DB |

### 5.3 上下文构建对比

| 维度 | Cogito-Agent | Akashic Agent | Hermes Agent |
|------|-------------|---------------|--------------|
| 构建方式 | ContextEngine.build() | SystemPromptBuilder 拼接 | build_turn_context() + MemoryManager |
| 记忆注入 | ContextItem -> PromptBuilder | PromptBlock 链（priority 35,55） | prefetch() + system_prompt_block() |
| 预算控制 | Token 预算制（按类型分配） | 无显式预算 | threshold_percent 触发压缩 |
| 记忆标记 | source_type（resident/dynamic） | PromptBlock label | <memory-context> 围栏 |
| 压缩 | 滑动窗口 + LLM 摘要 | RECENT_CONTEXT.md | 辅助模型 + 会话分裂 |

### 5.4 架构哲学对比

| 项目 | 核心理念 | 最独特之处 |
|------|---------|-----------|
| Cogito-Agent | 治理优先 | 六边形架构 + Ports/Adapters，全链路审计追踪 |
| Akashic Agent | 缓存意识 | PENDING.md 缓冲 + 两阶段提交崩溃安全 |
| Hermes Agent | 可进化 | Curator 技能管理 + 可插拔 Provider + 会话分裂 |

---

## 6. 设计启示

### 6.1 共同模式

1. UUID 作为 ID：所有项目使用 UUID v4
2. SQLite 为核：兼顾本地性和可靠性
3. 状态机保护：显式的状态管理防止并发冲突
4. 可追溯性：Trace ID、事件总线、Session chain 都支持回溯

### 6.2 共同挑战

1. 提取 vs 完整性：三个项目都采用宁漏勿编原则
2. 检索 vs 上下文预算：需要分层优先级管理
3. 新鲜度 vs 稳定性：过于频繁的更新破坏 prompt cache

### 6.3 适合 Cogito-Agent 的借鉴点

1. PENDING 缓冲层：借鉴 Akashic 的设计保护 prompt cache
2. 技能程序化记忆：借鉴 Hermes 的技能即记忆理念
3. 会话链追踪：Hermes 的 parent_session_id 链更完整地保留历史线索
4. Memory Provider 插件化：让第三方实现自定义记忆后端
5. 协作缓存：借鉴 Akashic 的 is_static + cache_signature() 设计
6. Curator 自动维护：对积累的记忆做自动生命周期管理

---

*本文基于 Cogito-Agent v0.17.0-dev、Akashic Agent（2026-06）、Hermes Agent（2026-06）源码分析。*
