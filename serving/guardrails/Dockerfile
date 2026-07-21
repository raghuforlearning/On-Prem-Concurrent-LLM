# On-Prem Concurrent LLM - NeMo Guardrails server
#
# Same image is used for both the UAT and Prod guardrails containers - only the
# mounted /config directory differs (see docker-compose.yml). Config is mounted
# read-only at runtime, not baked into the image, so policy changes (v1.1, v1.2...)
# don't require a rebuild - just a container restart.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

# --config is set to /config, which docker-compose.yml mounts from
# ./guardrails/config_uat or ./guardrails/config_prod depending on the service.
CMD ["nemoguardrails", "server", "--config", "/config", "--port", "8000"]
