"""cogito-console 入口：独立 Console Web 服务器。

与 ``cogito_agent.api.app`` 的 ``run_api`` 不同，此入口只启动
Console Web UI，不需要 RuntimeKernel，秒开。
"""

from __future__ import annotations

import os
from pathlib import Path


def run_console(host: str = "127.0.0.1", port: int = 8080) -> None:
    """启动独立 Console Web 服务器。

    用法::

        cogito-console --port 8080 --db ~/.cogito/cogito.db
    """
    import uvicorn

    from cogito_agent.config.loader import load_config
    from cogito_agent.console.app import create_console_app

    cfg = load_config()
    db_path_env = os.environ.get("COGITO_DB_PATH", "")
    if not db_path_env:
        db_path = str(Path(cfg.storage.db_path).expanduser())
        os.environ["COGITO_DB_PATH"] = db_path
    else:
        db_path = db_path_env

    app = create_console_app(db_path=db_path)
    uvicorn.run(app, host=host, port=port, log_level="info")
