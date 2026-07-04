import os
import logging
import tempfile
import aiofiles
import uuid
from typing import List
from fastapi import APIRouter, UploadFile, status, Request, Form, File
from fastapi.responses import JSONResponse
from helpers.confg import get_settings
from controllers import DataController, ProjectController, NLPController
from models import ResponseSignal
from models.ProjectModel import ProjectModel
from models.CourseModel import CourseModel
from models.ChunkModel import ChunkModel
from models.AssetModel import AssetModel
from models.db_schemes import DataChunk, Asset, Course
from models.enums.AssetTypeEnum import AssetTypeEnum
from stores.document_processing import KnowledgeBaseProcessor, ChatAttachmentProcessor
from langchain_core.documents import Document
from routes.schemes.nlp import SearchRequest
from routes.schemes.courses import CreateCourseRequest, ProcessCourseRequest, IndexCourseRequest

logger = logging.getLogger('uvicorn.error')

courses_router = APIRouter(
    prefix="/api/v1/courses",
    tags=["api_v1", "courses"],
)


@courses_router.post("")
async def create_course(
    request: Request,
    course_req: CreateCourseRequest,
):
    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )

    existing = await course_model.get_course_by_code(code=course_req.code)
    if existing:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"signal": "course_code_exists", "code": course_req.code}
        )

    course = Course(
        code=course_req.code,
        name=course_req.name,
        department=course_req.department,
    )
    course = await course_model.create_course(course=course)

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )
    await project_model.get_or_create_project_for_course(
        course_id=course.id,
        project_name=f"{course.code} Knowledge Base",
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": "course_created",
            "id": str(course.id),
            "code": course.code,
            "name": course.name,
            "department": course.department,
        }
    )


@courses_router.get("")
async def list_courses(request: Request):
    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )
    courses = await course_model.get_all_courses()
    return JSONResponse(
        content={
            "signal": "courses_retrieved",
            "courses": [
                {
                    "code": c.code,
                    "name": c.name,
                    "department": c.department,
                }
                for c in courses
            ]
        }
    )


@courses_router.post("/{course_code}/upload")
async def course_upload(
    request: Request,
    course_code: str,
    file: UploadFile,
    type: str = Form("other"),
    lecture_id: str = Form(None),
    lecture_name: str = Form(None),
):
    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )
    course = await course_model.get_course_by_code(code=course_code)
    if not course:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"signal": ResponseSignal.COURSE_NOT_FOUND.value}
        )

    if type not in ("lecture", "book", "other"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": "type must be one of: lecture, book, other"}
        )

    if type == "lecture" and (not lecture_id or not lecture_name):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": "lecture_id and lecture_name are required when type is lecture"}
        )

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )
    project = await project_model.get_or_create_project_for_course(
        course_id=course.id,
        project_name=f"{course.code} Knowledge Base",
    )

    data_controller = DataController()
    is_valid, result_signal = data_controller.validate_uploaded_file(file=file)
    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": f"File validation failed: {result_signal}"}
        )

    file_path, file_id = data_controller.generate_unique_filepath(
        original_filename=file.filename,
        project_id=project.project_id,
    )

    try:
        async with aiofiles.open(file_path, 'wb') as out_file:
            while chunk := await file.read(512 * 1024):
                await out_file.write(chunk)
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.FILE_UPLOAD_FAILED.value}
        )

    asset_config = {"type": type}
    if type == "lecture":
        asset_config["lecture_id"] = lecture_id
        asset_config["lecture_name"] = lecture_name

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )
    asset_resource = Asset(
        asset_project_id=project.project_id,
        asset_course_id=course.id,
        asset_type=AssetTypeEnum.FILE.value,
        asset_name=file_id,
        asset_size=os.path.getsize(file_path),
        asset_config=asset_config,
    )
    asset_record = await asset_model.create_asset(asset=asset_resource)

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal": "file_uploaded",
            "file_id": asset_record.asset_id,
            "file_type": type,
            "lecture_id": lecture_id,
            "lecture_name": lecture_name,
            "course_code": course_code,
        }
    )


