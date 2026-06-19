import os
import fitz
import logging
from typing import List
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document

CHUNK_SIZE = 700
CHUNK_OVERLAP = 100


class TextExtractor:

    def __init__(self, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.logger = logging.getLogger(__name__)

    def _chunk_text(self, text: str, metadata: dict) -> List[Document]:
        chunks = []
        start = 0
        text_len = len(text)
        chunk_idx = 0
        step = self.chunk_size - self.overlap
        if step < 1:
            step = 1

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append(Document(
                    page_content=chunk_text,
                    metadata={**metadata, "chunk_index": chunk_idx}
                ))
                chunk_idx += 1
            start += step

        return chunks

    def _chunk_sentences(self, docs: List[Document]) -> List[Document]:
        if not docs:
            return []
        chunks = []
        for doc in docs:
            text = doc.page_content
            if text:
                chunks.extend(self._chunk_text(text, doc.metadata))
        return chunks

    def extract_txt(self, file_path: str, file_id: str) -> list:
        loader = TextLoader(file_path, encoding="utf-8")
        raw_docs = loader.load()

        for doc in raw_docs:
            doc.metadata.update({
                "source": file_path,
                "source_file": file_id,
                "chunk_type": "text",
            })

        return self._chunk_sentences(raw_docs)

    def extract_pdf(self, file_path: str, file_id: str) -> list:
        docs = []
        try:
            self.logger.info(f"Opening PDF: {file_path}")
            doc = fitz.open(file_path)
            self.logger.info(f"PDF opened, pages: {len(doc)}")
        except Exception as e:
            self.logger.warning(f"Could not open PDF for text extraction: {e}")
            return []

        for page_num in range(min(len(doc), 200)):
            page = doc[page_num]
            try:
                text = page.get_text().strip()
            except Exception:
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

            if (page_num + 1) % 20 == 0:
                self.logger.info(f"Extracted {page_num + 1}/{len(doc)} pages")

        doc.close()
        self.logger.info(f"PDF extraction done, {len(docs)} pages with text")
        result = self._chunk_sentences(docs)
        self.logger.info(f"Chunking done, {len(result)} chunks")
        return result
