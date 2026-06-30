import asyncio
import logging
from typing import Optional

import pyodbc

logger = logging.getLogger("uvicorn")


class SQLServerConnection:
    def __init__(self, host: str, port: int, database: str, username: str, password: str, driver: str = "ODBC Driver 18 for SQL Server"):
        self._conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={host},{port};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            f"TrustServerCertificate=yes;"
        )
        self._conn: Optional[pyodbc.Connection] = None

    async def connect(self):
        loop = asyncio.get_event_loop()
        try:
            self._conn = await loop.run_in_executor(
                None, lambda: pyodbc.connect(self._conn_str, autocommit=False)
            )
            logger.info("Connected to SQL Server: %s", self._conn_str.split("PWD=")[0])
        except Exception as e:
            logger.error("Failed to connect to SQL Server: %s", e)
            raise

    async def close(self):
        if self._conn:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._conn.close)
            self._conn = None
            logger.info("SQL Server connection closed")

    async def fetch_all(self, query: str, params: tuple = ()) -> list[dict]:
        if not self._conn:
            raise ConnectionError("SQL Server not connected")
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._fetch_all_sync, query, params)
        except Exception as e:
            logger.error("SQL Server query error: %s | Query: %s", e, query[:120])
            raise

    def _fetch_all_sync(self, query: str, params: tuple) -> list[dict]:
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def fetch_one(self, query: str, params: tuple = ()) -> Optional[dict]:
        rows = await self.fetch_all(query, params)
        return rows[0] if rows else None

    async def execute(self, query: str, params: tuple = ()):
        if not self._conn:
            raise ConnectionError("SQL Server not connected")
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._execute_sync, query, params)
        except Exception as e:
            logger.error("SQL Server execute error: %s | Query: %s", e, query[:120])
            raise

    def _execute_sync(self, query: str, params: tuple):
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        self._conn.commit()
        return cursor
