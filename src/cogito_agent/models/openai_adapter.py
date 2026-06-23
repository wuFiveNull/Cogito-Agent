from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from urllib.parse import urljoin

from .adapter import ModelResponse, ToolIntent
from .codec import OpenAICompatibleCodec, ProviderMessageCodec


def _deep_copy_tool(t: dict[str, object]) -> dict[str, object]:
    """Deep-copy a tool dict so we can mutate names without affecting the original."""
    result: dict[str, object] = {}
    for k, v in t.items():
        if isinstance(v, dict):
            result[k] = _deep_copy_tool(v)  # type: ignore[arg-type]
        elif isinstance(v, list):
            result[k] = [dict(item) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _merge_streaming_tool_calls(
    existing: list[ToolIntent],
    delta_tc: dict[str, object],
) -> list[ToolIntent]:
    raw_idx = delta_tc.get("index", 0)
    idx = int(raw_idx) if isinstance(raw_idx, (int, float, str)) else 0
    raw_fn = delta_tc.get("function", {})
    delta_fn = raw_fn if isinstance(raw_fn, dict) else {}
    tc_id = str(delta_tc.get("id", ""))

    while len(existing) <= idx:
        existing.append(ToolIntent(tool_call_id="", capability_name="", arguments={}))

    current = existing[idx]
    if tc_id:
        current.tool_call_id = tc_id
    fn_name = str(delta_fn.get("name", ""))
    if fn_name:
        current.capability_name = fn_name
    args_delta = str(delta_fn.get("arguments", ""))
    if args_delta:
        current_args_raw = (
            json.dumps(current.arguments, ensure_ascii=False) if current.arguments else ""
        )
        merged = current_args_raw + args_delta
        try:
            parsed = json.loads(merged)
            if isinstance(parsed, dict):
                current.arguments = {str(k): v for k, v in parsed.items()}
        except (json.JSONDecodeError, TypeError):
            current.arguments = {"_partial": current_args_raw + args_delta}
    return existing


class OpenAICompatibleAdapter:
    supports_streaming = True

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_sec: int = 60,
        codec: ProviderMessageCodec | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("MODEL_API_KEY", "")
        base = base_url or os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1")
        self.base_url = base.rstrip("/") + "/"
        self.model = model or os.environ.get("MODEL_NAME", "gpt-4o-mini")
        self.timeout_sec = timeout_sec
        self.codec = codec or OpenAICompatibleCodec()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(self, messages: list[dict[str, object]], **kwargs: object) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self.model,
            "messages": messages,
        }
        if "temperature" in kwargs:
            body["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            body["max_tokens"] = kwargs["max_tokens"]
        if "tools" in kwargs:
            tools = kwargs["tools"]
            if isinstance(tools, list):
                # Some providers (e.g. DeepSeek) reject dots in function names.
                # Sanitize: "." -> "_" and ":" -> "_" to match [a-zA-Z0-9_-]+
                sanitized: list[dict[str, object]] = []
                for t in tools:
                    t_copy = _deep_copy_tool(t)
                    fn = t_copy.get("function", {})
                    if isinstance(fn, dict):
                        raw = fn.get("name", "")
                        if isinstance(raw, str):
                            fn["name"] = raw.replace(".", "_").replace(":", "_")
                    sanitized.append(t_copy)
                body["tools"] = sanitized
            else:
                body["tools"] = tools
        if kwargs.get("stream"):
            body["stream"] = True
        return body

    def _parse_tool_calls(
        self,
        raw_tool_calls: list[dict[str, object]],
    ) -> list[ToolIntent]:
        intents: list[ToolIntent] = []
        for tc in raw_tool_calls:
            fn_data = tc.get("function", {})
            fn_dict = fn_data if isinstance(fn_data, dict) else {}
            args_raw = fn_dict.get("arguments", "{}")
            args_str = str(args_raw) if args_raw else "{}"
            try:
                args = json.loads(args_str)
            except (json.JSONDecodeError, TypeError):
                args = {}
            intents.append(
                ToolIntent(
                    tool_call_id=str(tc.get("id", "")),
                    capability_name=str(fn_dict.get("name", "")),
                    arguments={str(k): v for k, v in args.items()}
                    if isinstance(args, dict)
                    else {},
                )
            )
        return intents

    def _legacy_dicts_to_chat_messages(self, messages: list[dict[str, object]]) -> list:  # type: ignore[type-arg]
        """Convert legacy dict messages to ChatMessage objects for codec."""
        from .messages import ChatMessage, FilePart, ImagePart, MessageRole, TextPart

        result: list[ChatMessage] = []
        for msg in messages:
            role = msg.get("role", "user")
            content_raw = msg.get("content", "")
            parts: list[TextPart | ImagePart | FilePart]
            if isinstance(content_raw, str):
                parts = [TextPart(text=content_raw)]
            elif isinstance(content_raw, list):
                parts = []
                for item in content_raw:
                    if isinstance(item, dict):
                        ptype = item.get("type", "text")
                        if ptype == "image":
                            parts.append(
                                ImagePart(
                                    uri=str(
                                        item.get("uri", item.get("image_url", {}).get("url", ""))
                                    ),
                                    mime_type=str(item.get("mime_type", "image/png")),
                                )
                            )
                        elif ptype == "file":
                            parts.append(
                                FilePart(
                                    uri=str(item.get("uri", "")),
                                    mime_type=str(
                                        item.get("mime_type", "application/octet-stream")
                                    ),
                                    filename=str(item.get("filename", "file")),
                                )
                            )
                        else:
                            parts.append(TextPart(text=str(item.get("text", ""))))
                    else:
                        parts.append(TextPart(text=str(item)))
            else:
                parts = [TextPart(text=str(content_raw))]
            role_val = (
                MessageRole(role)
                if role in ("user", "assistant", "system", "tool")
                else MessageRole.user
            )
            cm = ChatMessage(role=role_val, content=parts)
            if msg.get("tool_call_id"):
                cm.tool_call_id = str(msg["tool_call_id"])
            if msg.get("name"):
                cm.name = str(msg["name"])
            result.append(cm)
        return result

    def chat(self, messages: list[dict[str, object]], **kwargs: object) -> ModelResponse:
        chat_msgs = self._legacy_dicts_to_chat_messages(messages)
        encoded = self.codec.encode_messages(chat_msgs)
        url = urljoin(self.base_url, "chat/completions")
        body = self._build_body(encoded, **kwargs)
        data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=self._headers, method="POST")
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

        tool_intents: list[ToolIntent] = []
        if tool_calls_raw:
            tool_intents = self._parse_tool_calls(tool_calls_raw)

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

    def stream_chat(self, messages: list[dict[str, object]], **kwargs: object) -> Iterator[str]:
        chat_msgs = self._legacy_dicts_to_chat_messages(messages)
        encoded = self.codec.encode_messages(chat_msgs)
        url = urljoin(self.base_url, "chat/completions")
        body = self._build_body(encoded, stream=True, **kwargs)
        data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=self._headers, method="POST")

        accumulated: dict[int, dict[str, object]] = {}

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                buf = b""
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line_str = line.strip().decode("utf-8", errors="replace")
                        if not line_str or line_str.startswith(":"):
                            continue
                        if line_str.startswith("data: "):
                            payload = line_str[6:]
                            if payload == "[DONE]":
                                return
                            try:
                                data_obj = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            choices = data_obj.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            finish = choice.get("finish_reason", "")

                            token = delta.get("content", "")
                            if token:
                                yield token

                            delta_tcs = delta.get("tool_calls")
                            if delta_tcs:
                                for dtc in delta_tcs:
                                    raw_idx = dtc.get("index", 0)
                                    idx = (
                                        int(raw_idx)
                                        if isinstance(raw_idx, (int, float, str))
                                        else 0
                                    )
                                    raw_fn = dtc.get("function", {})
                                    fn_data = raw_fn if isinstance(raw_fn, dict) else {}
                                    args_raw = str(fn_data.get("arguments", ""))

                                    if idx not in accumulated:
                                        accumulated[idx] = {
                                            "id": str(dtc.get("id", "")),
                                            "function": {
                                                "name": str(fn_data.get("name", "")),
                                                "arguments": args_raw,
                                            },
                                        }
                                    else:
                                        entry = accumulated[idx]
                                        existing_id = dtc.get("id")
                                        if existing_id:
                                            entry["id"] = str(existing_id)
                                        fn_name = fn_data.get("name")
                                        if isinstance(fn_name, str) and fn_name:
                                            raw_sub = entry.get("function", {})
                                            sub = raw_sub if isinstance(raw_sub, dict) else {}
                                            sub["name"] = fn_name
                                            entry["function"] = sub
                                        raw_sub2 = entry.get("function", {})
                                        sub2 = raw_sub2 if isinstance(raw_sub2, dict) else {}
                                        old_args = str(sub2.get("arguments", ""))
                                        sub2["arguments"] = old_args + args_raw
                                        entry["function"] = sub2

                            if finish:
                                if finish == "tool_calls":
                                    yield "[TOOL_CALLS]"
                                return
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            yield f"[stream error: HTTP {e.code} {detail}]"
        except Exception as e:
            yield f"[stream error: {e}]"

    def get_tool_calls_from_stream(
        self,
        accumulated: dict[int, dict[str, object]] | None = None,
    ) -> list[ToolIntent]:
        if not accumulated:
            return []
        intents: list[ToolIntent] = []
        for idx in sorted(accumulated.keys()):
            entry = accumulated[idx]
            raw_fn = entry.get("function", {})
            fn_data = raw_fn if isinstance(raw_fn, dict) else {}
            args_raw = str(fn_data.get("arguments", ""))
            try:
                args = json.loads(args_raw) if args_raw else {}
            except (json.JSONDecodeError, TypeError):
                args = {"_raw": args_raw}
            intents.append(
                ToolIntent(
                    tool_call_id=str(entry.get("id", "")),
                    capability_name=str(fn_data.get("name", "")),
                    arguments={str(k): v for k, v in args.items()}
                    if isinstance(args, dict)
                    else {},
                )
            )
        return intents
