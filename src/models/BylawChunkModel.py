from typing import Optional
from sqlalchemy.future import select
from sqlalchemy import func
from .BaseDataModel import BaseDataModel
from .db_schemes import BylawChunk


class BylawChunkRepository(BaseDataModel):

    def __init__(self, db_client: object):
        super().__init__(db_client=db_client)

    @classmethod
    async def create_instance(cls, db_client: object):
        return cls(db_client)

    async def create_chunk(self, chunk: BylawChunk) -> BylawChunk:
        async with self.db_client() as session:
            async with session.begin():
                session.add(chunk)
                await session.flush()
                await session.refresh(chunk)
        return chunk

    async def get_last_chunk_order(self) -> Optional[int]:
        async with self.db_client() as session:
            result = await session.execute(
                select(func.max(BylawChunk.chunk_order))
            )
            return result.scalar_one()

    async def get_chunk(self, chunk_id: int) -> Optional[BylawChunk]:
        async with self.db_client() as session:
            result = await session.execute(
                select(BylawChunk).where(BylawChunk.chunk_id == chunk_id)
            )
            return result.scalar_one_or_none()

    async def list_chunks(self, page: int = 1, page_size: int = 50) -> list[BylawChunk]:
        async with self.db_client() as session:
            result = await session.execute(
                select(BylawChunk)
                .offset((page - 1) * page_size)
                .limit(page_size)
                .order_by(BylawChunk.chunk_id.desc())
            )
            return result.scalars().all()
