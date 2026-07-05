from pydantic import BaseModel
from typing import Any, Optional


class CreateBylawChunkRequest(BaseModel):
    text: str
    metadata: dict[str, Any]
