from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from urllib.parse import urljoin

from .adapter import ModelResponse


class OpenAICompatibleAdapter:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_sec: int = 60,
    ) -> None:
        self.api_key = api_key or os.environ.get("MODEL_API_KEY", "")
        base = base_url or os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1")
        self.base_url = base.rstrip("/") + "/"
        self.model = model or os.environ.get("MODEL_NAME", "gpt-4o-mini")
        self.timeout_sec = timeout_sec

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self.model,
            "messages": messages,
        }
        if "temperature" in kwargs:
            body["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            body["max_tokens"] = kwargs["max_tokens"]
        if "tools" in kwargs:
            body["tools"] = kwargs["tools"]
        if kwargs.get("stream"):
            body["stream"] = True
        return body

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> ModelResponse:
        url = urljoin(self.base_url, "chat/completions")
        body = self._build_body(messages, **kwargs)
        data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            url, data=data, headers=self._headers, method="POST"
        )
        start = time.monotonic()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                elapsed = int((time.monotonic() - start) * 1000)
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            elapsed = int((time.monotonic() - start) * 1000)
            body_text = e.read().decode("utf-8", errors="replace")
            return ModelResponse(
                error=f"HTTP {e.code}: {body_text}",
                latency_ms=elapsed,
                model=self.model,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return ModelResponse(
                error=str(e),
                latency_ms=elapsed,
                model=self.model,
            )

        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content") or ""
        tool_calls_raw = message.get("tool_calls")

        tool_intents: list[dict[str, object]] = []
        if tool_calls_raw:
            for tc in tool_calls_raw:
                tool_intents.append({
                    "id": tc.get("id", ""),
                    "function": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "{}"),
                })

        usage = result.get("usage", {})
        stop_reason = choice.get("finish_reason", "")

        return ModelResponse(
            content=content,
            tool_intents=tool_intents,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            model=result.get("model", self.model),
            latency_ms=elapsed,
            stop_reason=stop_reason,
            error=None,
        )

    def stream_chat(
        self, messages: list[dict[str, str]], **kwargs: object
    ) -> Iterator[str]:
        url = urljoin(self.base_url, "chat/completions")
        body = self._build_body(messages, stream=True, **kwargs)
        data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            url, data=data, headers=self._headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                buffer = ""
                while True:
                    chunk = resp.read(1)
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data: "):
                            payload = line[6:]
                            if payload == "[DONE]":
                                return
                            try:
                                data_obj = json.loads(payload)
                                choices = data_obj.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    token = delta.get("content", "")
                                    if token:
                                        yield token
                            except json.JSONDecodeError:
                                continue
        except urllib.error.HTTPError as e:
            yield f"[stream error: HTTP {e.code}]"
        except Exception as e:
            yield f"[stream error: {e}]"
