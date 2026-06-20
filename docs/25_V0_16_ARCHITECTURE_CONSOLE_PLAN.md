# v0.15–v0.19 Architecture Implementation & Console 落地计划

**状态：** In Progress — v0.15 Production Foundation complete, v0.16 Phase 0/1/2 complete  
**日期：** 2026-06-19  
**基线：** v0.15.0-dev，1300+ tests passed，Console MVP 已覆盖 Chat、Memory、Approval、Trace、Audit、Autonomy、Config、Doctor、Inbox、Workspace Files、Artifacts、Drift、Overview  
**上游依赖：** ✅ v0.15 Production Packaging 最小闭环已完成（配置/health/日志/WAL/Web安全/测试）  
**目标文档：** `Cogito-Agent_架构设计文档.md`

---

## 1. 目标

将当前系统从“功能丰富的开发版 Runtime”推进为可长期运行的本地 Agent 产品。计划同时推进两条主线：一条完善 Runtime、Reasoning、Plugin、Task、Multi-Agent 和生产运维等后端能力；另一条将 Console MVP 升级为完整的本地 Agent 工作台，使架构文档中的主要运行平面都可以被用户观察、操作和追溯。

本计划交付以下结果：

1. 统一的 Console 信息架构、视觉系统和交互规范。
2. 面向日常使用的 Chat、Knowledge、Tasks、Inbox 工作区。
3. 面向能力管理的 Skills、Capabilities、MCP、Providers 工作区。
4. 面向自主运行的 Scheduler、Autonomy、Drift 工作区。
5. 面向安全控制的 Approvals、Policies、Secrets、Audit 工作区。
6. 面向系统诊断的 Traces、Usage、Doctor、Backup 工作区。
7. 面向多工作区和 Subagent 的 Agents 工作区；该部分必须建立在真实持久化和治理能力上，不制作假 UI。

最终用户应能从一次 Agent 回复反向查看：使用了哪些上下文、记忆、文件、模型、工具和策略，产生了哪些 Artifact、通知、审计和后续任务。

---

## 2. 产品定位

### 2.1 用户

- 主要用户：单机部署 Cogito-Agent 的个人用户。
- 高级用户：需要查看 Trace、策略、Skill 和文件索引的开发者。
- 暂不服务：多租户组织、公众 SaaS、匿名访问者。

### 2.2 核心使用场景

1. 与 Agent 进行长期、多会话对话。
2. 查看本轮回复使用了什么信息以及为什么这样回答。
3. 审核记忆候选、任务候选、审批请求和主动通知。
4. 管理本地文件索引、Artifact 和知识检索。
5. 运行 Skill、查看步骤状态、恢复审批后的执行。
6. 创建和管理定时任务。
7. 查看后台 Drift 的运行、预算、产物和错误。
8. 诊断 Provider、Secrets、数据库、迁移和运行服务。
9. 备份、导出和恢复本地数据。

### 2.3 成功标准

- 日常操作不需要切回 CLI。
- 所有写操作都有明确影响说明、确认、审计和错误反馈。
- 任一关键对象最多 2 次点击可进入其 Trace、Audit 或关联对象。
- Desktop 端核心页面 Lighthouse Accessibility 不低于 95。
- 360px 宽度下核心 Chat、Inbox 和 Approval 流程可用。
- Console 不泄露 Secret、Bearer Token、密码、原始异常栈或未脱敏工具结果。
- 页面首个有意义内容在本地环境下 500ms 内出现；大列表采用分页或游标。

---

## 3. 范围边界

### 3.1 本计划包含

- Console 全局 Shell 和设计系统。
- 现有页面的信息架构重组和交互升级。
- 架构平面尚缺失的管理页面。
- 为 UI 服务的 Application Service 和只读/变更 API。
- 可访问性、响应式、键盘操作、错误状态和空状态。
- UI 安全、CSRF、防重复提交、审计和回归测试。

### 3.2 本计划不包含

- 多用户、OAuth、RBAC 和组织管理。
- 云同步、分布式任务队列和高可用部署。
- Plugin Marketplace。
- Telegram、飞书等外部渠道的真实实现；只提供 Channel/Delivery 状态入口。
- 用前端重写后端业务规则。
- React、Vue、Node 构建链和远程 CDN。
- 在 Subagent 后端持久化、恢复、治理未完成前制作“多 Agent 编排器”演示页面。

---

## 4. 技术决策

### 4.1 前端栈

继续使用：

- FastAPI：路由、Application Service 接入、SSE。
- Jinja2：首屏和服务端组件渲染。
- htmx：局部更新、表单提交、轮询和渐进增强。
- Vanilla JavaScript：Command Palette、快捷键、可调整面板、局部客户端状态。
- CSS Custom Properties：Design Token、主题和响应式布局。
- 本地 SVG Icon Sprite：禁止使用 Emoji 作为正式导航图标。

不新增 SPA 构建系统。所有静态资源进入 wheel，不依赖 CDN。

### 4.2 页面响应策略

- 首屏：服务端完整 HTML。
- 列表过滤：GET + query string，可复制链接，可后退恢复。
- 写操作：POST-Redirect-GET 或 htmx partial，必须支持幂等保护。
- Chat：SSE 流式输出。
- 状态刷新：低频 htmx polling；仅 Chat/运行事件使用 SSE。
- 大数据：服务端分页，不将完整 Trace/Audit 列表注入 DOM。

