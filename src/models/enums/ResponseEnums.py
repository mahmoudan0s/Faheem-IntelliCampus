from enum import Enum

class ResponseSignal(str, Enum):
    FILE_UPLOAD_SUCCESS = "file_upload_success"
    FILE_UPLOAD_FAILED = "file_upload_failed"
    FILE_TYPE_NOT_ALLOWED = "file_type_not_supported"
    FILE_SIZE_EXCEEDED = "file_size_exceeded"
    
    FILE_VALIDATED_SUCCESS = "file_validated_success"
    FILE_VALIDATION_FAILED = "file_validation_failed"   

    PROCESSING_SUCCESS = "processing_success"
    PROCESSING_FAILED = "processing_failed"
    NO_FILES_ERROR = "no_found_files"
    FILE_ID_ERROR = "no file found with the provided file_id"
    PROJECT_NOT_FOUND_ERROR = "project_not_found"
    INSERT_INTO_VECTORDB_SUCCESS = "insert_into_vectordb_success"
    INSERT_INTO_VECTORDB_ERROR = "insert_into_vectordb_error"
    VECTORDB_COLLECTION_RETRIEVED = "vector_collection_retrieved"
    VECTORDB_SEARCH_SUCCESS = "vector_db_search_success"
    VECTORDB_SEARCH_ERROR = "vector_db_search_error"
    RAG_ANSWER_SUCCESS = "rag_answer_success"
    RAG_ANSWER_ERROR = "rag_answer_error"

    CHAT_ATTACHMENT_SUCCESS = "chat_attachment_success"
    CHAT_ATTACHMENT_ERROR = "chat_attachment_error"
    CHAT_ATTACHMENT_EXTRACTED = "chat_attachment_extracted"

    COURSE_UPLOAD_SUCCESS = "course_upload_success"
    COURSE_UPLOAD_ERROR = "course_upload_error"
    COURSE_NOT_FOUND = "course_not_found"
    COURSE_SEARCH_SUCCESS = "course_search_success"
    COURSE_SEARCH_ERROR = "course_search_error"
    COURSE_ANSWER_SUCCESS = "course_answer_success"
    COURSE_ANSWER_ERROR = "course_answer_error"
    PROJECT_COURSE_MISMATCH = "project_course_mismatch"