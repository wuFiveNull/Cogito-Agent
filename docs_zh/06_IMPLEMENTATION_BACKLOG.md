# 06 实现 Backlog

## Epic 1: Project Bootstrap

目标：创建最小 Python 包和开发工作流。
范围：包布局、依赖配置、测试配置、lint/type 配置。
可能影响文件：`pyproject.toml`、`src/cogito_agent/`、`tests/`。
依赖：无。
验收标准：包可导入，`pytest` 可运行，Ruff/mypy 命令已文档化。
不在范围内：Runtime 行为。

## Epic 2: Shared Types and Schemas

目标：定义与 provider 无关的数据契约。
范围：RuntimeEvent、turn 状态、Capability Manifest、Policy 请求/决策、Trace/Span 模型。
可能影响文件：`src/cogito_agent/shared/`、`src/cogito_agent/runtime/`。
依赖：Epic 1。
验收标准：Schema 能校验正确和错误 fixture。
不在范围内：持久化和执行。

## Epic 3: Storage Layer

目标：本地持久化 Session、Message、Memory、Trace、Audit 和调用记录。
范围：SQLite schema 初始化器、Repository、Workspace 过滤、软删除。
可能影响文件：`src/cogito_agent/storage/`、`tests/storage/`。
依赖：Epic 2。
验收标准：CRUD 测试通过；所有用户数据查询都要求 `workspace_id`。
不在范围内：向量搜索。

## Epic 4: Trace and Audit MVP

目标：从第一个 demo 开始具备执行可观测性。
范围：Trace/Span 创建、Model/Tool 日志、Audit 记录、脱敏 helper。
可能影响文件：`src/cogito_agent/trace/`、`src/cogito_agent/governance/`。
依赖：Epic 3。
验收标准：测试 turn 创建 Trace、Span、Audit 记录和脱敏摘要。
不在范围内：确定性回放。

## Epic 5: Runtime Kernel MVP

目标：实现 turn 生命周期和状态机。
范围：事件摄入、状态迁移、预算检查、结果组合、失败处理。
可能影响文件：`src/cogito_agent/runtime/`。
依赖：Epic 2-4。
验收标准：迁移测试覆盖合法/非法路径；一个简单 turn 可完成。
不在范围内：后台执行。

## Epic 6: Policy Engine MVP

目标：执行静态能力决策。
范围：Policy 矩阵、审批请求模型、deny/allow/audit 行为。
可能影响文件：`src/cogito_agent/governance/`。
依赖：Epic 2 和 4。
验收标准：测试覆盖 allow、allow_with_audit、require_approval、deny、escalate。
不在范围内：Policy DSL 和 Grant。

## Epic 7: Capability Registry MVP

目标：通过 Manifest 注册并调用安全本地工具。
范围：Manifest loader、Schema 校验、结果规范化、一两个安全工具。
可能影响文件：`src/cogito_agent/capability/`。
依赖：Epic 4-6。
验收标准：非法 Manifest 失败；工具调用经过 Policy 和 Trace。
不在范围内：MCP、Plugin、Shell 执行。

## Epic 8: Memory and Context MVP

目标：检索有用本地上下文并提出记忆候选。
范围：Memory 表、Candidate 提取、已接受记忆检索、上下文排序/裁剪。
可能影响文件：`src/cogito_agent/memory/`、`src/cogito_agent/context/`。
依赖：Epic 3-5。
验收标准：已接受记忆可被检索；Candidate 链接到来源 Message。
不在范围内：Embedding 和自动合并。

## Epic 9: CLI Chat Loop

目标：提供可运行的本地交互路径。
范围：CLI 命令、Session 创建、行内审批提示、turn 显示。
可能影响文件：`src/cogito_agent/cli/`。
依赖：Epic 5-8。
验收标准：用户可以本地聊天并查看持久化 Message/Trace。
不在范围内：TUI、Web UI、流式输出。

## Epic 10: API Chat Endpoint

目标：在 CLI 稳定后通过 HTTP 暴露 Runtime。
范围：FastAPI app、chat endpoint、session endpoint、approval resume endpoint。
可能影响文件：`src/cogito_agent/api/`。
依赖：Epic 9。
验收标准：API 测试创建 turn 并恢复审批。
不在范围内：除本地/dev token 外的认证。

## Epic 11: Model Provider Adapter

目标：将 Runtime 连接到一个真实模型提供方。
范围：Provider-neutral 接口、OpenAI 兼容或本地 provider 实现、用量日志。
可能影响文件：`src/cogito_agent/models/`。
依赖：Epic 4 和 5。
验收标准：Adapter 返回规范化 Message/Tool Intent 并记录用量。
不在范围内：多 Provider 路由。

## Epic 12: End-to-End Local Demo

目标：证明 MVP 可从干净 checkout 运行。
范围：种子配置、demo 脚本/文档、一个安全工具、一个记忆、一轮聊天。
可能影响文件：`docs/`、`src/cogito_agent/cli/`、`tests/e2e/`。
依赖：Epic 1-11。
验收标准：文档化命令完成一次本地 turn，并输出 Trace/Audit。
不在范围内：生产部署。

## Epic 13: Skill Runtime V1

目标：执行已批准的交互式 Skill。
范围：Skill Manifest、Workspace Copy、Step Runner、Step Trace、权限预检、运行历史。
可能影响文件：`src/cogito_agent/skill/`、`src/cogito_agent/capability/`。
依赖：Epic 12。
验收标准：一个示例 Skill 可交互式运行，并记录 Step Span。
不在范围内：后台 Skill 和市场导入。

## Epic 14: Autonomy V1

目标：引入受控后台行为。
范围：Scheduler 模型、安静时间、Notification Gate、去重、反馈记录。
可能影响文件：`src/cogito_agent/autonomy/`、`src/cogito_agent/governance/`。
依赖：Epic 13。
验收标准：计划 dry-run job 创建 Trace/Audit 并遵守安静时间。
不在范围内：外部推送渠道和完全自主动作。