### 4.3 后端边界

Console Router 只负责：

1. 解析和校验请求。
2. 调用 Application Service。
3. 将 ViewModel 交给模板。

Console Router 不直接拼装复杂 SQL，不复制 Runtime/Governance 规则，不直接修改存储。现有直接访问 Repository 的页面逐步迁移到服务层。

---

## 5. 视觉与交互方向

### 5.1 设计主题：Cognitive Operations Desk

界面表现为“本地认知系统的操作台”：克制、技术化、有证据感，但不做传统灰色企业后台。

- 主色：深石墨或暖灰纸面。
- 状态色：信号青用于运行，琥珀用于待处理，朱红用于风险，苔绿用于完成。
- 排版：正文使用可本地打包的 Atkinson Hyperlegible；代码、ID、Trace 使用 IBM Plex Mono。
- 视觉记忆点：每个 Agent Turn 以一条可展开的“执行脉冲”呈现，串联 Context、Model、Tool、Policy、Artifact。
- 图形：细线、时间刻度、状态灯和局部网格；不使用紫色渐变、玻璃拟态或通用 Admin Dashboard 模板。

### 5.2 全局布局

Desktop：

```text
┌──────────────┬──────────────────────────────────────────┐
│ Workspace    │ Top Bar: breadcrumb / search / status    │
│ Navigation   ├───────────────────────────┬──────────────┤
│              │ Main Workspace            │ Inspector    │
│              │                           │ optional     │
│              ├───────────────────────────┴──────────────┤
│              │ Runtime status / pending actions         │
└──────────────┴──────────────────────────────────────────┘
```

Mobile：

- Sidebar 变为抽屉。
- Inspector 变为底部 Sheet。
- Command Palette 保留。
- 数据表自动切换为卡片列表，不依赖横向滚动完成主要操作。

### 5.3 导航分组

```text
Home
  Overview
  Inbox

Work
  Chat
  Tasks
  Artifacts

Knowledge
  Memories
  Workspace Files
  Search

Automation
  Schedules
  Autonomy
  Drift

Capabilities
  Skills
  Tools
  MCP Servers
  Providers

Governance
  Approvals
  Policies
  Secrets
  Audit

Observe
  Traces
  Usage
  Replay

System
  Configuration
  Doctor
  Backup & Export
```

Agents 在持久化能力完成后加入一级导航；在此之前不显示不可用入口。

---

## 6. Design System

### 6.1 Token

建立以下 CSS Token：

- Color：canvas、surface、surface-raised、text、text-muted、border、accent、success、warning、danger、info。
- Typography：display、body、mono、字号、行高、字重。
- Spacing：4/8/12/16/24/32/48/64。
- Radius：2/6/10；避免所有组件使用相同大圆角。
- Elevation：仅 Inspector、Popover、Dialog 使用。
- Motion：120ms、180ms、260ms；支持 `prefers-reduced-motion`。
- Layout：sidebar width、inspector width、content max width、table row height。

### 6.2 基础组件

以 Jinja macro/partial 实现：

- Button、IconButton、ButtonGroup。
- TextField、SearchField、Select、Checkbox、Textarea。
- Badge、StatusDot、RiskBadge、CountBadge。
- Card、Metric、DefinitionList。
- DataTable、ResponsiveList、Pagination。
- Tabs、Breadcrumb、Dropdown、CommandPalette。
- Alert、Toast、InlineError、EmptyState、Skeleton。
- Modal、ConfirmDialog、Drawer、InspectorPanel。
- Timeline、SpanTree、Waterfall、EventPulse。
- CodeBlock、JsonViewer、DiffViewer、RedactedValue。
- MarkdownContent，使用严格 allowlist 清洗。

### 6.3 状态规范

每个页面必须实现：

- Loading。
- Empty。
- Partial data。
- Permission denied。
- Validation error。
- Recoverable failure + Retry。
- Terminal failure + Trace link。
- Success confirmation。

禁止只显示空表格或通用“Something went wrong”。

---

## 7. 架构文档到 UI 的映射

| 架构平面 | UI 工作区 | 当前状态 | 计划动作 |
|---|---|---|---|
| User Entry | Chat、Inbox、Channel Status | 部分完成 | 重构 Chat，增加渠道状态 |
| Gateway | Sessions、Request Metadata、API Health | 隐藏在系统中 | 在 Inspector/Doctor 中可见 |
| Runtime Kernel | Turn Pulse、Run State、Budget | Trace 中部分可见 | 增加实时 Turn Inspector |
| Context & Reasoning | Context Inspector、Knowledge Search | 部分完成 | 展示 included/excluded、token、lineage |
| Capability | Skills、Tools、MCP、Providers | 缺少主要页面 | 新建工作区 |
| Memory | Memories、Candidates、Files | 已有基础页 | 合并为 Knowledge 体验 |
| Autonomy | Inbox、Schedules、Decisions、Drift | 大部分已有 | 重组流程和关联导航 |
| Governance | Approval、Policy、Secrets、Audit | 部分完成 | 新建 Policy/Secrets，强化变更确认 |
| Trace | Trace Explorer、Replay、Usage | 已有基础页 | 增加 waterfall、聚合和比较 |
| Storage | Files、Artifacts、Backup、Migrations | 部分完成 | 新建 Backup & Export |
| Multi-Agent | Agents、Subagent Runs | 后端能力不足 | 后端完成后落地 |

