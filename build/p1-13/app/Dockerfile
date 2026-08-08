FROM python:3.12-slim

# System packages for file intake (install during internet window; image is
# then self-contained for air-gap): tesseract = OCR, poppler = PDF rasterize
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr poppler-utils && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
