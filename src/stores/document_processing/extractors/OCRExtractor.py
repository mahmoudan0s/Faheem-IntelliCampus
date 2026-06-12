import os
import io
import fitz
from PIL import Image
import pytesseract
from langchain_core.documents import Document


class OCRExtractor:

    def __init__(self, ocr_lang: str = "ara+eng"):
        self.ocr_lang = ocr_lang

    def extract_image(self, file_path: str) -> str:
        img = Image.open(file_path)
        return pytesseract.image_to_string(img, lang=self.ocr_lang)

    def extract_image_bytes(self, img_bytes: bytes) -> str:
        img = Image.open(io.BytesIO(img_bytes))
        return pytesseract.image_to_string(img, lang=self.ocr_lang)

    def extract_pdf(self, file_path: str, file_id: str) -> list:
        chunks = []
        doc = fitz.open(file_path)

        for page_num in range(len(doc)):
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

        doc.close()
        return chunks