---

## 8. 页面设计与功能需求

### 8.1 Overview

目标：回答“系统现在是否健康、有什么需要我处理、Agent 最近做了什么”。

内容：

- Attention Queue：待审批、失败投递、待审核记忆、失败 Drift、Provider 风险。
- Runtime Health：DB、Provider、Secrets、Daemon、Scheduler。
- Activity Stream：Turn、Skill、Drift、Autonomy、Artifact 的统一时间线。
- Usage Snapshot：24h/7d 的模型调用、工具调用、失败率、平均延迟。
- Quick Actions：New Chat、Run Skill、Scan Workspace、Create Schedule、Backup。

验收：不能只保留当前统计卡片；每个指标必须可下钻。

### 8.2 Chat Workspace

布局：会话列表 + 对话区 + 可选 Inspector。

功能：

- 创建、切换、重命名、归档、删除会话。
- Markdown、安全代码块、引用、Artifact 卡片。
- 流式状态：Thinking、Calling Tool、Awaiting Approval、Retrying、Completed。
- Tool Call 卡片展示参数摘要、策略决策、耗时、脱敏结果。
- Inline Approval：明确操作、资源、风险和副作用。
- Stop/Retry/Copy/Branch conversation。
- Turn Inspector：Context、Memory、Files、Model、Tools、Budget、Trace。
- 长消息虚拟化不是首期要求，但必须分页加载历史。

新增后端：会话重命名、分页消息、停止当前 Turn、从某条消息派生会话。

### 8.3 Knowledge Workspace

整合 Memories、Candidates、Workspace Files 和 Search。

功能：

- 全局混合搜索，按 memory/file/artifact/session 过滤。
- 搜索结果展示评分构成、来源、行号和更新时间。
- Memory Review 双栏界面，支持 Accept/Edit/Reject/Merge/Pin/Archive。
- 冲突和重复候选对比视图。
- 文件索引状态、chunk 数、hash、最后扫描时间、错误原因。
- 文件详情提供 chunk 预览和“在哪些回答中被使用”。
- Artifact 支持 Markdown/JSON/Text 预览、下载、删除和来源 Trace。

禁止首期实现力导向知识图谱；当前数据关系不足以支撑可靠图谱。

### 8.4 Tasks

任务候选目前由 `task_extraction` 产生 Artifact，但没有正式任务域。分两步：

1. v0.17：只读展示 Task Candidate Artifact，并提供“转为 Memory/忽略”。
2. v0.18：引入正式 Task Repository 后提供状态、截止时间、来源、关联会话和提醒。

没有正式 Task 模型前，UI 不得伪造可执行任务管理能力。

### 8.5 Skills

功能：

- Installed/Builtin/Workspace 三种视图。
- Manifest、版本、风险、权限、输入输出 Schema。
- Run 表单根据 input schema 自动生成。
- Dry Run / Preflight：展示将调用的能力和审批要求。
- Run Detail：步骤时间线、输入输出、Artifact、Inbox、Trace、Audit。
- Awaiting Approval 后从原步骤恢复。
- 版本变更比较和 major version 重新审批提示。

新增后端：Skill 查询服务、运行历史分页、Manifest diff、取消运行。

### 8.6 Tools / Capabilities

功能：

- Capability 列表、来源、风险、幂等性、Schema、授权场景。
- 调用历史和失败率。
- 只读 Test Console；写操作测试必须走 Governance 和 Approval。
- 显示哪些 Skill、Schedule、MCP Server 引用了该能力。

禁止从 UI 绕过 CapabilityRegistry 直接执行工具实现。

### 8.7 MCP Servers

功能：

- Server 状态、transport、同步时间、工具数量、错误摘要。
- Add/Edit/Disable/Remove 配置。
- Sync capabilities。
- Server Detail 展示导入工具和 Schema。

安全：配置中的 token 只允许 secret reference，不接受明文持久化。

### 8.8 Providers

功能：

- Provider、Base URL、Default Model、Streaming、Secret 状态。
- 本地配置测试和显式 Live Test。
- 延迟、错误率、最近模型调用。
- 默认 Provider 切换必须审计。

真正的动态 Model Router 不属于纯 UI 工作；路由策略后端完成后再增加规则编辑器。

### 8.9 Schedules

功能：

- List/Calendar 两种视图。
- 创建一次性、间隔、每日任务；Cron 仅在后端支持后开放。
- 目标 Skill/Capability、参数、Workspace、quiet hours、预算和重试。
- Pause/Resume/Run Now/Cancel。
- Job Detail：运行历史、下一次执行、失败和关联 Trace。

写操作必须经过后台场景 Policy 检查。

### 8.10 Autonomy & Drift

重组为一个 Automation 工作区：

- Autonomy：Decision → Outbox → Delivery → Feedback 完整链路。
- Drift：状态、预算、quiet hours、cooldown、运行历史、Artifact。
- Inbox：Read/Dismiss/Retry/Feedback，与来源 Decision/Skill/Trace 双向链接。
- Event Detail：输入事件、dedup key、cost score、gate rules、最终动作。

