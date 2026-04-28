from enum import Enum

class ResponseSignal(str, Enum):
    FILE_UPLOAD_SUCCESS = "file_upload_success"
    FILE_UPLOAD_FAILED = "file_upload_failed"
    FILE_TYPE_NOT_ALLOWED = "file_type_not_supported"
    FILE_SIZE_EXCEEDED = "file_size_exceeded"
    
    FILE_VALIDATED_SUCCESS = "file_validated_success"
    FILE_VALIDATION_FAILED = "file_validation_failed"   