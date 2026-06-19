from __future__ import annotations

from cogito_agent.shared import CapabilityManifest

TOOL_SCHEMA_TYPE = "function"


def manifest_to_tool_schema(manifest: CapabilityManifest) -> dict[str, object]:
    return {
        "type": TOOL_SCHEMA_TYPE,
        "function": {
            "name": manifest.name,
            "description": manifest.description,
            "parameters": manifest.input_schema,
        },
    }


def filter_available_tools(
    manifests: list[CapabilityManifest],
    workspace_id: str = "",
    actor: str = "assistant",
    interaction_mode: str = "interactive",
    background_allowed: bool = False,
) -> list[CapabilityManifest]:
    """Filter manifests to only expose currently available tools to the model."""
    results: list[CapabilityManifest] = []
    for m in manifests:
        if not m.name:
            continue
        if interaction_mode not in m.allowed_contexts:
            if not (background_allowed and "background" in m.allowed_contexts):
                continue
        results.append(m)
    return results
