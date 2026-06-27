import uuid
from sqlalchemy import Column, BigInteger, Integer, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from .minirag_base import SQLAlchemyBase


class BylawChunk(SQLAlchemyBase):
    __tablename__ = "bylaw_chunks"

    chunk_id = Column(BigInteger, primary_key=True, autoincrement=True)
    chunk_uuid = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False)
    text = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False)
    chunk_order = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
