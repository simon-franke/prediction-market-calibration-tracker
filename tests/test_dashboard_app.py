from prediction_market_tracker.dashboard import app


def test_database_url_prefers_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@db.example/tracker")

    assert app._database_url() == "postgresql://user:password@db.example/tracker"
