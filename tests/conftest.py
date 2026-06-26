import os

import pytest


@pytest.fixture(autouse=True)
def database_url_env(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:"),
    )
