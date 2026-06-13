from .BaseController import BaseController
from .ProjectController import ProjectController
import os
from stores.document_processing import DocumentProcessor

class ProcessController(BaseController):

    def __init__(self, project_id:str, generation_client=None):
        super().__init__()

        self.project_id = project_id
        self.project_path = ProjectController().get_project_path(project_id=project_id)
        self.generation_client = generation_client

    def get_file_extension(self, file_id: str):
        return os.path.splitext(file_id)[-1]

    def get_file_path(self, file_id: str):
        return os.path.join(self.project_path, file_id)

    def process_file(self, file_id: str, chunk_size: int = 100, overlap: int = 20):
        file_path = self.get_file_path(file_id=file_id)
        if not os.path.exists(file_path):
            return None

        processor = DocumentProcessor(
            chunk_size=chunk_size,
            overlap=overlap,
            generation_client=self.generation_client,
        )

        return processor.process(file_path=file_path, file_id=file_id)
