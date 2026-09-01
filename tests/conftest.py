import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import get_db
from app.core.main import create_app
from app.core.models import Base
import os

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URL"]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def create_schema():
    engine = create_async_engine(TEST_DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()
    yield


@pytest.fixture
def app():
    return create_app()


@pytest_asyncio.fixture
async def db_session(create_schema):
    engine = create_async_engine(TEST_DATABASE_URL)

    try:
        async with engine.connect() as conn:
            await conn.begin()

            session_maker = async_sessionmaker(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )

            async with session_maker() as session:
                yield session

            await conn.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(app, db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as async_client:
        yield async_client
    app.dependency_overrides.clear()
