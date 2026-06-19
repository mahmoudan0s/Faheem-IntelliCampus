from pydantic import BaseModel
from typing import Optional


class AttachmentRequest(BaseModel):
    message: str


class AttachmentResponse(BaseModel):
    signal: str
    content: Optional[str] = None
    answer: Optional[str] = None
