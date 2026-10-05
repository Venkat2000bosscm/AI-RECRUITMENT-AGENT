import os
import sys
from pathlib import Path

import pytest

DB = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ.pop("OPENAI_API_KEY", None)
os.environ["UPLOAD_DIR"] = str(Path(__file__).parent / "uploads")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


def as_user(role_id: int) -> dict:
    return {"X-User-Id": str(role_id)}


RECRUITER, MANAGER, ADMIN, VIEWER = (as_user(i) for i in range(1, 5))
