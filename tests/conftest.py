"""All tests use a fresh temporary database, never a developer's configured data."""
import os
from pathlib import Path
import tempfile

import pytest


# This runs before test modules import app.config or app.db. Explicit assignments
# override even a production DATABASE_URL inherited from the invoking shell.
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="vio-pytest-")).resolve()
os.environ["VIO_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DATA_DIR / 'test.db').as_posix()}"
os.environ["VIO_DISABLE_WORKER"] = "1"
os.environ["VIO_SECURE_COOKIE"] = "0"


@pytest.fixture
def isolated_db():
    from app import config
    from app.db import Base, engine

    # Refuse destructive schema setup if an app was imported before this conftest.
    assert config.DATA_DIR == TEST_DATA_DIR
    assert engine.url.get_backend_name() == "sqlite"
    assert Path(engine.url.database).resolve().parent == TEST_DATA_DIR
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    (TEST_DATA_DIR / "setup.token").unlink(missing_ok=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(isolated_db):
    from app.db import SessionLocal

    with SessionLocal() as session:
        yield session


@pytest.fixture
def api_client(isolated_db, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.db import Base

    monkeypatch.setattr(main, "migrate", lambda: Base.metadata.create_all(isolated_db))
    main.login_attempts.clear()
    with TestClient(main.app) as client:
        yield client
    main.login_attempts.clear()
