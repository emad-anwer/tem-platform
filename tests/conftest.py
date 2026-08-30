import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.main import create_app
from app.core.db import get_db, get_engine


@pytest.fixture
def app():
    """Provides a FastAPI application instance."""
    return create_app()


@pytest_asyncio.fixture
async def db_session():
    """Provides a database session with nested transaction (SAVEPOINT) rollback.
    
    This ensures each test runs in isolation and rolls back its changes
    after completion, keeping the test database clean.
    """
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.begin()
        
        session_maker = async_sessionmaker(
            bind=conn, 
            expire_on_commit=False, 
            join_transaction_mode="create_savepoint"
        )
        async with session_maker() as session:
            yield session
            
        await conn.rollback()


@pytest_asyncio.fixture
async def client(app, db_session: AsyncSession):
    """Provides an httpx AsyncClient connected to the app, with the db_session injected."""
    async def override_get_db():
        yield db_session
        
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client

    app.dependency_overrides.clear()