设置变更采用带 Diff 的确认页，并写入 Audit。

### 8.11 Governance

#### Approvals

- 以风险和过期时间排序。
- 显示 actor、capability、operation、resource、context、side effects。
- Approve once / Reject；长期授权暂不实现。
- 防止重复处理，过期审批不可执行。

#### Policies

- v0.18 首期只读 Policy Matrix 和“解释一次决策”。
- 后续编辑必须引入版本、校验、模拟、回滚和审计，不直接编辑运行中规则。

#### Secrets

- 仅展示 key 名、backend、更新时间和可用性。
- Set/Rotate/Delete 使用受保护表单，页面永不回显 Secret Value。
- 浏览器 autocomplete 关闭，响应禁止缓存。

### 8.12 Trace / Replay / Usage

Trace Detail 使用四种互补视图：

1. Timeline：按时间排序的事件。
2. Tree：父子 Span。
3. Waterfall：耗时和并行关系。
4. Data：脱敏 JSON、Model Call、Tool Call、Lineage。

功能：

- workspace/status/source/time/model/tool 过滤。
- 慢 Trace、失败 Trace、Denied Call 快速筛选。
- 两个 Trace 的摘要比较。
- Replay 为只读重建，不自动重新执行外部副作用。
- Usage 展示调用次数、token、延迟、成本和失败率；没有可靠成本数据时明确标记 unknown。

### 8.13 System

- Config：按来源显示最终值，支持 Default/Config/Env/CLI provenance。
- Doctor：快速检查与 Live Check 分离，Live Check 显式确认。
- Backup & Export：创建、验证、下载、Dry Run Restore、执行 Restore。
- Migration：当前版本、待执行版本和最近结果。
- Diagnostics Bundle：默认排除 Secret 和用户原文。

Restore 属于高风险操作，要求二次确认、备份前置检查和 Audit。

### 8.14 Agents（后端完成后）

前置条件：

- Subagent 元数据持久化。
- 可恢复的任务状态。
- 父子 Trace 关系。
- Agent 级配置、Policy 和 Capability Grant。
- 取消、超时和预算隔离。

满足后交付：Agents 列表、Agent Workspace、Run Tree、任务委派、结果 Merge 和资源使用视图。

---

## 9. API 与 Application Service 计划

### 9.1 统一 ViewModel

所有页面共享：

```python
class ConsolePageContext(TypedDict):
    request: Request
    title: str
    workspace: WorkspaceSummary
    breadcrumbs: list[Breadcrumb]
    menu: list[MenuItem]
    flash: list[FlashMessage]
    system_status: SystemStatusSummary
    csrf_token: str
```

禁止模板直接依赖 sqlite row 的任意字段。

### 9.2 新增服务

- `ConsoleOverviewService`
- `KnowledgeService`
- `SkillManagementService`
- `CapabilityManagementService`
- `AutomationManagementService`
- `GovernanceConsoleService`
- `ObservabilityService`
- `SystemOperationsService`

服务负责 workspace scope、redaction、分页、关联对象和审计上下文。

### 9.3 建议新增端点

```text
GET  /console/search
GET  /console/activity

GET  /console/skills
GET  /console/skills/{name}
POST /console/skills/{name}/run
GET  /console/skill-runs/{id}
POST /console/skill-runs/{id}/cancel

GET  /console/capabilities
GET  /console/capabilities/{name}

GET  /console/mcp
POST /console/mcp
POST /console/mcp/{name}/sync
POST /console/mcp/{name}/disable
POST /console/mcp/{name}/delete

GET  /console/providers
POST /console/providers/{name}/test
POST /console/providers/{name}/select

GET  /console/schedules
POST /console/schedules
GET  /console/schedules/{id}
POST /console/schedules/{id}/pause
POST /console/schedules/{id}/resume
POST /console/schedules/{id}/run
POST /console/schedules/{id}/cancel

GET  /console/policies
POST /console/policies/explain

GET  /console/secrets
POST /console/secrets/{key}/set
POST /console/secrets/{key}/rotate
POST /console/secrets/{key}/delete

GET  /console/usage
GET  /console/backup
POST /console/backup/create
POST /console/backup/restore/preflight
POST /console/backup/restore
```

JSON API 只在 CLI、外部客户端或复杂前端组件确有复用需求时增加，避免为每个 HTML 页面机械复制 API。

---

## 10. 安全要求

### 10.1 必须在 UI 重构前完成的 v0.15 最小项

- CSRF Token：所有状态变更表单。
- Request Body Size Limit。
- SameSite Cookie 或现有 Bearer 模式的明确浏览器认证策略。
- `/api/v1/health`。
- CORS allowlist。
- 安全响应头：CSP、X-Content-Type-Options、Referrer-Policy、frame-ancestors。

### 10.2 页面安全

- 所有动态内容 HTML escape。
- Markdown 使用 allowlist sanitizer。
- JSON/代码块以 textContent 渲染。
- Secret 页面 `Cache-Control: no-store`。
- 所有 URL、header、tool result、audit detail 经过统一 redaction。
- 所有写操作检查 workspace ownership/scope。
- destructive action 使用对象名称确认，而不是只有颜色不同的按钮。
- htmx 请求失败不得回显 Python traceback。

