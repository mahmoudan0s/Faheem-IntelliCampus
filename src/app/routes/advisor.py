import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request

from app.routes.schemas.advisor import AdvisorQuestionRequest, AdvisorQuestionResponse
from app.services.advisor_service import AdvisorService

logger = logging.getLogger("uvicorn")

advisor_router = APIRouter(prefix="/api/v1/advisor", tags=["advisor"])


def get_advisor_service(request: Request) -> AdvisorService:
    service = getattr(request.app.state, "advisor_service", None)
    if not service:
        raise HTTPException(status_code=503, detail="Advisor service not initialized")
    return service


@advisor_router.post("/ask", response_model=AdvisorQuestionResponse)
async def ask_advisor(
    req: AdvisorQuestionRequest,
    advisor_service: AdvisorService = Depends(get_advisor_service),
):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    logger.info(
        "Advisor request: student_code=%s, question=%s",
        req.student_code,
        req.question[:100],
    )

    answer = await advisor_service.process_question(
        question=req.question,
        student_code=req.student_code,
        department=req.department,
    )

    return AdvisorQuestionResponse(answer=answer)
