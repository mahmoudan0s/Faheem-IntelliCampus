from enum import Enum

class ResponseSignal(str, Enum):
    FILE_UPLOAD_FAILED = "file_upload_failed"
    FILE_TYPE_NOT_ALLOWED = "file_type_not_supported"
    FILE_SIZE_EXCEEDED = "file_size_exceeded"

    FILE_VALIDATED_SUCCESS = "file_validated_success"

    PROCESSING_SUCCESS = "processing_success"
    RAG_ANSWER_ERROR = "rag_answer_error"

    COURSE_UPLOAD_SUCCESS = "course_upload_success"
    COURSE_UPLOAD_ERROR = "course_upload_error"
    COURSE_NOT_FOUND = "course_not_found"
    COURSE_SEARCH_SUCCESS = "course_search_success"
    COURSE_SEARCH_ERROR = "course_search_error"
    COURSE_ANSWER_SUCCESS = "course_answer_success"
    COURSE_ANSWER_ERROR = "course_answer_error"
    PROJECT_COURSE_MISMATCH = "project_course_mismatch"