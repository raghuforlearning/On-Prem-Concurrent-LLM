# On-Prem Concurrent LLM

Self-hosted, GPU-accelerated local LLM platform for NationLabs Technical Research & Development — built to serve **NL-Proposal-Builder** and **Niren's AI agents** as shared consumers of one internal API, the same way they'd call any hosted LLM provider.

## Architecture

```
NLABDLAS01 (Dell PowerEdge R750, Windows Server 2019, Hyper-V)
  └── NL-AI-Inference-01 (Ubuntu 22.04 LTS VM, GPU via DDA passthrough)
        └── NVIDIA A30 (24GB VRAM)
        └── Docker + nvidia-container-toolkit
              └── Ollama (serving layer, port 11434)
                    ├── qwen3:14b          — primary/everyday
                    ├── deepseek-r1:32b    — heavy reasoning (Qwen distillation)
                    └── gemma3:4b          — fast utility
              └── NeMo Guardrails (planned — policy layer in front of Ollama)
              └── Open WebUI (planned — staff chat interface)

Consumers (network clients of the Ollama/guardrails endpoint):
  - NL-Proposal-Builder (src/anthropic.js multi-provider router)
  - Niren's AI agents
```

The GPU is bound to exactly one VM via DDA — that's a hard Hyper-V limitation, not a design choice. Sharing happens one layer up: everything that needs the GPU talks to the one serving endpoint over the network, the same way NL-Proposal-Builder already talks to Groq's cloud API today.

## Repo layout

- `infra/01-create-vm.ps1` — Hyper-V VM provisioning + GPU DDA attachment (run on the host)
- `infra/02-setup-gpu-docker.sh` — NVIDIA driver, CUDA, Docker, nvidia-container-toolkit (run inside the VM)
- `serving/docker-compose.yml` — Ollama serving container
- `RUNBOOK.md` — full operational runbook: build history, gotchas, current status, troubleshooting

## Current status

See `RUNBOOK.md` for the authoritative, up-to-date phase-by-phase status. As of the initial commit: Phases 1 and 2 complete (VM + GPU passthrough working, Ollama deployed with 3 models pulled and benchmarked). Phase 3 (guardrails) in progress.

## Access

- VM: `ssh <user>@192.168.71.11` (LAN) or via `10.10.10.3` (internal management network)
- Ollama API: `http://192.168.71.11:11434`