### 10.3 治理要求

- UI 不能成为绕过 PolicyEngine 的第二条写路径。
- Tool、Skill、Schedule、Secret、Backup 写操作必须由 Application Service 调用既有治理路径。
- 所有变更记录 actor、workspace、request_id、trace_id 和 before/after 摘要。

---

## 11. 可访问性与国际化

### 11.1 Accessibility

- WCAG 2.2 AA。
- 全键盘操作，焦点可见。
- Dialog/Drawer 正确管理焦点和 Escape。
- 状态不能只依赖颜色。
- 表单使用显式 label 和错误关联。
- 动画尊重 `prefers-reduced-motion`。
- Span Tree 支持键盘展开/折叠。
- 图表提供文本摘要或数据表替代。

### 11.2 语言

v0.16 保持英文 UI，但所有显示字符串集中管理，不散落在模板中。v0.18 再引入中文语言包；不在模板中同时硬编码中英文。

---

## 12. 测试策略

### 12.1 Unit

- ViewModel 构建、格式化、分页和时间显示。
- Redaction、Markdown sanitizer、URL 构建。
- Design System macro 渲染。
- Policy explain、Schema form generator。

### 12.2 Integration

- 每个 GET 页面 auth/200/404。
- 每个 POST 的成功、校验失败、CSRF 失败、重复提交、无权限。
- Workspace 隔离。
- Secret/XSS/stack trace 回归。
- htmx partial 和普通浏览器请求均可工作。

### 12.3 E2E

使用真实浏览器覆盖：

1. New Chat → stream → tool call → approval → final → trace。
2. Memory candidate → edit → accept → search。
3. Run Skill → approval → resume → artifact → inbox。
4. Create Schedule → run now → trace → pause。
5. Autonomy event → decision → outbox → feedback。
6. Backup → verify → dry-run restore。

### 12.4 Visual Regression

- 1440×900、1024×768、390×844。
- Light/Dark。
- Empty、loading、error、long UUID、long code、中文内容。
- 基准截图按页面区域维护，避免整页动态时间戳导致噪声。

### 12.5 Quality Gate

- 全量 pytest、Ruff、Mypy。
- 无新增未解释 skip。
- Accessibility 自动扫描无 critical/serious。
- 无外部 CDN 请求。
- Wheel 安装后所有模板、字体、图标和 JS 可用。

---

## 13. 分阶段实施

## v0.16 — Console Foundation & Chat

### Phase 0：前置安全与结构，3–5 天

- ✅ CSRF、安全响应头、请求大小限制（v0.15 Production Foundation）。
- ✅ `ConsolePageContext` TypedDict 和 Application Service 边界（`src/cogito_agent/console/context.py`、`src/cogito_agent/console/services/`）。
- ✅ 静态资源版本（`?v={hash}`）和缓存策略（模板全局 `static_version`）。
- ⬜ 建立浏览器 E2E 基础设施（待安排）。

### Phase 1：Design System，5–7 天

- ✅ Token、字体、Icon Sprite。
- ✅ Base layout、responsive shell、Inspector、Command Palette。
- ✅ 基础组件和状态组件。
- ✅ 替换所有 Emoji 导航图标。

### Phase 2：Overview，3–4 天

- ✅ Attention Queue、Health、Activity、Usage snapshot。
- ✅ 指标下钻和 Quick Actions。

### Phase 3：Chat Workspace，7–10 天

- ✅ 三栏布局、会话/消息分页、安全 Markdown、Tool/Approval 卡片。
- ✅ Turn Inspector、stream state、stop/retry 控件。
- ✅ 会话重命名和派生，操作写入 Audit。
- ⬜ 真实浏览器视觉回归和 WCAG 自动扫描（当前浏览器运行环境无法连接健康的 localhost 服务）。

**v0.16 退出标准：** 新 Shell 和 Chat 可作为每日主入口；旧页面仍可通过新导航使用；安全和 E2E Gate 通过。

## v0.17 — Knowledge & Automation

### Phase 4：Knowledge，7–9 天

- Memories、Candidates、Files、Artifacts 统一体验。
- 全局混合搜索和 lineage 下钻。
- 冲突/重复对比。

### Phase 5：Inbox / Autonomy / Drift，5–7 天

- Automation 信息架构重组。
- Decision → Delivery → Feedback 链路。
- Drift 预算、quiet hours、运行详情。

### Phase 6：Schedules，5–7 天

- 创建、查看、暂停、恢复、Run Now、运行历史。

**v0.17 退出标准：** 日常知识审核和自动化管理不再需要 CLI。

## v0.18 — Capabilities & Governance

### Phase 7：Skills，6–8 天

- Catalog、Manifest、Schema Form、Preflight、Run Detail、Resume。

### Phase 8：Capabilities / MCP / Providers，7–10 天

- 工具依赖图、MCP 管理、Provider 状态与测试。

### Phase 9：Governance，6–8 天

- Approval 升级、Policy Matrix/Explain、Secrets 管理。

**v0.18 退出标准：** 能力配置和安全控制有完整可视化闭环，且不存在 UI 绕过治理路径。

