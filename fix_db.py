import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def fix():
    e = create_async_engine('postgresql+asyncpg://postgres:0000@localhost:5432/minirag-postgres')
    async with e.begin() as c:
        # Drop old incompatible bylaw_chunks table
        await c.execute(text("DROP TABLE IF EXISTS bylaw_chunks CASCADE"))
        # Fix alembic version - remove orphaned entry
        await c.execute(text("DELETE FROM alembic_version"))
        # Stamp with the last known good migration
        await c.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0a9157642013')"))
        print("Done")
    await e.dispose()

asyncio.run(fix())
