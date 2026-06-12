from langchain_core.documents import Document


class DiagramExtractor:

    DIAGRAM_PROMPT = (
        "Analyze the following OCR text extracted from an image in a document. "
        "If this represents a UML diagram, ERD, entity-relationship diagram, "
        "flowchart, architecture diagram, class diagram, sequence diagram, "
        "or any other type of structural/behavioral diagram, "
        "convert it into a structured semantic description "
        "suitable for semantic search retrieval. "
        "Focus on the entities, relationships, and flows described. "
        "If it is NOT a diagram, respond with exactly: NOT_A_DIAGRAM\n\n"
        "OCR text:\n{ocr_text}"
    )

    MAX_INPUT_CHARS = 1000

    def __init__(self, generation_client=None):
        self.generation_client = generation_client

    def process_image_text(
        self, ocr_text: str, file_id: str, page_num: int = None
    ):
        if not self.generation_client or not ocr_text or not ocr_text.strip():
            return None

        truncated = ocr_text.strip()[:self.MAX_INPUT_CHARS]
        prompt = self.DIAGRAM_PROMPT.format(ocr_text=truncated)

        try:
            response = self.generation_client.generate_text(prompt=prompt)
        except Exception:
            return None

        if not response or "NOT_A_DIAGRAM" in response.strip().upper():
            return None

        return Document(
            page_content=response.strip(),
            metadata={
                "source": file_id,
                "page": page_num,
                "chunk_type": "diagram",
                "source_file": file_id,
            },
        )
