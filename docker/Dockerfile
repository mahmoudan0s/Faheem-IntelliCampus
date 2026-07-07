FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System dependencies required by:
#  - psycopg2 (libpq-dev, gcc)
#  - pytesseract (tesseract-ocr)
#  - pdfplumber (poppler-utils)
#  - Pillow (libjpeg/zlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
        libjpeg-dev \
        zlib1g-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for better layer caching
COPY src/requirements.txt /app/src/requirements.txt
RUN python -m pip install -r /app/src/requirements.txt

# Copy the rest of the project (volume mount in compose overrides this at runtime)
COPY . /app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]