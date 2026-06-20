from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    dimension: int
    max_input_tokens: int = 8192
    query_instruction: str | None = None
    supports_dimensions_parameter: bool = True


MODEL_REGISTRY: dict[str, ModelInfo] = {
    "BAAI/bge-m3": ModelInfo(
        dimension=1024,
        max_input_tokens=8192,
        query_instruction=None,
        supports_dimensions_parameter=False,
    ),
    "BAAI/bge-large-zh-v1.5": ModelInfo(
        dimension=1024,
        max_input_tokens=512,
        query_instruction=None,
        supports_dimensions_parameter=False,
    ),
    "text-embedding-3-small": ModelInfo(
        dimension=1536,
        max_input_tokens=8191,
        supports_dimensions_parameter=True,
    ),
    "text-embedding-3-large": ModelInfo(
        dimension=3072,
        max_input_tokens=8191,
        supports_dimensions_parameter=True,
    ),
    "text-embedding-ada-002": ModelInfo(
        dimension=1536,
        max_input_tokens=8191,
        supports_dimensions_parameter=False,
    ),
    "all-MiniLM-L6-v2": ModelInfo(
        dimension=384,
        max_input_tokens=256,
        supports_dimensions_parameter=False,
    ),
}


def get_model_info(model_name: str) -> ModelInfo | None:
    return MODEL_REGISTRY.get(model_name)
