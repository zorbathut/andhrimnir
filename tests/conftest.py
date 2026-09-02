import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from andhrimnir.config import Settings
from andhrimnir.db import init_db
from andhrimnir.main import app_create

from .fakes import TemperatureSourceFake


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test.db")


@pytest_asyncio.fixture
async def conn(db_path):
    connection = await init_db(db_path)
    yield connection
    await connection.close()


@pytest.fixture
def source() -> TemperatureSourceFake:
    return TemperatureSourceFake()


@pytest.fixture
def client(db_path, source):
    """A TestClient over a real SQLite file and a fake source, with the real lifespan."""
    app = app_create(Settings(db_path=db_path), source, lambda: init_db(db_path))
    with TestClient(app) as test_client:
        yield test_client
