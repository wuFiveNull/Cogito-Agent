from __future__ import annotations

from importlib import resources

from cogito_agent.skill.builtin.loader import BUILTIN_SKILL_MANIFESTS


def test_console_resources_are_packaged() -> None:
    package = resources.files("cogito_agent.console")
    assert package.joinpath("templates", "console", "base.html").is_file()
    assert package.joinpath("templates", "console", "overview.html").is_file()
    assert package.joinpath("static", "console.css").is_file()
    assert package.joinpath("static", "htmx.min.js").is_file()


def test_migration_resources_are_packaged() -> None:
    package = resources.files("cogito_agent.storage.migrations")
    migration_names = sorted(
        item.name for item in package.iterdir() if item.name.endswith(".sql")
    )
    assert migration_names == [
        "0001_initial.sql",
        "0002_memory_v2.sql",
        "0003_memory_v2_complete.sql",
        "0011_approval_tool_call.sql",
    ]


def test_builtin_skills_are_available() -> None:
    assert {manifest.name for manifest in BUILTIN_SKILL_MANIFESTS} == {
        "daily_brief",
        "inbox_digest",
        "memory_consolidation",
        "project_status",
        "task_extraction",
        "trace_review",
    }
