# Runbook — On-Prem Concurrent LLM

Last updated: 19 Jul 2026

## 1. Purpose and background

NationLabs needed a local, GPU-accelerated LLM platform for two consumers: **NL-Proposal-Builder** (currently on Groq's cloud API, moving to local) and **Niren's AI agents** (new build). Rather than each consumer needing its own GPU access, this platform exposes one shared internal API endpoint that both call over the network — architecturally identical to how NL-Proposal-Builder already calls Groq today, just pointed at an internal IP instead of a cloud one.

**Why this design, specifically:** the physical GPU (NVIDIA A30) lives in NLABDLAS01, a Windows Server 2019 Hyper-V host that also runs 10+ other production VMs. Windows Server 2019 cannot do GPU-P (paravirtualized GPU sharing across multiple VMs/WSL2 — that needs Windows Server 2022+), so the only way to get GPU access into a VM at all is DDA (Discrete Device Assignment), which binds the whole GPU to exactly one VM. Given that constraint, the only way to have *multiple consumers* share the GPU is for exactly one VM to hold the GPU and run the serving layer, with everything else acting as a network client of that one endpoint. See `README.md` for the resulting architecture diagram.

## 2. Host environment

- **Physical host:** NLABDLAS01, Dell PowerEdge R750, Windows Server 2019 Standard, BIOS 1.11.2, Xeon Silver 4310 (48 logical CPUs), 128GB RAM, IP `192.168.71.2`
- **GPU:** NVIDIA A30, 24GB VRAM, Ampere architecture — confirmed healthy via `nvidia-smi -q` on 19 Jul 2026 (0 ECC errors, PCIe Gen4 x16 full link, normal temps/power)
- **Host RAM headroom:** at time of build, 10 other VMs were already running on this host consuming ~94GB of 128GB RAM, leaving ~34GB free. This capped how large the new VM could reasonably be — see Section 4.
- **Do not touch:** NLVMH1PTCPNS, NLVMH1PTEPP, NLVMH1PTNVS, NLVMH1PTSGV, NLVMH1PTSGV2, NLVMH1PTSMC, SAADAuditServer, SAADControllerServer, SAADGatewayServer — all production VMs on this host, unrelated to this project. `VM-AI_Assistant` (44 vCPU / ~98GB RAM, currently off) was considered and rejected — its origin is unconfirmed and it's too large to fit alongside the currently-running VMs anyway.

## 3. Phase 1 — VM creation and GPU passthrough

### 3.1 VM specs

New VM, **not** a reuse of the existing `NL-ProposalBuilder-01` VM (kept separate deliberately — GPU/driver work on a new VM has zero blast radius on the live production app):

| Setting | Value |
|---|---|
| Name | `NL-AI-Inference-01` |
| Generation | 1 |
| vCPU | 8 |
| RAM | 24GB (static, not dynamic) |
| Disk | 250GB VHDX, `D:\Virtual Machines\NL-AI-Inference-01\` |
| Checkpointing | Disabled (required for DDA) |
| AutomaticStopAction | TurnOff (required for DDA) |
| NICs | eth0 → external LAN switch (`192.168.71.11/24`, gw `192.168.71.1`), eth1 → `Mgmt-Switch` internal (`10.10.10.3/24`, no gateway) |

Run `infra/01-create-vm.ps1` on the host to provision this (adjust switch names / GPU LocationPath to match your own `Get-VMSwitch` / `Get-VMHostAssignableDevice` output first — don't assume the values in the script match a different host).

### 3.2 GPU DDA attachment — and the MMIO gotcha

DDA assignment requires the VM to be off. Sequence: dismount the GPU from wherever it currently is (host or another VM), set MMIO space, then `Add-VMAssignableDevice`.

**The gotcha that cost real debugging time:** `HighMemoryMappedIoSpace` must exceed the GPU's BAR1 aperture size, not just roughly match its VRAM. We initially set this to exactly `32GB` (matching the A30's 24GB VRAM with what seemed like reasonable headroom). The VM booted fine, Ubuntu installed fine, but `lspci` inside the guest showed **no NVIDIA device at all** — not an error, just absent, like the GPU was never assigned.

Root cause was in `dmesg`:
```
hv_pci ...: Need 0x802000000 of high MMIO space. Consider reconfiguring the VM.
```
`0x802000000` ≈ 32.03GB — about 32MB more than the 32GB we'd allocated. The A30's BAR1 is exactly 32,768 MiB, and the guest needs a bit more than that once other overhead is factored in.

**Fix:** set `HighMemoryMappedIoSpace` to `64GB` instead of exactly matching the card's VRAM. This is already baked into `infra/01-create-vm.ps1`. If a different GPU is ever used, don't assume its exact VRAM size is a safe MMIO value — go generous.

**Diagnostic checklist if a DDA'd GPU doesn't show up in the guest:**
1. `Get-VMAssignableDevice -VMName <name>` on the host — confirms Hyper-V thinks it's assigned
2. `lspci` (no grep filter) inside the guest — see the full device list, not just a filtered NVIDIA search
3. `sudo dmesg | grep -iE "pci|nvidia"` inside the guest — look specifically for "Need 0x... of high MMIO space" lines
4. If found, shut the guest down cleanly (`sudo shutdown -h now`), bump `HighMemoryMappedIoSpace` from the host, restart

### 3.3 Ubuntu Server install — choices made

- **ISO:** Ubuntu Server 22.04.5 LTS (`ubuntu-22.04.5-live-server-amd64.iso`), standard kernel — deliberately **not** the HWE (Hardware Enablement) kernel option in the GRUB menu. HWE kernels rotate more often and can break out-of-tree NVIDIA driver modules on auto-updates; standard kernel is the safer choice for a GPU/Docker production box.
- **Base:** "Ubuntu Server" (not the minimized variant) — minimized strips out tools useful for interactive administration while installing Docker/drivers/troubleshooting.
- **Third-party drivers:** left unchecked during install — the NVIDIA driver is installed deliberately afterward (Section 3.4), matched to a specific version, not whatever the installer would auto-pick.
- **Storage:** guided, entire disk, LVM (no LUKS — this is an internal-network box that needs unattended reboots; full-disk encryption would block that without additional TPM/network-unlock tooling we haven't set up). **Important:** the guided LVM layout by default only allocates ~100GB of a 250GB disk to `/`, leaving the rest as unused free space in the volume group — go into the `ubuntu-lv` edit screen and set it to the max available size before continuing, or you'll need `lvextend` + `resize2fs` later to fix it.
- **Network:** static IPs as listed in 3.1 (no DHCP available on either switch).
- **SSH:** "Install OpenSSH server" **must** be checked — easy to miss, and without it you're stuck using the Hyper-V console for everything afterward instead of SSH from your own machine.
- **Snaps:** none selected on the "featured server snaps" screen — Docker is installed manually via apt in Phase 2, not as a snap (snap Docker has known GPU passthrough compatibility issues).

### 3.4 Driver + Docker install

Run `infra/02-setup-gpu-docker.sh` inside the guest (after fresh SSH login). It installs, in order: build tools + kernel headers, NVIDIA driver + CUDA (via NVIDIA's own apt repo — resulted in driver `610.43.02` / CUDA 13.3 support on this build, well ahead of any current inference engine's requirements), Docker Engine (apt repo, not snap), and `nvidia-container-toolkit`.

Two manual steps after the script (can't be scripted — both need a fresh session):
1. `sudo reboot` — loads the new NVIDIA kernel module
2. Log back in, verify: `nvidia-smi` (host-level check) then `docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi` (the real test — confirms containers can reach the GPU, not just the host OS)

**Common snag:** `sudo usermod -aG docker $USER` does not take effect in the current shell. Don't use `newgrp docker` to work around this — it can prompt for a password it shouldn't need and just wastes time. Log out (`exit`) and reconnect via SSH instead; check with `groups` that `docker` is listed before retrying docker commands without `sudo`.

## 4. Phase 2 — Ollama serving layer

Deployed via `serving/docker-compose.yml`. Key config, and why:

- `OLLAMA_NUM_PARALLEL=1` — matches Niren's initial concurrency spec for the pilot
- `OLLAMA_MAX_LOADED_MODELS=1` — the A30's 24GB VRAM cannot hold all three model tiers resident simultaneously (14B Q4 is ~8-9GB, 32B Q4 is ~18-20GB — those two alone exceed 24GB together), so this forces predictable swap-on-demand behavior instead of letting Ollama guess
- `OLLAMA_KEEP_ALIVE=30m` — see the cold-start note below; a longer keep-alive reduces how often intermittent traffic re-pays the cold-start cost

### 4.1 Models

| Tier | Model | Ollama tag | Size | License |
|---|---|---|---|---|
| Primary / everyday | Qwen3 14B | `qwen3:14b` | 9.3GB | Apache 2.0 |
| Heavy reasoning | DeepSeek-R1-Distill-Qwen-32B | `deepseek-r1:32b` | 19GB | MIT (DeepSeek's own release, built on Qwen2.5-32B) |
| Fast utility | Gemma 3 4B | `gemma3:4b` | 3.3GB | Apache 2.0 |

**Licensing note:** Alibaba closed their Qwen 3.7-Max/Plus *flagship* tier to paid-API-only in 2026, but kept a mid-tier open under Apache 2.0 (what `qwen3:14b` and the DeepSeek distillation's base model both are). This doesn't affect anything already downloaded under an open license — Apache 2.0/MIT grants on released weights can't be revoked retroactively, and there's no phone-home/enforcement mechanism for self-hosted open-weight models. The risk is purely forward-looking (not automatically getting Alibaba's newest flagship for free), not a compliance issue with what's deployed here.

**Scope note:** only `qwen3:14b` is strictly required to validate the pipeline end to end. The other two tiers exist because Niren's usage plan calls for them eventually, but don't block getting NL-Proposal-Builder and the guardrails/WebUI layer working — add reasoning/utility-tier routing once real usage patterns justify the complexity.

### 4.2 Benchmark results (qwen3:14b, 19 Jul 2026)

`ollama ps` confirmed `100% GPU` (no CPU offload).

| Run | Prompt eval rate | Eval rate (generation) | Load duration |
|---|---|---|---|
| Cold (first request after container start) | 0.64 tok/s | — | 36.2s |
| Warm (same prompt, second run) | 106.06 tok/s | **51.82 tok/s** | 4.9s |

**Important operational note:** the first inference after any container/model (re)start is a cold-start outlier caused by one-time CUDA kernel JIT/warmup — not a real performance problem. The warm number (51.82 tok/s) is the real figure, and it comfortably beats the ~35 tok/s reference point Niren flagged as "not guaranteed." Don't panic or start debugging based on a slow first request after a restart — always benchmark on the second request.

### 4.3 Not yet configured

- `num_ctx=8192` (Niren's spec) — plan is to set this per-request via API `options`, not bake it into the model, so each consumer (NL-Proposal-Builder, agents) can override if it ever needs a different context size. Not yet wired up — do this when building the Phase 5 integration.
- Qwen3 runs in "thinking" mode by default (visible reasoning block before the final answer — adds tokens and latency). Likely want to suppress this for proposal generation specifically via API options. Revisit in Phase 5.

## 5. Remaining phases (not yet built)

- **Phase 3 — Guardrails:** NVIDIA NeMo Guardrails in front of the Ollama API. Policy layer for content safety, prompt injection defense, topic boundaries appropriate to internal reasoning/document/code use.
- **Phase 4 — Access layer:** Open WebUI pointed at the guardrailed endpoint, for staff chat access separate from the raw API.
- **Phase 5 — NL-Proposal-Builder integration:** update `src/anthropic.js`'s multi-provider router to add a "local" provider hitting this endpoint, flip `AI_PROVIDER` in `.env`, test end to end, decide on a Groq/OpenAI fallback strategy.
- **Phase 6 — Hand off to Niren:** give him the guardrailed endpoint for his agent framework. Confirm he understands the concurrency=1 shared-queue behavior — his agent traffic and proposal-generation traffic queue behind each other during this pilot, no priority lane yet.
- **Phase 7 — Backlog:** document-vision (VLM) and embedding/reranker model tiers, evaluate migrating from Ollama to vLLM once concurrency needs grow (the VM's isolated driver — CUDA 13.3 — makes this a low-risk swap later), consider a priority queue so proposal generation isn't starved by agent traffic, consider MIG partitioning on the A30 for hard workload isolation if needed.

## 6. Troubleshooting quick reference

| Symptom | Cause | Fix |
|---|---|---|
| GPU doesn't show in `lspci` inside guest | MMIO space too small | See Section 3.2 — bump `HighMemoryMappedIoSpace` to 64GB, restart guest |
| `Mount-VMHostAssignableDevice` fails: "cannot be deleted because it is being used" | Host has an active driver bound to the GPU (e.g. after a Windows-side health check) | `Disable-PnpDevice -InstanceId "<id>" -Confirm:$false` first, then retry the dismount/mount |
| `docker` commands need `sudo` even after `usermod -aG docker` | Group change needs a fresh login | `exit` and reconnect via SSH, don't use `newgrp` (can hit an unexpected password prompt) |
| First LLM request after container start is very slow (30-40s, <1 tok/s prompt eval) | One-time CUDA JIT/warmup cost | Not a bug — benchmark the second request instead |
| PowerShell multi-line paste produces garbled/merged commands | RDP clipboard paste can drop characters (e.g. a closing quote), causing PowerShell's `>>` continuation prompt to merge two separate commands into one | Paste commands one at a time rather than as a block; if you see `>>` unexpectedly, `Ctrl+C` and retry that command alone |

## 7. Credentials and access

- VM SSH: `ssh <username>@192.168.71.11` (LAN) — see whoever provisioned the VM for the account; not stored in this repo
- Ollama API (internal only, not guardrailed yet): `http://192.168.71.11:11434`
- Host PowerShell/RDP: `192.168.71.2` — standard NLABDLAS01 admin credentials, not stored in this repo
