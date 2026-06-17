from langchain_core.documents import Document


class VisualExtractor:

    PROMPT = (
        "Analyze the following OCR text extracted from an image in a document. "
        "Determine what type of visual element it represents:\n"
        "- If it is a diagram (UML, ERD, flowchart, architecture, class, sequence, "
        "entity-relationship, or any structural/behavioral diagram), "
        "convert it into a structured semantic description focusing on "
        "entities, relationships, and flows.\n"
        "- If it is a chart or graph (bar chart, line graph, pie chart, "
        "scatter plot, histogram, etc.), generate a concise summary of "
        "what the chart shows, including key trends, data points, and insights.\n"
        "- If it is neither, respond with exactly: NOT_A_VISUAL\n\n"
        "OCR text:\n{ocr_text}"
    )

    MAX_INPUT_CHARS = 1000
    MIN_IMG_SIZE = 10000

    def __init__(self, generation_client=None):
        self.generation_client = generation_client

    def process_image_text(
        self, ocr_text: str, file_id: str, page_num: int = None, chunk_type: str = None
    ):
        if not self.generation_client or not ocr_text or not ocr_text.strip():
            return None

        if chunk_type:
            return Document(
                page_content=ocr_text.strip(),
                metadata={
                    "source": file_id,
                    "page": page_num,
                    "chunk_type": "image_text",
                    "source_file": file_id,
                },
            )

        truncated = ocr_text.strip()[:self.MAX_INPUT_CHARS]
        prompt = self.PROMPT.format(ocr_text=truncated)

        try:
            response = self.generation_client.generate_text(prompt=prompt)
        except Exception:
            return None

        if not response or "NOT_A_VISUAL" in response.strip().upper():
            return None

        visual_type = "diagram" if "diagram" in response.lower() else "chart"

        return Document(
            page_content=response.strip(),
            metadata={
                "source": file_id,
                "page": page_num,
                "chunk_type": visual_type,
                "source_file": file_id,
            },
        )
