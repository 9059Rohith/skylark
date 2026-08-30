"""Deployment entrypoint contract for Vercel's FastAPI runtime."""

from pathlib import Path

from packaging.requirements import Requirement


def test_root_entrypoint_exports_fastapi_application() -> None:
    """Removing the root shim must break the serverless deployment contract."""
    from index import app

    assert app.title == "Skylark Signal"
    assert {route.path for route in app.routes} >= {"/health", "/chat"}


def test_serverless_requirements_are_direct_pep508_entries() -> None:
    """Recursive includes are rejected by Vercel's Python dependency parser."""
    requirements = Path(__file__).parents[1] / "requirements.txt"
    entries = [
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    parsed = [Requirement(entry) for entry in entries]

    assert {requirement.name for requirement in parsed} >= {
        "fastapi",
        "langgraph",
        "openai",
        "pytest",
    }
