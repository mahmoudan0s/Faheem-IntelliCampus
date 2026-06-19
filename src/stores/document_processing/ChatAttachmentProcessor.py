import os
import logging
import fitz
import numpy as np
from langchain_core.documents import Document
from .extractors import TextExtractor, OCRExtractor
from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)

MAX_DIRECT_TOKENS = 2048
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
RETRIEVAL_LIMIT = 5


class ChatAttachmentProcessor:

    def __init__(self, embedding_client=None, generation_client=None):
        self.embedding_client = embedding_client
        self.generation_client = generation_client
        self.text_extractor = TextExtractor(
            chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP
        )
        self.ocr_extractor = OCRExtractor()

    def _cosine_similarity(self, a: list, b: list) -> float:
        a = np.array(a, dtype=np.float32)
        b = np.array(b, dtype=np.float32)
        if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
            return 0.0
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    def _extract_pdf_text(self, file_path: str) -> str:
        text = ""
        try:
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            doc.close()
        except Exception as e:
            logger.warning(f"Failed to extract PDF text: {e}")
        return text.strip()

    def _estimate_tokens(self, text: str) -> int:
        return len(text.split())

    def _retrieve_relevant_context(self, text: str, query: str) -> str:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) == 0:
            paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if len(paragraphs) == 0:
            return text[:3000]

        docs = [
            Document(page_content=p, metadata={"idx": i})
            for i, p in enumerate(paragraphs)
        ]

        if not docs or not self.embedding_client:
            return text[:3000]

        embedded_chunks = self.embedding_client.embed_text(
            text=[d.page_content for d in docs],
            document_type=DocumentTypeEnum.DOCUMENT.value,
        )

        query_vector = self.embedding_client.embed_text(
            text=[query],
            document_type=DocumentTypeEnum.QUERY.value,
        )

        if not embedded_chunks or not query_vector:
            return text[:3000]

        query_vec = query_vector[0] if query_vector else None
        if not query_vec:
            return text[:3000]

        scored = []
        for i, doc in enumerate(docs):
            if i < len(embedded_chunks) and embedded_chunks[i]:
                score = self._cosine_similarity(query_vec, embedded_chunks[i])
                scored.append((score, doc.page_content))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored[:RETRIEVAL_LIMIT]
        context = "\n".join([chunk for _, chunk in top_chunks])
        return context

    def process_image(self, file_path: str) -> str:
        try:
            ocr_text = self.ocr_extractor.extract_image(file_path)
            return ocr_text.strip() if ocr_text else ""
        except Exception as e:
            logger.warning(f"OCR failed on image: {e}")
            return ""

    def process_pdf(self, file_path: str, query: str = "") -> str:
        raw_text = self._extract_pdf_text(file_path)
        if not raw_text:
            try:
                chunks = self.ocr_extractor.extract_pdf(file_path, "")
                raw_text = "\n".join(c.page_content for c in chunks)
            except Exception as e:
                logger.warning(f"OCR fallback failed: {e}")
                return ""

        token_count = self._estimate_tokens(raw_text)

        if token_count <= MAX_DIRECT_TOKENS:
            return raw_text

        if query and self.embedding_client:
            return self._retrieve_relevant_context(raw_text, query)

        return raw_text[:3000]

    def process_txt(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"Failed to read txt file: {e}")
            return ""

    def process_attachment(self, file_path: str, file_id: str,
                           query: str = "") -> str:
        ext = os.path.splitext(file_id)[-1].lower()

        if ext in (".png", ".jpg", ".jpeg", ".bmp"):
            return self.process_image(file_path)

        elif ext == ".pdf":
            return self.process_pdf(file_path, query=query)

        elif ext == ".txt":
            return self.process_txt(file_path)

        return ""

    def generate_answer(self, extracted_content: str, user_message: str) -> str:
        if not self.generation_client or not extracted_content:
            return ""

        system_prompt = (
            "You are a helpful teaching assistant. "
            "Use the following document content to answer the student's question. "
            "If the document content does not contain enough information, "
            "say so and provide your best guidance based on general knowledge.\n\n"
            f"Document Content:\n{extracted_content}"
        )

        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        answer = self.generation_client.generate_text(
            prompt=user_message,
            chat_history=chat_history,
        )
        return answer
