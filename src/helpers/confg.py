from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    APP_NAME: str
    APP_VERSION: str

    FILE_ALLOWED_TYPES: list[str]
    FILE_MAX_SIZE_MB: int 
    FILE_DEFAULT_CHUNK_SIZE: int
    
    #MONGODB_URL: str
    #MONGODB_DATABASE: str
    POSTGRES_USERNAME: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_MAIN_DATABASE: str


    GENERATION_BACKEND: str
    EMBEDDING_BACKEND: str

    OPENAI_API_KEY: str = None
    OPENAI_API_URL: str = None
    COHERE_API_KEY: str = None
    GROQ_API_KEY: str = None
    HUGGINGFACE_API_KEY: str = None

    Generation_Model_ID_Literal : Optional[List[str]] = None
    GENERATION_MODEL_ID: str = None
    GROQ_MODEL_ID: str = None
    EMBEDDING_MODEL_ID: str = None
    EMBEDDING_MODEL_SIZE: int = None
    INPUT_DEFAULT_MAX_CHARACTERS: int = None
    GENERATION_DEFAULT_MAX_TOKENS: int = None
    GENERATION_DEFAULT_TEMPERATURE: float = None

    VECTOR_DB_BACKEND_LITERAL: Optional[List[str]] = None
    VECTOR_DB_BACKEND : str
    VECTOR_DB_PATH : str
    VECTOR_DB_DISTANCE_METHOD: str = None
    VECTOR_DB_PGVEC_INDEX_THRESHOLD: int = 50

    PRIMARY_LANG: str = "en"
    DEFAULT_LANG: str = "en"

    SQL_SERVER_HOST: str = "localhost"
    SQL_SERVER_PORT: int = 1433
    SQL_SERVER_USERNAME: str = "sa"
    SQL_SERVER_PASSWORD: str = "SA123456"
    SQL_SERVER_DATABASE: str = "IntelliCampusDb"
    SQL_SERVER_DRIVER: str = "ODBC Driver 18 for SQL Server"

    model_config = SettingsConfigDict(env_file=".env")

def get_settings():
    return Settings()