## v0.19 — Observability, Operations & Agents

### Phase 10：Trace / Usage / Replay，6–8 天

- Timeline、Tree、Waterfall、Data、比较和聚合。

### Phase 11：System Operations，5–7 天

- Config provenance、Doctor live check、Backup/Restore、Migration。

### Phase 12：Agents 后端，8–12 天

- Subagent 持久化、恢复、父子 Trace、预算/治理隔离。

### Phase 13：Agents UI，5–7 天

- Agent Workspace、Run Tree、委派、Merge、取消和资源视图。

**v0.19 退出标准：** 架构文档中的主要运行平面均有真实 UI 映射；Agents UI 与后端语义一致。

---

## 14. 工作量与优先级

| 模块 | 预计工作日 | 优先级 | 依赖 |
|---|---:|---|---|
| 安全与服务边界 | 3–5 | P0 | v0.15 最小项 |
| Design System/Shell | 5–7 | P0 | 无 |
| Overview | 3–4 | P1 | Activity 聚合服务 |
| Chat | 7–10 | P0 | Runtime streaming |
| Knowledge | 7–9 | P1 | Hybrid retrieval/File registry |
| Automation/Schedules | 10–14 | P1 | Scheduler services |
| Skills | 6–8 | P1 | SkillRunner query/cancel |
| Capability/MCP/Provider | 7–10 | P1 | 管理服务与 secret refs |
| Governance | 6–8 | P0 | Policy explain/CSRF |
| Observability | 6–8 | P1 | Trace aggregation |
| System Operations | 5–7 | P1 | Backup/health/config provenance |
| Agents backend + UI | 13–19 | P2 | Runtime persistence |

单人完整实施预计 78–109 个工作日。建议按 v0.16–v0.19 分四次发布，不做一次性大爆炸重写。

---

## 15. 迁移策略

1. 新旧页面共用现有 URL，逐页替换模板，不同时维护两套餐路由。
2. 先抽 Design System macro，再迁移页面，避免复制新样式。
3. 所有数据库变更使用新 migration，禁止在模板层兼容 Schema。
4. htmx 行为必须保留无 JavaScript 的基础表单路径。
5. 每个 Phase 完成后删除被替代 CSS、partial 和 helper。
6. 每个版本更新 README、CHANGELOG、AGENTS、Release Checklist 和 pyproject version。

---

## 16. 风险与控制

| 风险 | 影响 | 控制措施 |
|---|---|---|
| UI 重构复制业务逻辑 | 治理绕过、行为不一致 | Application Service 单一入口 |
| 一次重写所有页面 | 回归范围不可控 | 按页面渐进替换 |
| htmx 局部状态混乱 | 后退/刷新丢状态 | 查询参数作为列表状态源 |
| Trace 页面数据过大 | 页面卡顿 | 分页、懒加载、摘要优先 |
| Secret 表单泄漏 | 高安全风险 | no-store、不回显、统一 redaction |
| 先做 Agents UI | 产生假功能和返工 | 后端前置 Gate |
| 视觉效果压过可用性 | 运维页面难读 | 高密度信息遵循层级和 AA 对比度 |
| 文档/版本继续漂移 | 发布状态不可信 | 每版退出标准强制同步元数据 |

---

## 17. Definition of Done

每个页面只有同时满足以下条件才算完成：

- 功能路径调用真实 Application Service。
- Auth、CSRF、workspace scope、policy、audit 正确。
- Loading/empty/error/partial/success 状态齐全。
- Desktop/Mobile、键盘和 reduced motion 可用。
- 动态内容经过 escape/redaction。
- Unit、Integration、E2E 和必要的 Visual Regression 已覆盖。
- Trace/Audit/关联对象可以下钻。
- 无远程静态资源。
- Ruff、Mypy、全量 pytest 通过。
- 文档、版本、截图和 Release Checklist 已更新。

---

## 18. 推荐的下一步

立即启动 **v0.16 Phase 0 + Phase 1**，不要先逐页改 CSS：

1. 建立 CSRF 和安全响应头。
2. 抽出 Console Application Service 和统一 PageContext。
3. 建立 Design Token、Icon Sprite、组件 macro 和新 Base Shell。
4. 用 Overview 作为组件试验页。
5. Design System 稳定后重构 Chat。

第一里程碑应是“新 Shell + Overview + 原有功能页面可导航”，第二里程碑才是完整 Chat Workspace。这样可以控制回归范围，并为后续 Knowledge、Automation、Governance 页面提供稳定基础。

---

## 19. UI 之外的 Agent 后端开发主线

Console 只能呈现真实能力，不能替代后端语义。以下能力必须与 UI 计划并行开发，其中 Task、Plugin、Agents 等页面必须以后端完成为前置条件。

### 19.1 v0.15 Production Foundation（P0）

目标：保证 Cogito-Agent 可以作为长期运行的本地服务安装、升级、诊断和恢复。

交付内容：

