from langchain_core.documents import Document


class ChartExtractor:

    CHART_PROMPT = (
        "Analyze the following OCR text extracted from a chart or graph in a document. "
        "This text contains labels, titles, legends, axis values, "
        "and other textual elements from a chart or graph. "
        "If this represents a chart, graph, or plot (such as bar chart, line graph, "
        "pie chart, scatter plot, histogram, etc.), "
        "generate a concise semantic summary of what the chart shows, "
        "including the key trends, data points, and insights. "
        "Focus on describing the data and trends shown, "
        "making it suitable for semantic search retrieval. "
        "If it is NOT a chart or graph, respond with exactly: NOT_A_CHART\n\n"
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
        prompt = self.CHART_PROMPT.format(ocr_text=truncated)

        try:
            response = self.generation_client.generate_text(prompt=prompt)
        except Exception:
            return None

        if not response or "NOT_A_CHART" in response.strip().upper():
            return None

        return Document(
            page_content=response.strip(),
            metadata={
                "source": file_id,
                "page": page_num,
                "chunk_type": "chart",
                "source_file": file_id,
            },
        )
