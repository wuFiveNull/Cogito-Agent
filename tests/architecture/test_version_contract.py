from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _app_version() -> str:
    path = ROOT / "src" / "cogito_agent" / "version.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "APP_VERSION"
                for target in node.targets
            ):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    return node.value.value
    raise AssertionError("APP_VERSION must be a string literal")


def test_package_version_matches_application_version() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]
    assert project_version == _app_version()


def test_quality_workflow_does_not_pin_a_different_version() -> None:
    workflow = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert f"cogito_agent.__version__ == '{_app_version()}'" in workflow
