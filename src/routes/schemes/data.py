from pydantic import BaseModel
from typing import Optional

class ProcessRequest(BaseModel):
    file_id: str = None
    chunk_size: Optional[int] = 100 # Default chunk size of 100 tokens
    overlap: Optional[int] = 20 # Default overlap of 20 tokens
    do_reset: Optional[int] = 0 # Default is not to reset the processed data, set to 1 to reset and reprocess the data
    