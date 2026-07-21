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

# --config points at a CONFIGS ROOT (a folder of named sub-folders, one per
# config), not a config directly - docker-compose.yml mounts a "default"
# sub-folder in from ./guardrails/config_uat/default or config_prod/default.
# --default-config-id means clients don't need to know/send a config_id -
# every request just falls through to the one config each container serves.
CMD ["nemoguardrails", "server", "--config", "/config", "--port", "8000", "--default-config-id", "default"]