- 修正 `pyproject.toml`、README、AGENTS、CHANGELOG 之间的版本漂移。
- TOML 配置文件与 `CLI > ENV > config file > defaults` 优先级。
- `/api/v1/health` 和内部运行状态检查。
- 结构化 JSON 日志、日志轮转和本地错误聚合。
- SQLite WAL、busy timeout、连接生命周期和自动维护。
- 自动备份策略、备份校验、Restore Dry Run。
- Windows Service、systemd、launchd 的安装和卸载。
- SIGINT/SIGTERM/SIGHUP 的优雅停止与配置重载。
- Windows、Linux、macOS CI matrix 和 wheel 安装验证。
- CSRF、CORS allowlist、request size limit、安全响应头。

退出标准：

- 三个平台可从 wheel 安装并初始化数据库。
- Daemon 可被服务管理器启动、停止和重启。
- 异常退出不破坏数据库和 Outbox 状态。
- Backup/Restore 在干净环境完成往返验证。
- Doctor 不报告未解释的 security risk。

### 19.2 Model Router（P0）

实施状态（2026-06-20）：第一阶段已完成。配置 Provider 已通过 `ModelRouter` 创建，
支持确定性约束、健康缓存、熔断、恢复探测和 transient fallback；路由选择、排除原因、
失败尝试和最终选择已脱敏写入 Trace/Audit。真实 DeepSeek 配置回归已通过。

剩余工作是多候选配置格式、每 Provider 独立凭据、Workspace/Skill/Agent 覆盖，以及成本配置管理。

需要实现：

- `ModelRouteRequest`：task type、required capabilities、context tokens、latency class、quality class、budget、workspace、skill。
- `ModelCandidate`：provider、model、capabilities、context limit、cost profile、health、priority。
- `ModelRouter.route()`：确定性规则优先，返回选择结果和原因。
- Provider health cache、熔断、恢复探测。
- transient failure fallback chain。
- Tool calling、streaming、structured output 能力匹配。
- Workspace/Skill/Agent 级路由覆盖。
- 路由决策、fallback 和成本估算写入 Trace/Audit。
- 路由模拟测试，禁止单元测试调用真实收费 API。

首期不使用 LLM 决定模型路由，避免递归成本和不可解释决策。

### 19.3 Task Domain（P1）

当前 `task_extraction` 只生成候选 Artifact，缺少正式任务实体。需要新增：

- `tasks`：title、description、status、priority、due_at、source、workspace、assignee、created_at、completed_at。
- `task_events`：状态变更和审计历史。
- `task_links`：关联 session、message、memory、artifact、schedule、trace。
- Task Candidate 接受、编辑、忽略、去重。
- 创建、开始、阻塞、完成、取消、延期。
- 与 Scheduler、Inbox、Memory、Autonomy 的应用服务集成。
- 逾期和即将到期事件进入 Notification Gate。
- 删除采用软删除或可审计 tombstone。

Task UI 只能在 Repository、Application Service、Policy 和 Audit 路径完成后开放写操作。

### 19.4 Context & Reasoning Deepening（P1）

目标：从“能拼装上下文”提升为“可解释、可压缩、有稳定引用的上下文治理”。

需要实现：

- 长会话增量摘要和摘要版本。
- 文件、Tool Result、历史消息的独立压缩策略。
- 动态预算分配，而不是仅使用固定类别比例。
- Context Item 的 evidence strength、freshness 和 trust metadata。
- included/excluded 原因标准化。
- 引用稳定标识，支持文件行号、Memory、Artifact、Message。
- `ResultComposer` 独立服务，统一正文、引用、Tool Summary、Artifact 和后续建议。
- Embedding 后台批量生成、模型版本记录和索引重建。
- 真实 Embedding 不可用时明确显示降级状态。
- Context/Answer 质量 Eval 数据集。

压缩器不得直接修改原始会话、Memory 或文件，只生成带 lineage 的派生记录。

### 19.5 Plugin Runtime（P1）

目标：完成架构文档中可安装、启用、禁用、升级和回滚的本地扩展生命周期。

需要实现：

- Plugin Manifest：id、version、entry points、skills、capabilities、MCP、permissions、dependencies。
- 本地安装、校验、启用、禁用、卸载。
- 版本兼容、依赖检查和冲突检测。
- Plugin → Capability/Skill/MCP 的注册与注销。
- Workspace 级启用状态。
- 安装前权限预览和审批。
- 升级 diff、major version 重新审批和回滚。
- 可信来源、文件 hash 和可选签名验证。
- 安装、启用、升级、卸载全部写入 Audit。
- Plugin 失败不能阻止核心 Runtime 启动。

首期只支持本地目录或本地归档包，不实现 Marketplace 和远程自动安装。

### 19.6 Multi-Agent Runtime（P1/P2）

现有 `SubagentManager` 仅具备基础 fork/run/merge，且运行元数据主要在进程内。完整实现需要：

- `agents`、`agent_runs`、`agent_messages`、`agent_grants` 持久化模型。
- 父任务/子任务状态和父子 Trace。
- 独立 Context、Budget、Policy、Capability Grant。
- 并行调度、最大并发、超时和取消。
- 进程重启后的恢复或明确失败收敛。
- Agent 间结构化消息，禁止共享任意可变内存对象。
- 结果 Merge contract、冲突报告和来源保留。
- 主 Agent 对子 Agent 输出重新验证。
- 防止递归无限创建 Subagent。
- 每个 Agent Run 可追踪模型、工具、成本和产物。

