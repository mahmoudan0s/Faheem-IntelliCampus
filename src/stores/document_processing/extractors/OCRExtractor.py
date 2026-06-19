import os
import io
import logging
import fitz
from PIL import Image
import pytesseract
from langchain_core.documents import Document


class OCRExtractor:

    def __init__(self, ocr_lang: str = "ara+eng"):
        self.ocr_lang = ocr_lang
        self.logger = logging.getLogger(__name__)

    def extract_image(self, file_path: str) -> str:
        try:
            img = Image.open(file_path)
            return pytesseract.image_to_string(img, lang=self.ocr_lang)
        except Exception as e:
            self.logger.warning(f"OCR failed on image {file_path}: {e}")
            return ""

    def extract_image_bytes(self, img_bytes: bytes) -> str:
        try:
            img = Image.open(io.BytesIO(img_bytes))
            return pytesseract.image_to_string(img, lang=self.ocr_lang)
        except Exception as e:
            self.logger.warning(f"OCR failed on image bytes: {e}")
            return ""

    def extract_pdf(self, file_path: str, file_id: str) -> list:
        chunks = []
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            self.logger.warning(f"Could not open PDF for OCR: {e}")
            return []

        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = pytesseract.image_to_string(img, lang=self.ocr_lang)
                if text.strip():
                    chunks.append(
                        Document(
                            page_content=text.strip(),
                            metadata={
                                "source": file_path,
                                "page": page_num + 1,
                                "chunk_type": "text",
                                "source_file": file_id,
                            },
                        )
                    )
            except Exception as e:
                self.logger.warning(
                    f"OCR failed on page {page_num + 1} of {file_id}: {e}"
                )
                continue

        doc.close()
        return chunks
