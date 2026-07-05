import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("uvicorn")


class PostgresConnection:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def execute(self, query, params: Optional[dict] = None):
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(query, params or {})
                return result

    async def fetch_all(self, query, params: Optional[dict] = None):
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(query, params or {})
                return result.fetchall()

    async def fetch_one(self, query, params: Optional[dict] = None):
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(query, params or {})
                return result.fetchone()
