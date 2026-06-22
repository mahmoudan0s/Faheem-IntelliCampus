from pydantic import BaseModel
from typing import Optional


class EnhanceNotesRequest(BaseModel):
    lecture_id: Optional[str] = None
    notes: str
