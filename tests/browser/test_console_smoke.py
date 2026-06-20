from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Browser, Page, sync_playwright


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def console_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path_factory.mktemp("browser-data")
    env = os.environ.copy()
    env.update(
        {
            "COGITO_DB_PATH": str(data_dir / "console.db"),
            "COGITO_API_KEY": "",
            "COGITO_CSRF_TOKEN": "",
            "PYTHONPATH": str(root / "src"),
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "cogito_agent.api.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=root,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/v1/health", timeout=1) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("Console server did not become healthy")

    yield url
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.mark.browser_e2e
def test_console_overview_to_chat(browser: Browser, console_url: str) -> None:
    page: Page = browser.new_page(viewport={"width": 1440, "height": 900})
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: (
            console_errors.append(message.text) if message.type == "error" else None
        ),
    )

    page.goto(f"{console_url}/console/overview", wait_until="networkidle")
    assert page.title() == "Cogito-Agent — Overview"
    assert page.get_by_role("heading", name="Attention Queue").is_visible()
    assert page.locator("main").inner_text().strip()

    page.get_by_role("link", name="Chat", exact=True).click()
    page.wait_for_url(f"{console_url}/console/chat")
    assert page.title() == "Cogito-Agent — Chat"
    assert page.get_by_role("heading", name="Sessions").is_visible()
    assert console_errors == []
    page.close()
