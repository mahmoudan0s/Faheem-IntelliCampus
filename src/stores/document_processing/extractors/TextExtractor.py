import os
import fitz
import logging
from langchain_community.document_loaders import TextLoader
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
        self.logger = logging.getLogger(__name__)

    def extract_txt(self, file_path: str, file_id: str) -> list:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()

        for doc in docs:
            doc.metadata["source_file"] = file_id
            doc.metadata["chunk_type"] = "text"

        return self.text_splitter.split_documents(docs)

    def extract_pdf(self, file_path: str, file_id: str) -> list:
        docs = []
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            self.logger.warning(f"Could not open PDF for text extraction: {e}")
            return []

        for page_num in range(len(doc)):
            page = doc[page_num]
            try:
                text = page.get_text().strip()
            except Exception:
                self.logger.warning(f"Failed to extract text on page {page_num + 1}, rendering as image")
                try:
                    pix = page.get_pixmap(dpi=200)
                    img = __import__("PIL", fromlist=["Image"]).Image.frombytes(
                        "RGB", [pix.width, pix.height], pix.samples
                    )
                    import pytesseract
                    text = pytesseract.image_to_string(img).strip()
                except Exception as ocr_e:
                    self.logger.warning(f"OCR fallback also failed on page {page_num + 1}: {ocr_e}")
                    text = ""

            if text:
                docs.append(Document(
                    page_content=text,
                    metadata={
                        "source": file_path,
                        "page": page_num + 1,
                        "chunk_type": "text",
                        "source_file": file_id,
                    },
                ))

        doc.close()
        return self.text_splitter.split_documents(docs)