@courses_router.post("/{course_code}/process")
async def course_process(
    request: Request,
    course_code: str,
    process_req: ProcessCourseRequest,
):
    import asyncio

    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )
    course = await course_model.get_course_by_code(code=course_code)
    if not course:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"signal": ResponseSignal.COURSE_NOT_FOUND.value}
        )

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )
    project = await project_model.get_or_create_project_for_course(
        course_id=course.id,
        project_name=f"{course.code} Knowledge Base",
    )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )
    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=getattr(request.app, "groq_generation_client", request.app.generation_client),
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    if process_req.do_reset == 1:
        collection_name = nlp_controller.create_collection_name(
            project_id=project.project_id,
            course_code=course_code,
        )
        _ = await request.app.vectordb_client.delete_collection(
            collection_name=collection_name
        )
        _ = await chunk_model.delete_chunks_by_project_id(
            project_id=project.project_id
        )

    if process_req.file_id is not None:
        asset_ids = [process_req.file_id]
    else:
        all_assets = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id,
            asset_type=AssetTypeEnum.FILE.value,
        )
        asset_ids = [a.asset_id for a in all_assets]

    base_path = ProjectController().get_project_path(project_id=project.project_id)
    kb_processor = KnowledgeBaseProcessor(
        embedding_client=request.app.embedding_client,
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
    )

    total_inserted = 0
    processed = []
    skipped = []

    for aid in asset_ids:
        asset_record = await asset_model.get_asset_by_id(asset_id=aid)
        if not asset_record:
            continue

        existing = await chunk_model.get_chunks_by_asset_id(asset_id=aid)
        if existing and process_req.do_reset != 1:
            skipped.append({"file_id": aid, "reason": "already_processed"})
            continue

        file_path = os.path.join(base_path, asset_record.asset_name)
        if not os.path.exists(file_path):
            skipped.append({"file_id": aid, "reason": "file_not_found_on_disk"})
            continue

        logger.info(f"Processing file: {file_path}")
        try:
            chunks = await asyncio.wait_for(
                asyncio.to_thread(
                    kb_processor.get_chunks,
                    file_path=file_path,
                    file_id=asset_record.asset_name,
                    chunk_size=process_req.chunk_size,
                    overlap=process_req.overlap,
                    extract_tables=process_req.extract_tables,
                    extract_images=process_req.extract_images,
                    enable_ocr=process_req.enable_ocr,
                ),
                timeout=120,
            )
        except asyncio.TimeoutError:
            logger.error(f"Processing timed out for: {file_path}")
            skipped.append({"file_id": aid, "reason": "timed_out"})
            continue

        if not chunks:
            skipped.append({"file_id": aid, "reason": "processing_failed"})
            continue

        asset_config = asset_record.asset_config or {}
        asset_type = asset_config.get("type", "other")
        if asset_type == "lecture":
            asset_lecture_id = asset_config.get("lecture_id")
            asset_lecture_name = asset_config.get("lecture_name")
        else:
            asset_lecture_id = None
            asset_lecture_name = None

        chunk_records = [
            DataChunk(
                chunk_text=chunk.page_content,
                chunk_metadata={
                    **chunk.metadata,
                    "source": asset_record.asset_name,
                    "asset_id": asset_record.asset_id,
                    "type": asset_type,
                    "lecture_id": asset_lecture_id,
                    "lecture_name": asset_lecture_name,
                },
                chunk_order=i + 1,
                chunk_project_id=project.project_id,
                chunk_asset_id=asset_record.asset_id,
                chunk_course_id=course.id,
            )
            for i, chunk in enumerate(chunks)
        ]

        inserted = await chunk_model.insert_many_chunks(chunks=chunk_records)
        total_inserted += inserted
        processed.append({"file_id": aid, "inserted_chunks": inserted})

    return JSONResponse(
        content={
            "signal": ResponseSignal.PROCESSING_SUCCESS.value,
            "course_code": course_code,
            "processed": processed,
            "skipped": skipped,
            "total_inserted_chunks": total_inserted,
        }
    )


@courses_router.post("/{course_code}/index")
async def course_index(
    request: Request,
    course_code: str,
    index_req: IndexCourseRequest,
):
    import asyncio

    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )
    course = await course_model.get_course_by_code(code=course_code)
    if not course:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"signal": ResponseSignal.COURSE_NOT_FOUND.value}
        )

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )
    project = await project_model.get_or_create_project_for_course(
        course_id=course.id,
        project_name=f"{course.code} Knowledge Base",
    )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )
    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    kb_processor = KnowledgeBaseProcessor(
        embedding_client=request.app.embedding_client,
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
    )

    collection_name = nlp_controller.create_collection_name(
        project_id=project.project_id,
        course_code=course_code,
    )
    await kb_processor.create_vector_collection(
        collection_name=collection_name,
        embedding_size=request.app.embedding_client.embedding_size,
        do_reset=bool(index_req.do_reset),
    )

    if index_req.file_id is not None:
        asset_ids = [index_req.file_id]
    else:
        all_assets = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id,
            asset_type=AssetTypeEnum.FILE.value,
        )
        asset_ids = [a.asset_id for a in all_assets]

    total_indexed = 0
    indexed = []
    skipped = []

    for aid in asset_ids:
        chunk_records = await chunk_model.get_chunks_by_asset_id(asset_id=aid)
        if not chunk_records:
            skipped.append({"file_id": aid, "reason": "no_chunks_found"})
            continue

        texts = [c.chunk_text for c in chunk_records]
        metadata = [c.chunk_metadata for c in chunk_records]
        chunk_ids = [c.chunk_id for c in chunk_records]

        docs = [
            Document(page_content=c.chunk_text, metadata=c.chunk_metadata)
            for c in chunk_records
        ]
        vectors = await asyncio.to_thread(kb_processor.embed_chunks, docs)

        if not vectors:
            skipped.append({"file_id": aid, "reason": "embedding_failed"})
            continue

        await kb_processor.store_vectors(
            collection_name=collection_name,
            texts=texts,
            vectors=vectors,
            metadata=metadata,
            record_ids=chunk_ids,
        )

        total_indexed += len(chunk_records)
        indexed.append({"file_id": aid, "indexed_chunks": len(chunk_records)})

    return JSONResponse(
        content={
            "signal": "indexing_success",
            "course_code": course_code,
            "indexed": indexed,
            "skipped": skipped,
            "total_indexed_chunks": total_indexed,
        }
    )


