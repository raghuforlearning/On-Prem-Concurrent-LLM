FROM python:3.12-slim

WORKDIR /srv/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# default = API; worker overrides via compose command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
