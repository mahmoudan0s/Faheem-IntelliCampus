from pydantic import BaseModel, Field
from typing import Optional


class AdvisorQuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="Student's question")
    student_code: Optional[str] = Field(None, description="Student code for personal questions")
    department: Optional[str] = Field(None, description="Department name to filter bylaw results (e.g. AI, CS, IT, IS, DS)")


class AdvisorQuestionResponse(BaseModel):
    answer: str = Field(..., description="Advisor's answer")
