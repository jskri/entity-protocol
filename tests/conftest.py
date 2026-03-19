import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import server.state as state
from server.db import BankAccount, Base, Event, User


@pytest_asyncio.fixture
async def engine():
    url = os.environ["DATABASE_URL"]
    e = create_async_engine(url)
    # Make sure the database is ready.
    for attempt in range(20):
        try:
            async with e.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            break
        except Exception:
            if attempt == 19:
                raise
            await asyncio.sleep(0.5)
    yield e
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await e.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncSession:  # type: ignore[override]
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def clean_db(engine) -> None:  # type: ignore[override]
    yield
    async with engine.begin() as conn:
        await conn.execute(sa_delete(Event))
        await conn.execute(sa_delete(BankAccount))
        await conn.execute(sa_delete(User))


@pytest.fixture(autouse=True)
def reset_watch_state() -> None:
    state.reset()
    yield  # type: ignore[misc]
    state.reset()
