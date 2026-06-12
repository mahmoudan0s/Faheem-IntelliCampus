import os
import fitz
from langchain_core.documents import Document
from .extractors import TextExtractor, OCRExtractor, TableExtractor, DiagramExtractor, ChartExtractor


class DocumentProcessor:

    def __init__(self, chunk_size: int = 100, overlap: int = 20, generation_client=None):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.generation_client = generation_client

        self.text_extractor = TextExtractor(chunk_size, overlap)
        self.ocr_extractor = OCRExtractor()
        self.table_extractor = TableExtractor()
        self.diagram_extractor = DiagramExtractor(generation_client)
        self.chart_extractor = ChartExtractor(generation_client)

    def process(self, file_path: str, file_id: str) -> list:
        ext = os.path.splitext(file_id)[-1].lower()

        if ext == ".txt":
            return self.text_extractor.extract_txt(file_path, file_id)

        elif ext == ".pdf":
            return self._process_pdf(file_path, file_id)

        elif ext in (".png", ".jpg", ".jpeg", ".bmp"):
            return self._process_image(file_path, file_id)

        return []

    def _process_pdf(self, file_path: str, file_id: str) -> list:
        has_selectable_text = self._pdf_has_selectable_text(file_path)

        if has_selectable_text:
            chunks = []

            text_chunks = self.text_extractor.extract_pdf(file_path, file_id)
            chunks.extend(text_chunks)

            table_chunks = self.table_extractor.extract(file_path, file_id)
            chunks.extend(table_chunks)

            img_chunks = self._process_pdf_images(file_path, file_id)
            chunks.extend(img_chunks)

            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk_order"] = i

            return chunks

        else:
            return self.ocr_extractor.extract_pdf(file_path, file_id)

    def _process_image(self, file_path: str, file_id: str) -> list:
        ocr_text = self.ocr_extractor.extract_image(file_path)
        if not ocr_text or not ocr_text.strip():
            return []

        diagram_chunk = self.diagram_extractor.process_image_text(
            ocr_text, file_id, page_num=1
        )
        if diagram_chunk:
            return [diagram_chunk]

        chart_chunk = self.chart_extractor.process_image_text(
            ocr_text, file_id, page_num=1
        )
        if chart_chunk:
            return [chart_chunk]

        return [
            Document(
                page_content=ocr_text,
                metadata={
                    "source": file_id,
                    "page": 1,
                    "chunk_type": "text",
                    "source_file": file_id,
                },
            )
        ]

    def _pdf_has_selectable_text(self, file_path: str) -> bool:
        try:
            doc = fitz.open(file_path)
            total_text = 0
            for page in doc:
                text = page.get_text().strip()
                total_text += len(text)
                if total_text > 100:
                    doc.close()
                    return True
            doc.close()
            return total_text > 50
        except Exception:
            return False

    def _process_pdf_images(self, file_path: str, file_id: str) -> list:
        from PIL import Image
        import io

        chunks = []
        doc = fitz.open(file_path)

        for page_num, page in enumerate(doc):
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                img_bytes = base_image["image"]

                ocr_text = self.ocr_extractor.extract_image_bytes(img_bytes)
                if not ocr_text or not ocr_text.strip():
                    continue

                diagram_chunk = self.diagram_extractor.process_image_text(
                    ocr_text, file_id, page_num=page_num + 1
                )
                if diagram_chunk:
                    chunks.append(diagram_chunk)
                    continue

                chart_chunk = self.chart_extractor.process_image_text(
                    ocr_text, file_id, page_num=page_num + 1
                )
                if chart_chunk:
                    chunks.append(chart_chunk)

        doc.close()
        return chunks
