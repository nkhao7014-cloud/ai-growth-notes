"""Render deployment smoke tests that never connect to a real database."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_USERNAME", "smoke-user")
os.environ.setdefault("APP_PASSWORD_HASH", "not-used-by-these-tests")
os.environ.setdefault("SESSION_SECRET", "deployment-smoke-secret-at-least-32-characters")
os.environ.setdefault("DATABASE_URL", "postgresql://smoke:smoke@db.invalid/smoke")

import main
from fastapi.testclient import TestClient


def client_with_database_status(healthy: bool) -> TestClient:
    initialization = patch.object(main, "initialize_database", return_value=None)
    health_check = patch.object(main, "database_health_check", return_value=healthy)
    initialization.start()
    health_check.start()
    client = TestClient(main.app)
    client.__enter__()
    client._deployment_patches = (initialization, health_check)  # type: ignore[attr-defined]
    return client


def close_client(client: TestClient) -> None:
    try:
        client.__exit__(None, None, None)
    finally:
        for active_patch in client._deployment_patches:  # type: ignore[attr-defined]
            active_patch.stop()


def test_main_imports_and_resource_paths_exist():
    assert main.app is not None
    assert main.ROOT == Path(main.__file__).resolve().parent
    assert (main.ROOT / "templates" / "login.html").is_file()
    assert (main.ROOT / "static" / "index.html").is_file()


def test_health_is_public_and_reports_database_ok():
    client = client_with_database_status(True)
    try:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
    finally:
        close_client(client)


def test_login_page_and_static_asset_are_available():
    client = client_with_database_status(True)
    try:
        login = client.get("/login")
        static = client.get("/static/ai-daily.css")
        assert login.status_code == 200
        assert static.status_code == 200
    finally:
        close_client(client)


def test_health_failure_is_safe():
    secret_url = "postgresql://secret-user:secret-password@db.invalid/private"
    client = client_with_database_status(False)
    try:
        with patch.dict(os.environ, {"DATABASE_URL": secret_url}):
            response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable", "database": "unavailable"}
        assert secret_url not in response.text
        assert "secret-password" not in response.text
    finally:
        close_client(client)
