import os
import pdfplumber
from tabulate import tabulate
from langchain_core.documents import Document


class TableExtractor:

    def extract(self, file_path: str, file_id: str) -> list:
        chunks = []

        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    for table_index, table in enumerate(tables):
                        if not table or len(table) < 2:
                            continue

                        headers = table[0]
                        rows = table[1:]
                        cleaned_headers = [
                            h.strip() if h else "" for h in headers
                        ]
                        cleaned_rows = []
                        for row in rows:
                            cleaned_rows.append(
                                [cell.strip() if cell else "" for cell in row]
                            )

                        markdown_table = tabulate(
                            cleaned_rows,
                            headers=cleaned_headers,
                            tablefmt="github",
                        )

                        chunks.append(
                            Document(
                                page_content=markdown_table,
                                metadata={
                                    "source": file_path,
                                    "page": page_num + 1,
                                    "chunk_type": "table",
                                    "source_file": file_id,
                                    "table_index": table_index,
                                },
                            )
                        )
        except Exception:
            pass

        return chunks
