from pydantic import BaseModel
from typing import Optional

class ProcessRequest(BaseModel):
    file_id: Optional[str] = None
    chunk_size: Optional[int] = 100
    overlap: Optional[int] = 20
    do_reset: Optional[int] = 0
    deep_processing: Optional[bool] = False
    extract_tables: Optional[bool] = False
    extract_images: Optional[bool] = False
    enable_ocr: Optional[bool] = False
    