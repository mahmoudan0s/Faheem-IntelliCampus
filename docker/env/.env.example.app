APP_NAME="mini-RAG"
APP_VERSION="0.1"
OPENAI_API_KEY=""
PINECONE_API_KEY=""
PINECONE_ENVIRONMENT=""
FILE_ALLOWED_TYPES=["text/plain","application/pdf","image/png","image/jpeg","image/bmp"]
FILE_MAX_SIZE_MB=10
FILE_DEFAULT_CHUNK_SIZE=512000 # 512KB

#MONGODB_URL="mongodb://admin:admin@localhost:27007"
#MONGODB_DATABASE="mini_rag"

POSTGRES_USERNAME="postgres"
POSTGRES_PASSWORD="postgres_password"
POSTGRES_HOST="pgvector"
POSTGRES_PORT=5432
POSTGRES_MAIN_DATABASE="minirag"

# ========================= LLM Config =========================
GENERATION_BACKEND = "GROQ"
EMBEDDING_BACKEND = "HUGGINGFACE"

OPENAI_API_KEY="" #get your OpenAI API key from https://platform.openai.com/account/api-keys
OPENAI_API_URL=""
COHERE_API_KEY="" #get your Cohere API key from https://dashboard.cohere.com/api-keys
#GROQ_API_KEY=""
GROQ_API_KEY=""

HUGGINGFACE_API_KEY=""
GENERATION_MODEL_ID_LITERAL = ["gpt-4o-mini", "gpt-4o"]
GENERATION_MODEL_ID="llama-3.3-70b-versatile" #GROQ
EMBEDDING_MODEL_ID="sentence-transformers/all-MiniLM-L6-v2" #HUGGINGFACE
EMBEDDING_MODEL_SIZE=384

INPUT_DEFAULT_MAX_CHARACTERS=1024
GENERATION_DEFAULT_MAX_TOKENS=200
GENERATION_DEFAULT_TEMPERATURE=0.1

# ========================= Vector DB Config =========================
VECTOR_DB_BACKEND_LITERAL = ["QDRANT", "PGVECTOR"]
VECTOR_DB_BACKEND="PGVECTOR"
VECTOR_DB_PATH="qdrant_db"
VECTOR_DB_DISTANCE_METHOD="cosine"
VECTOR_DB_PGVEC_INDEX_THRESHOLD = 50
# ========================= Template Configs =========================
PRIMARY_LANG = "en"
DEFAULT_LANG = "en"