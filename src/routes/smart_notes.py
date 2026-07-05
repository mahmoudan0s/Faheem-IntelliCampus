from fastapi import APIRouter, status, Request
from fastapi.responses import JSONResponse
from routes.schemes.smart_notes import EnhanceNotesRequest
from models.CourseModel import CourseModel
from models.ProjectModel import ProjectModel
from controllers.NLPController import NLPController
from models import ResponseSignal
import logging

logger = logging.getLogger('uvicorn.error')

smart_notes_router = APIRouter(
    prefix="/api/v1/courses",
    tags=["api_v1", "smart_notes"],
)

SYSTEM_PROMPT = (
    "You are an academic learning assistant.\n"
    "Your primary source of truth is the retrieved course material.\n"
    "Your job is to transform rough student notes into a complete and organized study guide.\n\n"
    "Rules:\n"
    "- Preserve the student's original ideas.\n"
    "- Improve structure and readability.\n"
    "- Add missing concepts from the retrieved course material.\n"
    "- Explain difficult concepts.\n"
    "- Add examples when useful.\n"
    "- Add practical intuition.\n"
    "- Add important exam notes.\n"
    "- Add related topics.\n"
    "- Recommend useful resources.\n"
    "- Use your own knowledge only when it helps explain concepts better.\n"
    "- Never contradict the retrieved course material.\n"
    "- Never invent lecture-specific facts.\n"
    "- If information is not supported by the retrieved material, clearly avoid presenting it as course content.\n\n"
    "The final output must be well-structured Markdown."
)

USER_PROMPT_TEMPLATE = (
    "## Student's Notes\n"
    "{notes}\n\n"
    "## Retrieved Course Material\n"
    "{context}\n\n"
    "Based on the student's notes and the retrieved course material above, "
    "generate a complete and organized study guide following the required structure."
)


def _build_sources_section(documents: list) -> str:
    pages_by_label = {}
    for doc in documents:
        meta = doc.metadata or {}
        label = meta.get("lecture_name")
        if not label:
            continue
        page = meta.get("page")
        if label not in pages_by_label:
            pages_by_label[label] = set()
        if page is not None:
            pages_by_label[label].add(page)
    if not pages_by_label:
        return ""
    lines = ["## Sources", ""]
    for label in sorted(pages_by_label):
        pages = sorted(pages_by_label[label])
        parts = [f"- {label}"]
        if pages:
            page_str = ", ".join(str(p) for p in pages)
            parts.append(f"(Pages {page_str})")
        lines.append(" ".join(parts))
    lines.append("")
    return "\n".join(lines)


def _filter_by_lecture(retrieved_documents: list, lecture_id: str = None) -> list:
    if not lecture_id:
        return list(retrieved_documents)
    filtered = [
        doc for doc in retrieved_documents
        if (doc.metadata or {}).get("lecture_id") == lecture_id
    ]
    return filtered if filtered else list(retrieved_documents)


def _build_context(documents: list) -> str:
    if not documents:
        return ""
    parts = []
    for idx, doc in enumerate(documents):
        meta = doc.metadata or {}
        header = f"Document {idx + 1}"
        labels = []
        sf = meta.get("source_file") or meta.get("source")
        if sf:
            labels.append(sf)
        if meta.get("page") is not None:
            labels.append(f"Page {meta['page']}")
        if meta.get("lecture_id"):
            labels.append(f"Lecture {meta['lecture_id']}")
        if labels:
            header += f" — {', '.join(labels)}"
        parts.append(f"### {header}\n{doc.text}")
    return "\n\n".join(parts)


@smart_notes_router.post("/{course_code}/smart-notes/enhance")
async def enhance_notes(
    request: Request,
    course_code: str,
    body: EnhanceNotesRequest,
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

    retrieved_documents = await nlp_controller.search_vector_db_collection(
        project=project,
        text=body.notes,
        limit=10,
        course_code=course_code,
    )

    if not retrieved_documents:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": "smart_notes_retrieval_error"}
        )

    relevant_docs = _filter_by_lecture(retrieved_documents, lecture_id=body.lecture_id)
    if not relevant_docs:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": "smart_notes_no_relevant_content"}
        )

    context = _build_context(relevant_docs)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        notes=request.app.generation_client.process_text(body.notes),
        context=context,
    )

    sources_section = _build_sources_section(relevant_docs)

    chat_history = [
        request.app.generation_client.construct_prompt(
            prompt=SYSTEM_PROMPT,
            role=request.app.generation_client.enums.SYSTEM.value,
        )
    ]

    answer = request.app.generation_client.generate_text(
        prompt=user_prompt,
        chat_history=chat_history,
        max_output_tokens=2048,
        temperature=0.3,
    )

    if not answer:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"signal": ResponseSignal.RAG_ANSWER_ERROR.value}
        )

    if sources_section:
        answer = answer.rstrip() + "\n\n" + sources_section

    return JSONResponse(
        content={
            "content": answer,
        }
    )
