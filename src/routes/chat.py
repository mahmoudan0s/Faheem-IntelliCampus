import os
import logging
import tempfile
import aiofiles
from fastapi import APIRouter, UploadFile, status, Request, Form
from fastapi.responses import JSONResponse
from controllers import DataController
from stores.document_processing import ChatAttachmentProcessor
from models import ResponseSignal

logger = logging.getLogger('uvicorn.error')

chat_router = APIRouter(
    prefix="/api/v1/chat",
    tags=["api_v1", "chat"],
)


@chat_router.post("/attachment")
async def chat_attachment(
    request: Request,
    file: UploadFile,
    message: str = Form(...),
):
    data_controller = DataController()
    is_valid, result_signal = data_controller.validate_uploaded_file(file=file)
    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": f"File validation failed: {result_signal}"}
        )

    tmp_dir = tempfile.mkdtemp()
    file_path = os.path.join(tmp_dir, file.filename or "attachment")
    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            while chunk := await file.read(512 * 1024):
                await out_file.write(chunk)

        processor = ChatAttachmentProcessor(
            embedding_client=request.app.embedding_client,
            generation_client=request.app.generation_client,
        )

        extracted_content = processor.process_attachment(
            file_path=file_path,
            file_id=file.filename or "attachment",
            query=message,
        )

        if not extracted_content:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"signal": ResponseSignal.CHAT_ATTACHMENT_ERROR.value}
            )

        answer = processor.generate_answer(
            extracted_content=extracted_content,
            user_message=message,
        )

        return JSONResponse(
            content={
                "signal": ResponseSignal.CHAT_ATTACHMENT_SUCCESS.value,
                "content": extracted_content,
                "answer": answer or "",
            }
        )
    except Exception as e:
        logger.error(f"Chat attachment error: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"signal": ResponseSignal.CHAT_ATTACHMENT_ERROR.value}
        )
    finally:
        try:
            os.remove(file_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass
