import os
from langchain_community.document_loaders import TextLoader, PyMuPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


class TextExtractor:

    def __init__(self, chunk_size: int = 100, overlap: int = 20):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=len,
        )

    def extract_txt(self, file_path: str, file_id: str) -> list:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()

        for doc in docs:
            doc.metadata["source_file"] = file_id
            doc.metadata["chunk_type"] = "text"

        return self.text_splitter.split_documents(docs)

    def extract_pdf(self, file_path: str, file_id: str) -> list:
        loader = PyMuPDFLoader(file_path)
        docs = loader.load()

        for doc in docs:
            doc.metadata["source_file"] = file_id
            doc.metadata["chunk_type"] = "text"
            if "page" not in doc.metadata:
                doc.metadata["page"] = doc.metadata.get("page", 1)

        return self.text_splitter.split_documents(docs)
