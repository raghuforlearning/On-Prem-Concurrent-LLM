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

# Phase 3 follow-up (21-Jul-2026): opentelemetry-bootstrap auto-detects the
# instrumentable libraries actually installed (fastapi, requests, logging,
# etc.) and installs the matching instrumentation packages - this is what
# lets `opentelemetry-instrument` (used in CMD below) hook Python's stdlib
# `logging` module without any code changes to nemoguardrails itself.
RUN opentelemetry-bootstrap -a install

EXPOSE 8000

# --config points at a CONFIGS ROOT (a folder of named sub-folders, one per
# config), not a config directly - docker-compose.yml mounts a "default"
# sub-folder in from ./guardrails/config_uat/default or config_prod/default.
# --default-config-id means clients don't need to know/send a config_id -
# every request just falls through to the one config each container serves.
#
# `opentelemetry-instrument` wraps the server process to auto-export Python
# logging output via OTLP - zero-code instrumentation, configured entirely
# via the OTEL_* environment variables set in docker-compose.yml. This is
# Layer 1 of the audit-log pipeline (see RUNBOOK.md) - ships NeMo Guardrails'
# existing operational logs (rail activations, block/allow decisions, LLM
# call info) to Loki. Does not require nemoguardrails' own `tracing:` config
# section - that's for distributed trace spans, which is a separate,
# deliberately out-of-scope capability for now.
# The `--` is required, not stylistic: opentelemetry-instrument dynamically
# registers a --<flag> for every OTEL_* env var (including --config_file and
# --configurator), and its argument parser scans the FULL argv for matches
# before splitting off the wrapped command - without `--`, it tries to match
# nemoguardrails' own "--config" against its own option list and fails with
# "ambiguous option: --config could match --config_file, --configurator".
# Confirmed from opentelemetry-python-contrib's actual auto_instrumentation
# source (parser.parse_args() on full argv, not parse_known_args()).
CMD ["opentelemetry-instrument", "--", "nemoguardrails", "server", "--config", "/config", "--port", "8000", "--default-config-id", "default"]
