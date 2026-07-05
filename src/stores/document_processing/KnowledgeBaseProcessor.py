import os
import logging
import fitz
from langchain_core.documents import Document
from .extractors import TextExtractor, OCRExtractor, TableExtractor, VisualExtractor
from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)

TEXT_EXTRACTION_THRESHOLD = 200


class KnowledgeBaseProcessor:

    def __init__(self, embedding_client=None, vectordb_client=None, generation_client=None):
        self.embedding_client = embedding_client
        self.vectordb_client = vectordb_client
        self.generation_client = generation_client

    def _get_chunks_from_pdf(self, file_path: str, file_id: str,
                              chunk_size: int, overlap: int,
                              deep_processing: bool,
                              extract_tables: bool,
                              extract_images: bool,
                              enable_ocr: bool) -> list:
        text_extractor = TextExtractor(chunk_size=chunk_size, overlap=overlap)
        chunks = text_extractor.extract_pdf(file_path, file_id)
        total_text_len = sum(len(c.page_content) for c in chunks)

        if total_text_len > TEXT_EXTRACTION_THRESHOLD:
            if extract_tables:
                table_extractor = TableExtractor()
                try:
                    table_chunks = table_extractor.extract(file_path, file_id)
                    chunks.extend(table_chunks)
                except Exception as e:
                    logger.warning(f"Table extraction failed: {e}")

            if extract_images:
                from PIL import Image
                import io
                visual_extractor = VisualExtractor(
                    generation_client=self.generation_client
                )
                ocr_extractor = OCRExtractor()
                try:
                    doc = fitz.open(file_path)
                    for page_num, page in enumerate(doc):
                        image_list = page.get_images(full=True)
                        for img_info in image_list:
                            xref = img_info[0]
                            try:
                                base_image = doc.extract_image(xref)
                                img_bytes = base_image["image"]
                                img = Image.open(io.BytesIO(img_bytes))
                                if img.width * img.height < 10000:
                                    continue
                            except Exception:
                                continue
                            ocr_text = ocr_extractor.extract_image_bytes(img_bytes)
                            if not ocr_text or not ocr_text.strip():
                                continue
                            visual_chunk = visual_extractor.process_image_text(
                                ocr_text, file_id, page_num=page_num + 1
                            )
                            if visual_chunk:
                                chunks.append(visual_chunk)
                    doc.close()
                except Exception as e:
                    logger.warning(f"Image extraction failed: {e}")

        elif enable_ocr:
            ocr_extractor = OCRExtractor()
            try:
                ocr_chunks = ocr_extractor.extract_pdf(file_path, file_id)
                if ocr_chunks:
                    chunks = ocr_chunks
            except Exception as e:
                logger.warning(f"OCR extraction failed: {e}")

        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_order"] = i

        return chunks

    def _get_chunks_from_image(self, file_path: str, file_id: str,
                                enable_ocr: bool) -> list:
        if not enable_ocr:
            return []

        ocr_extractor = OCRExtractor()
        try:
            ocr_text = ocr_extractor.extract_image(file_path)
        except Exception as e:
            logger.warning(f"OCR failed on image: {e}")
            return []

        if not ocr_text or not ocr_text.strip():
            return []

        if self.generation_client:
            visual_extractor = VisualExtractor(
                generation_client=self.generation_client
            )
            visual_chunk = visual_extractor.process_image_text(
                ocr_text, file_id, page_num=1
            )
            if visual_chunk:
                return [visual_chunk]

        return [
            Document(
                page_content=ocr_text.strip(),
                metadata={
                    "source": file_id,
                    "page": 1,
                    "chunk_type": "text",
                    "source_file": file_id,
                },
            )
        ]

    def _get_chunks_from_txt(self, file_path: str, file_id: str,
                              chunk_size: int, overlap: int) -> list:
        text_extractor = TextExtractor(chunk_size=chunk_size, overlap=overlap)
        return text_extractor.extract_txt(file_path, file_id)

    def get_chunks(self, file_path: str, file_id: str,
                   chunk_size: int = 700, overlap: int = 100,
                   deep_processing: bool = False,
                   extract_tables: bool = False,
                   extract_images: bool = False,
                   enable_ocr: bool = False) -> list:
        ext = os.path.splitext(file_id)[-1].lower()

        if ext == ".txt":
            return self._get_chunks_from_txt(file_path, file_id, chunk_size, overlap)

        elif ext == ".pdf":
            return self._get_chunks_from_pdf(
                file_path, file_id, chunk_size, overlap,
                deep_processing, extract_tables, extract_images, enable_ocr,
            )

        elif ext in (".png", ".jpg", ".jpeg", ".bmp"):
            return self._get_chunks_from_image(file_path, file_id, enable_ocr)

        return []

    def embed_chunks(self, chunks: list) -> list:
        if not self.embedding_client or not chunks:
            return []
        texts = [c.page_content for c in chunks]
        return self.embedding_client.embed_text(
            text=texts,
            document_type=DocumentTypeEnum.DOCUMENT.value,
        )

    async def create_vector_collection(self, collection_name: str,
                                        embedding_size: int,
                                        do_reset: bool = False):
        if not self.vectordb_client:
            return
        await self.vectordb_client.create_collection(
            collection_name=collection_name,
            embedding_size=embedding_size,
            do_reset=do_reset,
        )

    async def store_vectors(self, collection_name: str,
                             texts: list, vectors: list,
                             metadata: list = None,
                             record_ids: list = None):
        if not self.vectordb_client:
            return
        if record_ids is None:
            record_ids = [None] * len(texts)
        await self.vectordb_client.insert_many(
            collection_name=collection_name,
            texts=texts,
            vectors=vectors,
            metadata=metadata,
            record_ids=record_ids,
        )
