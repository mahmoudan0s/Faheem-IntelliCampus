import asyncio
import logging
from typing import List
from sqlalchemy.sql import text as sql_text
from stores.llm.LLMEnums import DocumentTypeEnum
from models.db_schemes import BylawChunk

logger = logging.getLogger("uvicorn")

BYLAW_COLLECTION_NAME = "bylaw"


class BylawService:

    def __init__(self, db_client, vectordb_client, embedding_client):
        self.db_client = db_client
        self.vectordb_client = vectordb_client
        self.embedding_client = embedding_client

    async def _ensure_collection_exists(self, embedding_size: int):
        exists = await self.vectordb_client.is_collection_existed(
            collection_name=BYLAW_COLLECTION_NAME
        )
        if exists:
            return
        async with self.db_client() as session:
            async with session.begin():
                create_sql = sql_text(
                    f"CREATE TABLE {BYLAW_COLLECTION_NAME} ("
                    f"id bigserial PRIMARY KEY,"
                    f"text text, "
                    f"vector vector({embedding_size}), "
                    f"metadata jsonb DEFAULT '{{}}', "
                    f"chunk_id integer"
                    f")"
                )
                await session.execute(create_sql)
                await session.commit()

    async def upload_chunks(self, chunks_data: list[dict]) -> list[dict]:
        if not chunks_data:
            raise ValueError("Request body must be a non-empty list")

        for item in chunks_data:
            if not item.get("text") or not item["text"].strip():
                raise ValueError("Each chunk must have non-empty text")
            if "metadata" not in item:
                raise ValueError("Each chunk must have metadata")

        texts = [c["text"] for c in chunks_data]
        metadatas = [c["metadata"] for c in chunks_data]

        vectors = await asyncio.to_thread(
            self.embedding_client.embed_text,
            text=texts,
            document_type=DocumentTypeEnum.DOCUMENT.value,
        )
        if not vectors or len(vectors) != len(texts):
            raise RuntimeError("Embedding generation failed")

        await self._ensure_collection_exists(
            embedding_size=self.embedding_client.embedding_size
        )

        repo = await _get_repo(self.db_client)
        last_order = await repo.get_last_chunk_order()
        next_order = (last_order or 0) + 1

        inserted_chunks = []
        for i, item in enumerate(chunks_data):
            chunk = BylawChunk(
                text=item["text"],
                metadata_=item["metadata"],
                chunk_order=next_order + i,
            )
            chunk = await repo.create_chunk(chunk)
            inserted_chunks.append(chunk)

        chunk_ids = [c.chunk_id for c in inserted_chunks]
        pgvector_texts = [c.text for c in inserted_chunks]
        pgvector_metadatas = [
            {"chunk_id": c.chunk_id, **chunks_data[i]["metadata"]}
            for i, c in enumerate(inserted_chunks)
        ]

        try:
            inserted = await self.vectordb_client.insert_many(
                collection_name=BYLAW_COLLECTION_NAME,
                texts=pgvector_texts,
                vectors=vectors,
                metadata=pgvector_metadatas,
                record_ids=chunk_ids,
            )
            if not inserted:
                raise RuntimeError("PGVector batch indexing failed")
        except Exception:
            async with self.db_client() as session:
                async with session.begin():
                    await session.execute(
                        sql_text("DELETE FROM bylaw_chunks WHERE chunk_id = ANY(:ids)"),
                        {"ids": chunk_ids},
                    )
                    await session.commit()
            raise

        return [
            {
                "chunk_id": c.chunk_id,
                "chunk_uuid": str(c.chunk_uuid),
                "indexed": True,
                "message": "Bylaw chunk uploaded and indexed successfully.",
            }
            for c in inserted_chunks
        ]


async def _get_repo(db_client):
    from models.BylawChunkModel import BylawChunkRepository
    return await BylawChunkRepository.create_instance(db_client=db_client)
