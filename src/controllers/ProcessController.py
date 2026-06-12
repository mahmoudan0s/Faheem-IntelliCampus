from .BaseController import BaseController
from .ProjectController import ProjectController
import os
from PIL import Image
import pytesseract
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document
from models.enums.ProcessingEnums import ProcessingEnum
from langchain_text_splitters import RecursiveCharacterTextSplitter
from models import ProcessingEnum

class ProcessController(BaseController):

    def __init__(self, project_id:str):
        super().__init__()

        self.project_id = project_id
        self.project_path = ProjectController().get_project_path(project_id=project_id)
    
    def get_file_extension(self, file_id: str):
        return os.path.splitext(file_id)[-1] # Get the file extension from the file_id
    
    def get_file_loader(self, file_id: str):
        file_extension = self.get_file_extension(file_id=file_id)
        file_path = os.path.join(self.project_path, file_id)

        if not os.path.exists(file_path):
            return None

        if file_extension == ProcessingEnum.TXT.value:
            return TextLoader(file_path, encoding='utf-8')
        elif file_extension == ProcessingEnum.PDF.value:
            return PyMuPDFLoader(file_path)
        elif file_extension in [ProcessingEnum.PNG.value, ProcessingEnum.JPG.value, ProcessingEnum.JPEG.value, ProcessingEnum.BMP.value]:
            return self._ocr_loader(file_path)
        
        return None

        '''#in enum we can define the supported file types and their corresponding loaders, then we can use that enum to get the loader for a given file type. This way we can easily add support for new file types in the future by simply adding them to the enum and implementing their loaders.
        if file_extension in ['.txt']:
            return TextLoader(file_path)
        elif file_extension in ['.pdf']:
            return PyMuPDFLoader(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")'''
        

    def _ocr_loader(self, file_path: str):
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang='ara+eng')
        return [Document(page_content=text, metadata={"source": file_path})]

    def get_file_content(self, file_id: str):
        loader = self.get_file_loader(file_id=file_id)
        if loader is None:
            return None
        return loader.load() if hasattr(loader, 'load') else loader
    
        #it returns '''the content''' of the file as a list of documents,
        # where each document is a dictionary with a "page_content"
        #  key containing the text content of the document.
        #  The specific structure of the returned content may vary
        #  depending on the loader used and the file type being processed.
    def process_file_content(self, file_content:list, file_id:str, chunk_size:int=100, overlap:int=20):
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=len # Use the built-in len function to calculate the length of the text
        )
        file_content_text=[
            rec.page_content
            for rec in file_content
        ]

        file_content_metadata=[
            rec.metadata
            for rec in file_content
        ]
        chunks = text_splitter.create_documents(
            file_content_text,
            metadatas=file_content_metadata
            ) # Create chunks with metadata
        return chunks
