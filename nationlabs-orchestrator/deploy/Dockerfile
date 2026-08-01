FROM python:3.11-slim

# System deps: tesseract (OCR), poppler (scanned PDF rasterization)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY orchestrator/ ./orchestrator/
COPY scripts/ ./scripts/
COPY data_templates/ ./data_templates/

ENV NL_RUNTIME_ROOT=/opt/nationlabs \
    NL_OLLAMA_URL=http://ollama:11434 \
    PYTHONUNBUFFERED=1

EXPOSE 8100
CMD ["uvicorn", "orchestrator.web.app:app", "--host", "0.0.0.0", "--port", "8100"]
