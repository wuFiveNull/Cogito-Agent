"""Lazy Kernel manager — RuntimeKernel 惰性初始化与生命周期管理。

KernelManager 将 Kernel 的生命周期与 Console App 解耦：
- Console 启动时不初始化 Kernel（秒开）
- 仅当用户发送消息时才触发 Kernel 构建
- 支持 reset() 用于备份恢复等场景
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from cogito_agent.storage import Database

logger = logging.getLogger(__name__)


class KernelManager:
    """管理 RuntimeKernel 的惰性构建与生命周期。

    用法::

        manager = KernelManager(db)
        # 不会立即构建 Kernel
        kernel = manager.get_kernel()  # 首次调用时惰性构建
        manager.reset()                # 重置 Kernel（关闭旧实例）
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._kernel: Any = None
        self._lock = threading.RLock()
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built

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

    def reset(self) -> None:
        """重置 Kernel（关闭旧实例，下次 get_kernel 时重新构建）。

        用于备份恢复等需要重建运行时状态的场景。
        """
        with self._lock:
            old_kernel = self._kernel
            self._kernel = None
            self._built = False
            if old_kernel is not None:
                try:
                    # Cleanup any MCP servers if the kernel has a reference
                    mcp = getattr(old_kernel, "_mcp_manager", None)
                    if mcp is not None:
                        for server in mcp.list_servers():
                            mcp.remove_server(str(server.get("name", "")))
                except Exception:
                    logger.debug("MCP cleanup during kernel reset (non-fatal)")
            logger.info("Kernel reset complete")

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
        from cogito_agent.capability import CapabilityRegistry
        from cogito_agent.config.loader import build_multimodel_adapter, load_config
        from cogito_agent.media import MemeService
        from cogito_agent.media.vision_service import VisionObservationService
        from cogito_agent.workspace.artifacts import ArtifactService

        cfg = load_config()
        adapter = build_multimodel_adapter(cfg)
        if adapter is None:
            from cogito_agent.cli.chat import build_model_adapter_from_config

            adapter = build_model_adapter_from_config(cfg)

        cap_reg = CapabilityRegistry()
        vision_svc = VisionObservationService(
            self._db, None  # MediaProcessor 在注册时需要
        )
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
