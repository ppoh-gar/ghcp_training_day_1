import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("TICKET_DB_PATH", "/tmp/ghcp_training_pytest/default.duckdb")
os.environ.setdefault("NICEGUI_SECRET", "test-secret")


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "tickets.duckdb"


@pytest.fixture
def client(temp_db_path: Path) -> TestClient:
    from app.main import create_app

    app = create_app(database_path=str(temp_db_path), seed=True)
    with TestClient(app) as test_client:
        yield test_client
