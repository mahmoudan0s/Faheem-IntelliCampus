import logging
from typing import List
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from services.bylaw_service import BylawService
from routes.schemes.admin_bylaw import CreateBylawChunkRequest
from models.BylawChunkModel import BylawChunkRepository

logger = logging.getLogger("uvicorn")

admin_bylaw_router = APIRouter(
    prefix="/api/v1/admin/bylaw",
    tags=["api_v1", "admin", "bylaw"],
)


@admin_bylaw_router.post("/chunks")
async def create_bylaw_chunks(
    request: Request,
    chunks_req: List[CreateBylawChunkRequest],
):
    service = BylawService(
        db_client=request.app.db_client,
        vectordb_client=request.app.vectordb_client,
        embedding_client=request.app.embedding_client,
    )

    try:
        chunks_data = [c.model_dump() for c in chunks_req]
        results = await service.upload_chunks(chunks_data)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"chunks": results},
        )
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": "validation_error", "detail": str(e)},
        )
    except RuntimeError as e:
        logger.error(f"Bylaw chunks upload failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"signal": "indexing_failed", "detail": str(e)},
        )
    except Exception as e:
        logger.error(f"Unexpected error during bylaw chunks upload: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"signal": "internal_error", "detail": "An unexpected error occurred."},
        )


@admin_bylaw_router.get("/chunks")
async def list_bylaw_chunks(
    request: Request,
    page: int = 1,
    page_size: int = 50,
):
    repo = await BylawChunkRepository.create_instance(
        db_client=request.app.db_client
    )

    try:
        chunks = await repo.list_chunks(page=page, page_size=page_size)
        return JSONResponse(
            content={
                "chunks": [
                    {
                        "chunk_id": c.chunk_id,
                        "chunk_uuid": str(c.chunk_uuid),
                        "metadata": c.metadata_,
                        "chunk_order": c.chunk_order,
                        "created_at": str(c.created_at) if c.created_at else None,
                    }
                    for c in chunks
                ],
                "page": page,
                "page_size": page_size,
            }
        )
    except Exception as e:
        logger.error(f"Failed to list bylaw chunks: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"signal": "internal_error", "detail": "Failed to retrieve chunks."},
        )
