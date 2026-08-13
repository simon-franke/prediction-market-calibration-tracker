from prediction_market_tracker.dashboard import app


def test_settings_prefer_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@db.example/tracker")

    assert app._setting("DATABASE_URL") == "postgresql://user:password@db.example/tracker"
