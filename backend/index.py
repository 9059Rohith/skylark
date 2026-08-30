"""Serverless entrypoint; the Docker service continues to use ``app.main``."""

from app.main import app

__all__ = ["app"]
