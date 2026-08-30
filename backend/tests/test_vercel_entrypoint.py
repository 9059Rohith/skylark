"""Deployment entrypoint contract for Vercel's FastAPI runtime."""


def test_root_entrypoint_exports_fastapi_application() -> None:
    """Removing the root shim must break the serverless deployment contract."""
    from index import app

    assert app.title == "Skylark Signal"
    assert {route.path for route in app.routes} >= {"/health", "/chat"}
