#!/usr/bin/env bash
# ============================================================================
# P1-01 — AI VM Resize Validation & Acceptance Check
# Target: aiinference (192.168.71.11) — Ubuntu 22.04, air-gapped
# Run ON the AI VM:   bash vm-validate.sh
# Exit 0 = all acceptance criteria PASS. Prints a committed-ready report.
# ============================================================================
set -u
PASS=0; FAIL=0
ok()   { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
info() { echo "  [info] $1"; }

echo "======================================================================"
echo " P1-01 AI VM Validation Report — $(date -Iseconds)"
echo " Host: $(hostname)  |  Kernel: $(uname -r)"
echo "======================================================================"

# ---- 1. vCPU >= 16 -------------------------------------------------------
VCPU=$(nproc)
echo "[1] Logical processors: $VCPU (required >= 16)"
[ "$VCPU" -ge 16 ] && ok "vCPU count $VCPU >= 16" || bad "vCPU count $VCPU < 16"

# ---- 2. RAM >= 48 GB -----------------------------------------------------
RAM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
RAM_GB=$((RAM_KB / 1024 / 1024))
echo "[2] Total RAM: ${RAM_GB} GiB (required >= 48 GiB)"
[ "$RAM_GB" -ge 48 ] && ok "RAM ${RAM_GB} GiB >= 48 GiB" || bad "RAM ${RAM_GB} GiB < 48 GiB"

# ---- 3. GPU healthy ------------------------------------------------------
echo "[3] NVIDIA GPU (A30 expected)"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=name,memory.total,driver_version,temperature.gpu,ecc.errors.uncorrected.volatile.total \
               --format=csv,noheader | sed 's/^/  [info] GPU: /'
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
    ECC_ERR=$(nvidia-smi --query-gpu=ecc.errors.uncorrected.volatile.total --format=csv,noheader | head -1 | tr -d ' ')
    echo "$GPU_NAME" | grep -q "A30" && ok "GPU is A30" || bad "Unexpected GPU: $GPU_NAME"
    [ "$ECC_ERR" = "0" ] && ok "ECC uncorrected errors = 0" || bad "ECC errors: $ECC_ERR"
else
    bad "nvidia-smi not found"
fi

# ---- 4. Ollama serving ---------------------------------------------------
echo "[4] Ollama runtime"
if curl -sf --max-time 5 http://localhost:11434/api/tags >/tmp/ollama_tags.json 2>/dev/null; then
    ok "Ollama API responding on :11434"
    MODELS=$(python3 -c "import json;print(', '.join(m['name'] for m in json.load(open('/tmp/ollama_tags.json'))['models']))" 2>/dev/null || echo "?")
    info "Models loaded: $MODELS"
else
    bad "Ollama API not responding on :11434"
fi

# ---- 5. Docker healthy ---------------------------------------------------
echo "[5] Docker"
if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
    ok "Docker operational"
    docker ps --format '  [info] container: {{.Names}}  ({{.Status}})  {{.Ports}}'
else
    bad "Docker not operational"
fi

# ---- 6. Disk headroom ----------------------------------------------------
echo "[6] Root filesystem"
DISK_AVAIL=$(df -BG / | awk 'NR==2 {gsub("G","",$4); print $4}')
info "Available: ${DISK_AVAIL}G"
[ "$DISK_AVAIL" -ge 100 ] && ok ">=100G free" || bad "Low disk: ${DISK_AVAIL}G free"

# ---- 7. Swap sanity ------------------------------------------------------
SWAP_USED_MB=$(awk '/SwapTotal/ {t=$2} /SwapFree/ {f=$2} END {print int((t-f)/1024)}' /proc/meminfo)
info "Swap in use: ${SWAP_USED_MB} MB (informational)"

echo "======================================================================"
echo " RESULT: $PASS passed, $FAIL failed"
if [ "$FAIL" -eq 0 ]; then
    echo " P1-01 ACCEPTANCE: PASS — VM meets Phase 1 foundation requirements"
    echo "======================================================================"
    exit 0
else
    echo " P1-01 ACCEPTANCE: FAIL — resolve failures above (resize not yet applied?)"
    echo "======================================================================"
    exit 1
fi
