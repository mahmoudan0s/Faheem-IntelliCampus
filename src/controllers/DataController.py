import os
import re
from .BaseController import BaseController  
from .ProjectController import ProjectController
from fastapi import UploadFile
from models import ResponseSignal

class DataController(BaseController):

    def __init__(self):
        super().__init__()
        self.size_scale= 1024 * 1024  # Convert bytes to MB

    def validate_uploaded_file(self, file: UploadFile):

        if file.content_type not in self.app_settings.FILE_ALLOWED_TYPES:
            return False, ResponseSignal.FILE_TYPE_NOT_ALLOWED.value

        file_size = file.size
        if file_size is None:
            content_length = file.headers.get("content-length")
            file_size = int(content_length) if content_length else None

        if file_size is None or file_size > self.app_settings.FILE_MAX_SIZE_MB * self.size_scale:
            return False, ResponseSignal.FILE_SIZE_EXCEEDED.value

        return True, ResponseSignal.FILE_VALIDATED_SUCCESS.value
    
    def generate_unique_filepath(self, original_filename: str, project_id: str):
        random_key = self.generate_random_string()
        project_path= ProjectController().get_project_path(project_id=project_id)
        
        cleaned_filename = self.get_clean_filename(original_filename = original_filename)

        new_file_path = os.path.join(
            project_path,random_key + "_" + cleaned_filename
        )
        while os.path.exists(new_file_path):
            random_key = self.generate_random_string()
            new_file_path = os.path.join( 
                project_path,random_key + "_" + cleaned_filename
            )
        return new_file_path, random_key + "_" + cleaned_filename
    
    def get_clean_filename(self, original_filename: str):
        # Remove any characters that are not alphanumeric, underscores, or dots
        cleaned_filename = re.sub(r'[^a-zA-Z0-9_.]','', original_filename.strip())
        cleaned_filename = cleaned_filename.replace(" ", "_")  # Replace spaces with underscores
        return cleaned_filename 