"""Architecture dependency contracts.

The exception sets describe pre-existing debt. New exceptions are not allowed;
each refactor phase must remove entries as concrete dependencies are migrated.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src" / "cogito_agent"


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    return ".".join(relative.parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _runtime_storage_imports() -> set[tuple[str, str]]:
    violations: set[tuple[str, str]] = set()
    for path in (SOURCE_ROOT / "runtime").glob("*.py"):
        for imported in _imports(path):
            if imported == "cogito_agent.storage" or imported.startswith("cogito_agent.storage."):
                violations.add((_module_name(path), imported))
    return violations


KNOWN_RUNTIME_STORAGE_IMPORTS: set[tuple[str, str]] = set()


def test_runtime_storage_debt_does_not_grow() -> None:
    assert _runtime_storage_imports() == KNOWN_RUNTIME_STORAGE_IMPORTS


def test_runtime_does_not_import_concrete_governance_services() -> None:
    violations: set[tuple[str, str]] = set()
    for path in (SOURCE_ROOT / "runtime").glob("*.py"):
        for imported in _imports(path):
            if imported == "cogito_agent.governance" or imported.startswith(
                "cogito_agent.governance."
            ):
                violations.add((_module_name(path), imported))
    assert violations == set()


def test_runtime_does_not_import_provider_implementations() -> None:
    concrete_provider_modules = {
        "cogito_agent.models.openai_adapter",
        "cogito_agent.models.ollama_adapter",
    }
    violations: set[tuple[str, str]] = set()
    for path in (SOURCE_ROOT / "runtime").glob("*.py"):
        for imported in _imports(path):
            if imported in concrete_provider_modules:
                violations.add((_module_name(path), imported))
    assert violations == set()


def _direct_sql_modules(package: str) -> set[str]:
    modules: set[str] = set()
    for path in (SOURCE_ROOT / package).rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if ".connection.execute(" in source or ".connection.executemany(" in source:
            modules.add(_module_name(path))
    return modules


KNOWN_API_DIRECT_SQL_MODULES = {"cogito_agent.api.app"}
KNOWN_CONSOLE_DIRECT_SQL_MODULES = {
    "cogito_agent.console.approval",
    "cogito_agent.console.audit_views",
    "cogito_agent.console.doctor_views",
    "cogito_agent.console.inbox_views",
    "cogito_agent.console.memory",
    "cogito_agent.console.services.chat",
    "cogito_agent.console.services.overview",
    "cogito_agent.console.status",
    "cogito_agent.console.trace_views",
}


def test_channel_direct_sql_debt_does_not_grow() -> None:
    assert _direct_sql_modules("api") == KNOWN_API_DIRECT_SQL_MODULES
    assert _direct_sql_modules("console") == KNOWN_CONSOLE_DIRECT_SQL_MODULES


def _mutating_routes_with_direct_sql(package: str) -> set[str]:
    violations: set[str] = set()
    for path in (SOURCE_ROOT / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = {
                decorator.func.attr
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
            }
            if not methods.intersection({"post", "put", "patch", "delete"}):
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                    continue
                if child.func.attr not in {"execute", "executemany"}:
                    continue
                if isinstance(child.func.value, ast.Attribute) and (
                    child.func.value.attr == "connection"
                ):
                    violations.add(f"{_module_name(path)}:{node.name}")
    return violations


def test_channel_mutations_use_application_services() -> None:
    assert _mutating_routes_with_direct_sql("api") == set()
    assert _mutating_routes_with_direct_sql("console") == set()


def test_capability_registry_invocation_has_one_production_entry_point() -> None:
    callers: set[str] = set()
    invocation_markers = (
        "self._registry.invoke(",
        "self._cap_reg.invoke(",
        "registry.invoke(",
    )
    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if any(marker in source for marker in invocation_markers):
            callers.add(_module_name(path))
    assert callers == {"cogito_agent.execution.executor"}


def test_chat_channels_use_application_service() -> None:
    channel_files = (
        SOURCE_ROOT / "api" / "app.py",
        SOURCE_ROOT / "console" / "router.py",
        SOURCE_ROOT / "cli" / "chat.py",
    )
    forbidden = ("kernel.process(", "kernel.process_stream(", "kernel.resume(")
    for path in channel_files:
        source = path.read_text(encoding="utf-8")
        assert not any(marker in source for marker in forbidden), path
