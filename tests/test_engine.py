from ytdb.db.engine import get_sslmode, normalize_database_url


def test_normalize_database_url_rewrites_postgres_scheme():
    assert (
        normalize_database_url("postgres://user:pass@host/db")
        == "postgresql://user:pass@host/db"
    )


def test_get_sslmode_for_render_host():
    url = "postgresql://user:pass@dpg-abc.oregon-postgres.render.com/ytdb"
    assert get_sslmode(url) == "require"


def test_get_sslmode_respects_env_override(monkeypatch):
    monkeypatch.setenv("DB_SSLMODE", "disable")
    url = "postgresql://user:pass@dpg-abc.oregon-postgres.render.com/ytdb"
    assert get_sslmode(url) == "disable"
