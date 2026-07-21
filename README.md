# On-Prem Concurrent LLM

Self-hosted, GPU-accelerated local LLM platform for NationLabs Technical Research & Development — built to serve **NL-Proposal-Builder** and **Niren's AI agents** as shared consumers of one internal API, the same way they'd call any hosted LLM provider.

## Architecture

```
NLABDLAS01 (Dell PowerEdge R750, Windows Server 2019, Hyper-V)
  └── NL-AI-Inference-01 (Ubuntu 22.04 LTS VM, GPU via DDA passthrough)
        └── NVIDIA A30 (24GB VRAM)
        └── Docker + nvidia-container-toolkit
              └── Ollama (shared serving layer, port 11434)
                    ├── qwen3:14b          — primary/everyday
                    ├── deepseek-r1:32b    — heavy reasoning (Qwen distillation)
                    └── gemma3:4b          — fast utility, also runs self-check rails
              └── NeMo Guardrails — AI Guardrail Policy v1.0 (Phase 3, live)
                    ├── guardrails-uat  (port 8001, reasoning trace visible)
                    └── guardrails-prod (port 8000, reasoning trace stripped)
              └── Open WebUI (port 3000, demo UI, routed through guardrails-uat)

Consumers (network clients of the guardrails endpoint, not Ollama directly):
  - NL-Proposal-Builder (src/anthropic.js multi-provider router) — Phase 5, not yet wired, will use guardrails-prod
  - Niren's AI agents — Phase 6, not yet wired, will use guardrails-prod
```

The GPU is bound to exactly one VM via DDA — that's a hard Hyper-V limitation, not a design choice. Sharing happens one layer up: everything that needs the GPU talks to the one serving endpoint over the network, the same way NL-Proposal-Builder already talks to Groq's cloud API today.

## Repo layout

- `infra/01-create-vm.ps1` — Hyper-V VM provisioning + GPU DDA attachment (run on the host)
- `infra/02-setup-gpu-docker.sh` — NVIDIA driver, CUDA, Docker, nvidia-container-toolkit (run inside the VM)
- `serving/docker-compose.yml` — Ollama, guardrails-uat, guardrails-prod, and Open WebUI containers
- `serving/guardrails/` — NeMo Guardrails Dockerfile + `config_uat/` and `config_prod/` (content-safety and prompt-injection rails per AI Guardrail Policy v1.0)
- `RUNBOOK.md` — full operational runbook: build history, gotchas, current status, troubleshooting

## Current status

See `RUNBOOK.md` for the authoritative, up-to-date phase-by-phase status. Phases 1, 2, 3, and 4 complete: VM + GPU passthrough, Ollama serving 3 models, NeMo Guardrails (UAT/Prod split per AI Guardrail Policy v1.0) in front of it, and an Open WebUI demo for Niren routed through the guardrails. Phase 5 (NL-Proposal-Builder integration) and Phase 6 (hand off to Niren's agents) not yet started.

## Access

- VM: `ssh <user>@192.168.71.11` (LAN) or via `10.10.10.3` (internal management network)
- Ollama API: `http://192.168.71.11:11434`
