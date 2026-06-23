"""ConsoleDataReader — 纯只读数据访问层，不依赖 RuntimeKernel。

每个 Reader 是一个轻量类，只接受 ``Database`` 实例，
直接执行 SQL SELECT 查询，返回 dict 列表供 Console 模板渲染。

设计原则：
- 只读：所有方法只做 SELECT，不 INSERT/UPDATE/DELETE
- 无业务逻辑：不做数据变换，只做查询
- 无 Repository 包装：直接调 ``db.connection.execute()``
- 同步：Console 使用 Jinja2 SSR，不需要异步
"""

from __future__ import annotations

from .approval_reader import ApprovalReader
from .audit_reader import AuditReader
from .memory_reader import MemoryReader
from .session_reader import SessionReader
from .system_reader import SystemReader
from .trace_reader import TraceReader

__all__ = [
    "ApprovalReader",
    "AuditReader",
    "MemoryReader",
    "SessionReader",
    "SystemReader",
    "TraceReader",
]