建议先实现单机任务级 Subagent，不实现长期自治 Agent 网络。

### 19.7 Autonomy Runtime Hardening（P1）

- 将阻塞循环升级为可停止、可恢复的异步或事件驱动 daemon。
- Daemon 单实例锁和 heartbeat。
- Cron 表达式及 timezone/DST 语义。
- Job lease，防止崩溃或双实例造成重复执行。
- Outbox/Skill/Schedule 的持久化重试和 dead-letter 运维流程。
- 更完整的 AutonomySource adapter contract。
- Notification preference 的确定性学习规则。
- Email、Telegram、飞书等 Delivery Adapter；发送前统一经过 Governance 和 Notification Gate。
- Delivery credential 只能通过 Secret Reference 获取。

外部渠道为可选适配器，失败不得影响本地 Inbox。

### 19.8 Data Governance（P1）

- Workspace 数据清单和完整删除流程。
- Memory 禁用、纠错、版本和 provenance 导出。
- Trace、Audit、Artifact、Inbox、Backup 的保留策略。
- 按数据类型配置 retention，而不是全局统一天数。
- PII/Secret/Sensitive 内容分类。
- 清理任务的 Dry Run、计数、审批和 Audit。
- Backup manifest、checksum、schema version 和兼容检查。
- 云迁移 Adapter 接口，但本阶段不实现云同步。
- 对 audit evidence 定义不可静默删除的最小保留规则。

### 19.9 Observability & Evaluation（P1）

- Trace 聚合查询和时间序列指标。
- Provider/Model/Tool/Skill 的调用量、延迟、失败率和重试率。
- token 和成本估算；未知价格必须显示 unknown。
- Golden conversation、tool flow、memory retrieval、policy decision Eval 数据集。
- Replay 比较和版本回归报告。
- Context precision、citation coverage、tool success、notification usefulness 指标。
- 性能基线：数据库规模、Trace 数量、Memory 数量和文件 chunk 数量。
- 诊断包默认脱敏，禁止包含 Secret 和完整用户内容。

---

## 20. 综合版本路线图

后端主线与 Console 主线按以下顺序合并交付：

| 版本 | 后端主线 | Console 主线 | 核心退出标准 |
|---|---|---|---|
| v0.15 | Production Foundation、安全、配置、服务管理 | Phase 0 前置安全 | 可安装、可运行、可诊断、可恢复 |
| v0.16 | Model Router、Context/ResultComposer 第一阶段 | Design System、Overview、Chat | 日常 Chat 可用且每轮可解释 |
| v0.17 | Task Domain、Autonomy hardening | Knowledge、Tasks、Schedules、Automation | 知识和任务形成闭环 |
| v0.18 | Plugin Runtime、Data Governance | Skills、Capabilities、MCP、Providers、Governance | 扩展能力不绕过治理 |
| v0.19 | Multi-Agent Runtime、Observability/Eval | Agents、Trace、Usage、Operations | 多 Agent 可恢复、可治理、可追踪 |

### 20.1 依赖顺序

```text
Production Foundation
  ├── Console Security Foundation
  ├── Model Router ── Context/ResultComposer ── Chat Inspector
  ├── Task Domain ── Tasks UI ── Schedule/Notification Integration
  ├── Plugin Runtime ── Skills/Capabilities/MCP UI
  ├── Data Governance ── Secrets/Backup/Retention UI
  └── Multi-Agent Runtime ── Agents UI ── Cross-run Observability
```

### 20.2 当前推荐启动包

下一开发周期建议只启动以下三个相互配合的工作包：

1. ✅ **v0.15 Production Foundation 最小闭环**（已完成 2026-06-19）：配置（TOML + CLI/ENV/file/defaults 优先级）、health endpoint（200/503）、结构化 JSON 日志 + 轮转、SQLite WAL + busy_timeout、Web 安全（CSRF/CORS allowlist/请求体限制/CSP/X-Content-Type-Options/Referrer-Policy/frame-ancestors）。
2. ✅ **v0.16 Console Phase 0–2**：Application Service、统一 PageContext、Design System、Base Shell 和 Overview 已完成并稳定化。
3. **v0.16 Phase 3 + Model Router**：完成 Chat Workspace、能力匹配、健康状态、fallback、ResultComposer 和 Trace 决策。

暂不同时启动 Task、Plugin 和 Multi-Agent，以免在基础服务、治理和 UI 组件尚未稳定时扩大迁移面。

### 20.3 项目级完成标准

只有满足以下条件，才能认为架构文档已经基本落地：

- 每个主要架构平面都有真实服务边界和 UI/CLI 可观测入口。
- Runtime 不依赖具体 Provider、Tool、Storage Driver 或 Channel 实现。
- 所有外部副作用统一经过 Governance。
- Context、Model、Tool、Policy、Artifact、Memory 和最终响应可沿 Trace 双向追溯。
- 后台任务、Schedule 和 Subagent 可在进程重启后恢复或安全收敛。
- 用户能够导出、删除、备份和恢复自己的数据。
- Plugin、Skill、MCP 和 Agent 的权限可以解释、审批和撤销。
- Console 不包含仅用于展示的假功能。
- 三个平台的安装、升级、测试和安全检查通过。
