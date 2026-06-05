from enum import Enum
class DataBaseEnum(Enum):
    COLLECTION_PROJECT_NAME = "projects"
    COLLECTION_CHUNKS_NAME = "chunks"#plural of chunk, to store the data chunks extracted from the files, along with their metadata and embeddings.
    COLLECTION_ASSET_NAME = "assets"