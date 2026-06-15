from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cogito_agent.shared import CapabilityManifest


class ToolResult:
    def __init__(
        self,
        status: str = "ok",
        summary: str = "",
        data: dict[str, object] | None = None,
        error: str | None = None,
        artifacts: list[dict[str, object]] | None = None,
        redactions: list[str] | None = None,
        lineage: list[dict[str, object]] | None = None,
    ) -> None:
        self.status = status
        self.summary = summary
        self.data = data or {}
        self.error = error
        self.artifacts = artifacts or []
        self.redactions = redactions or []
        self.lineage = lineage or []


def _validate_json_schema(
    schema: dict[str, object], data: dict[str, object],
) -> str | None:
    """Validate *data* against a JSON Schema (subset).
    Returns an error message or None on success.
    Supports: type: object, properties, required, string/number/integer/boolean/array, items, enum.
    """
    props: dict[str, object] = {}
    raw_props = schema.get("properties")
    if isinstance(raw_props, dict):
        props = {str(k): v for k, v in raw_props.items()}

    required: list[str] = []
    raw_required = schema.get("required")
    if isinstance(raw_required, list):
        required = [str(r) for r in raw_required]

    for field_name in required:
        if field_name not in data:
            return f"Missing required field: {field_name}"

    for field_name, value in data.items():
        if field_name not in props:
            continue
        prop_schema = props[field_name]
        if not isinstance(prop_schema, dict):
            continue
        err = _validate_value(prop_schema, value, field_name)
        if err:
            return err

    return None


def _validate_value(
    schema: dict[str, object], value: object, path: str,
) -> str | None:
    expected_type = schema.get("type")

    if expected_type == "string":
        if not isinstance(value, str):
            return f"Field '{path}' must be a string"
        raw_enum = schema.get("enum")
        if isinstance(raw_enum, list) and value not in raw_enum:
            return f"Field '{path}' must be one of {raw_enum}"

    elif expected_type == "number":
        if not isinstance(value, (int, float)):
            return f"Field '{path}' must be a number"

    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"Field '{path}' must be an integer"

    elif expected_type == "boolean":
        if not isinstance(value, bool):
            return f"Field '{path}' must be a boolean"

    elif expected_type == "array":
        if not isinstance(value, list):
            return f"Field '{path}' must be an array"
        raw_items = schema.get("items")
        if isinstance(raw_items, dict):
            for i, item in enumerate(value):
                err = _validate_value(raw_items, item, f"{path}[{i}]")
                if err:
                    return err

    elif expected_type == "object":
        if not isinstance(value, dict):
            return f"Field '{path}' must be an object"

    return None


class CapabilityRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[CapabilityManifest, Callable[..., ToolResult]]] = {}

    def register(
        self, name: str, manifest: CapabilityManifest,
        invoke_fn: Callable[..., ToolResult],
    ) -> None:
        self._tools[name] = (manifest, invoke_fn)

    def get_manifest(self, name: str) -> CapabilityManifest | None:
        entry = self._tools.get(name)
        if entry is None:
            return None
        return entry[0]

    def invoke(self, name: str, **kwargs: Any) -> ToolResult | None:
        entry = self._tools.get(name)
        if entry is None:
            return None
        manifest, invoke_fn = entry
        if manifest.input_schema and isinstance(manifest.input_schema, dict):
            err = _validate_json_schema(manifest.input_schema, kwargs)
            if err:
                return ToolResult(
                    status="error", summary="Input validation failed",
                    error=f"Validation error for {name}: {err}",
                )
        return invoke_fn(**kwargs)

    def list_tools(self) -> list[CapabilityManifest]:
        return [m for m, _ in self._tools.values()]
