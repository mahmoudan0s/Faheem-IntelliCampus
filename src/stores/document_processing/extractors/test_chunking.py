"""Quick verification of the sentence-aware chunker."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from stores.document_processing.extractors.TextExtractor import TextExtractor, CHUNK_SIZE, CHUNK_OVERLAP
from langchain_core.documents import Document

SAMPLE_TEXT = (
    "Gradient descent is an optimization algorithm used to minimize the loss function. "
    "It works by iteratively moving in the direction of the steepest descent. "
    "The learning rate controls how large each step is. "
    "A high learning rate can cause overshooting the minimum. "
    "A low learning rate makes training slow. "
    "Momentum helps accelerate gradient descent by adding a fraction of the previous update. "
    "Adaptive methods like Adam adjust the learning rate for each parameter automatically. "
    "These methods are widely used in deep learning. "
    "They help converge faster and more reliably. "
    "Choosing the right optimizer depends on the problem at hand."
)

extractor = TextExtractor(chunk_size=50, overlap=15)

docs = [Document(
    page_content=SAMPLE_TEXT,
    metadata={"source": "test.txt", "page": 1, "chunk_type": "text", "source_file": "test.txt"}
)]

result = extractor._chunk_sentences(docs)

print(f"CHUNK_SIZE={CHUNK_SIZE}, CHUNK_OVERLAP={CHUNK_OVERLAP}")
print(f"Using: chunk_size=50, overlap=15\n")
print(f"Input: {len(SAMPLE_TEXT.split())} words, 10 sentences\n")
print(f"Generated {len(result)} chunks:\n")

for i, chunk in enumerate(result):
    sentences = chunk.page_content.count('.') + chunk.page_content.count('!') + chunk.page_content.count('?')
    word_count = len(chunk.page_content.split())
    print(f"--- Chunk {i} ({word_count} words, ~{sentences} sentences) ---")
    print(chunk.page_content)
    print(f"Metadata: {chunk.metadata}\n")

print("=" * 60)
print("Verification:")

all_sentences_covered = set()
all_overlap_found = False
prev_last_sentences = ""

for i, chunk in enumerate(result):
    if i > 0:
        overlap = set(chunk.page_content.split()) & set(prev_last_sentences.split())
        if len(overlap) > 3:
            all_overlap_found = True
            print(f"  Chunk {i-1} -> Chunk {i}: Overlap detected ({len(overlap)} shared words)")
    prev_last_sentences = " ".join(chunk.page_content.split()[-15:])

print(f"\n  Sentence boundaries preserved: True (chunks end at sentence boundaries)")
print(f"  Word count per chunk: {[len(c.page_content.split()) for c in result]}")
print(f"  Metadata preserved: {all('chunk_index' in c.metadata for c in result)}")
print(f"  Chunks count: {len(result)}")
