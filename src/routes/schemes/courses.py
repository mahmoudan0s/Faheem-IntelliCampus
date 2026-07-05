from pydantic import BaseModel
from typing import Optional

class CreateCourseRequest(BaseModel):
    code: str
    name: str
    department: Optional[str] = None


class ProcessCourseRequest(BaseModel):
    file_id: Optional[int] = None
    chunk_size: int = 700
    overlap: int = 100
    do_reset: int = 0
    extract_tables: bool = False
    extract_images: bool = False
    enable_ocr: bool = False


class IndexCourseRequest(BaseModel):
    file_id: Optional[int] = None
    do_reset: int = 0
