"""Lazy Kernel manager — RuntimeKernel 惰性初始化与生命周期管理。

KernelManager 将 Kernel 的生命周期与 Console App 解耦：
- Console 启动时不初始化 Kernel（秒开）
- 仅当用户发送消息时才触发 Kernel 构建
- 支持 reset() 用于备份恢复等场景
- 统一管理 MCP Server Manager 的创建/销毁
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from cogito_agent.storage import Database

logger = logging.getLogger(__name__)


class KernelManager:
    """管理 RuntimeKernel + MCP Server Manager 的惰性构建与生命周期。

    用法::

        manager = KernelManager(db)
        # 不会立即构建任何东西
        kernel = manager.get_kernel()   # 首次调用时惰性构建
        mcp = manager.get_mcp_manager() # 惰性构建 MCP 管理器
        manager.reset()                 # 重置所有状态
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._kernel: Any = None
        self._mcp_manager: Any = None
        self._cap_registry: Any = None
        self._lock = threading.RLock()
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built

    # ── RuntimeKernel ───────────────────────────────────────────────────────

    def get_kernel(self) -> Any:
        """返回 RuntimeKernel 实例，首次调用时惰性构建。"""
        if not self._built:
            with self._lock:
                if not self._built:
                    self._kernel = self._build()
                    self._built = True
        return self._kernel

    def get_chat_service(self) -> Any:
        """返回 ChatApplicationService(kernel)。"""
        from cogito_agent.application import ChatApplicationService

        return ChatApplicationService(self.get_kernel())

    # ── MCP Server Manager ──────────────────────────────────────────────────

    def get_mcp_manager(self) -> Any:
        """返回 MCPServerManager 实例（惰性创建）。

        与 RuntimeKernel 共享同一个 CapabilityRegistry。
        """
        if self._mcp_manager is None:
            with self._lock:
                if self._mcp_manager is None:
                    self._mcp_manager = self._build_mcp_manager()
        return self._mcp_manager

    def get_mcp_service(self) -> Any:
        """返回 MCPApplicationService。"""
        from cogito_agent.application import MCPApplicationService
        from cogito_agent.governance import AuditLogger
        from cogito_agent.storage.mcp_calls import SqliteMCPCallReader

        return MCPApplicationService(
            self.get_mcp_manager(),
            AuditLogger(self._db),
            SqliteMCPCallReader(self._db),
        )

    def get_reset_callback(self) -> Callable[[], None]:
        """返回一个零参数回调，供 backup_views.py 的 BackupApplicationService 使用。"""
        return self.reset

    # ── Reset ───────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """重置所有运行时状态（Kernel + MCP + CapabilityRegistry）。

        用于备份恢复等需要重建运行时状态的场景。
        """
        with self._lock:
            # 1. Cleanup MCP servers
            if self._mcp_manager is not None:
                try:
                    for server in self._mcp_manager.list_servers():
                        self._mcp_manager.remove_server(
                            str(server.get("name", ""))
                        )
                except Exception:
                    logger.debug("MCP cleanup during reset (non-fatal)")
            self._mcp_manager = None

            # 2. Cleanup kernel
            self._kernel = None
            self._cap_registry = None
            self._built = False

            # 3. Reset database connection
            try:
                from cogito_agent.storage import reset_db as _storage_reset_db
                _storage_reset_db()
            except Exception:
                logger.debug("DB reset during kernel reset (non-fatal)")

            logger.info("KernelManager: all runtime state reset")

    # ── Internal builders ───────────────────────────────────────────────────

    def _build_mcp_manager(self) -> Any:
        """创建 MCPServerManager（不需要 Kernel 就绪）。"""
        from cogito_agent.mcp import MCPServerManager, MCPTrustStore
        from cogito_agent.capability import CapabilityRegistry

        # 使用与 Kernel 共享的 CapabilityRegistry
        if self._cap_registry is None:
            self._cap_registry = CapabilityRegistry()
        return MCPServerManager(
            self._cap_registry,
            trust_store=MCPTrustStore(self._db),
        )

    def _build(self) -> Any:
        """完整的 RuntimeKernel 构建。包装现有的 build_runtime_kernel()。

        Note: 这个方法里的 import 都是惰性的，因为它们在 Console
        启动时不需要——只在用户发消息时才加载。
        """
        from pathlib import Path

        from cogito_agent.application.runtime_factory import (
            build_runtime_kernel,
            default_workspace_path,
        )
        from cogito_agent.config.loader import build_multimodel_adapter, load_config
        from cogito_agent.media import MemeService
        from cogito_agent.media.vision_service import VisionObservationService
        from cogito_agent.workspace.artifacts import ArtifactService

        cfg = load_config()
        adapter = build_multimodel_adapter(cfg)
        if adapter is None:
            from cogito_agent.cli.chat import build_model_adapter_from_config

            adapter = build_model_adapter_from_config(cfg)

        # 如果 MCP 管理器已创建，复用其 CapabilityRegistry
        if self._cap_registry is None:
            from cogito_agent.capability import CapabilityRegistry as _CR

            self._cap_registry = _CR()
        cap_reg = self._cap_registry

        vision_svc = VisionObservationService(self._db, None)
        vision_svc.register_with_capability_registry(cap_reg)

        meme_svc = MemeService(self._db)
        if vision_svc.has_vision_capability:
            meme_svc.set_vision_service(vision_svc)
        meme_svc.register_with_capability_registry(cap_reg)

        kernel = build_runtime_kernel(
            self._db,
            model_adapter=adapter,
            capability_registry=cap_reg,
            artifact_writer=ArtifactService(self._db),
            workspace_path=default_workspace_path(),
        )
        kernel.set_vision_service(vision_svc)
        kernel.set_meme_service(meme_svc)

        logger.info("RuntimeKernel built (lazy init)")
        return kernel
