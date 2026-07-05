import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def chk():
    e = create_async_engine('postgresql+asyncpg://postgres:0000@localhost:5432/minirag-postgres')
    async with e.connect() as c:
        r = await c.execute(text("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = 'bylaw_chunks' ORDER BY ordinal_position"))
        print('bylaw_chunks columns:')
        for row in r:
            print(f'  {row[0]} {row[1]} nullable={row[2]}')
    await e.dispose()

asyncio.run(chk())