@courses_router.post("/{course_code}/search")
async def course_search(
    request: Request,
    course_code: str,
    search_request: SearchRequest,
):
    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )
    course = await course_model.get_course_by_code(code=course_code)
    if not course:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"signal": ResponseSignal.COURSE_NOT_FOUND.value}
        )

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )
    project = await project_model.get_or_create_project_for_course(
        course_id=course.id,
        project_name=f"{course.code} Knowledge Base",
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    results = await nlp_controller.search_vector_db_collection(
        project=project, text=search_request.text, limit=search_request.limit,
        course_code=course_code,
    )

    if not results:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.COURSE_SEARCH_ERROR.value}
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.COURSE_SEARCH_SUCCESS.value,
            "course_code": course_code,
            "results": [r.dict() for r in results]
        }
    )


@courses_router.post("/{course_code}/answer")
async def course_answer(
    request: Request,
    course_code: str,
    text: str = Form(...),
    limit: int = Form(5),
    files: List[UploadFile] = File(None),
):
    course_model = await CourseModel.create_instance(
        db_client=request.app.db_client
    )
    course = await course_model.get_course_by_code(code=course_code)
    if not course:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"signal": ResponseSignal.COURSE_NOT_FOUND.value}
        )

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )
    project = await project_model.get_or_create_project_for_course(
        course_id=course.id,
        project_name=f"{course.code} Knowledge Base",
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=getattr(request.app, "groq_generation_client", request.app.generation_client),
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    additional_context = []
    file_sources = []

    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 100
    def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
        result = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            result.append(text[start:end])
            if end == len(text):
                break
            start += size - overlap
        return result

    if files:
        processor = ChatAttachmentProcessor(
            embedding_client=request.app.embedding_client,
            generation_client=request.app.generation_client,
        )
        for f in files:
            if not f.filename:
                continue
            tmp_dir = tempfile.mkdtemp()
            file_path = os.path.join(tmp_dir, f.filename)
            try:
                async with aiofiles.open(file_path, 'wb') as out_file:
                    while chunk := await f.read(512 * 1024):
                        await out_file.write(chunk)
                content = processor.process_attachment(
                    file_path=file_path,
                    file_id=f.filename,
                    query=text,
                )
                logger.info(f"File {f.filename}: extracted {len(content)} chars, preview={content[:100]!r}")
                if content:
                    chunks = chunk_text(content)
                    additional_context.extend(chunks)
                    file_sources.append({"file": f.filename, "content_preview": content[:200]})
            except Exception as e:
                logger.warning(f"Failed to process uploaded file {f.filename}: {e}")
            finally:
                try:
                    os.remove(file_path)
                    os.rmdir(tmp_dir)
                except Exception:
                    pass

    answer, full_prompt, chat_history, retrieved_documents = await nlp_controller.answer_rag_question(
        project=project,
        query=text,
        limit=limit,
        course_code=course_code,
        additional_context=additional_context if additional_context else None,
    )

    logger.info(f"KB results: {len(retrieved_documents) if retrieved_documents else 0}, "
                f"uploaded contexts: {len(additional_context)}, "
                f"answer length: {len(answer) if answer else 0}")

    if not answer:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.COURSE_ANSWER_ERROR.value}
        )

    sources = []
    if retrieved_documents:
        sources += [
            {
                "content": doc.text,
                "chunk_type": doc.chunk_type,
                "page": doc.page,
                "source_file": doc.source_file,
                "score": doc.score,
                "type": "kb",
            }
            for doc in retrieved_documents
        ]
    if file_sources:
        sources += [
            {**fs, "type": "upload"}
            for fs in file_sources
        ]

    return JSONResponse(
        content={
            "signal": ResponseSignal.COURSE_ANSWER_SUCCESS.value,
            "course_code": course_code,
            "answer": answer,
            "full_prompt": full_prompt,
            "chat_history": chat_history,
            "sources": sources,
        }
    )
