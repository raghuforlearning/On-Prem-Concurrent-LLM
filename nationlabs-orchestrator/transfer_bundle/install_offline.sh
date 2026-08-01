#!/bin/bash
# install_offline.sh — run ON THE AIR-GAPPED VM from the USB bundle directory.
# No Docker required: installs a self-contained Python 3.11 runtime + app.
# Tested target: Linux x86_64 (Ubuntu/Debian/RHEL-like), Ollama reachable locally.
set -euo pipefail
cd "$(dirname "$0")"
ROOT=/opt/nationlabs

echo "== 1. Runtime tree =="
sudo mkdir -p $ROOT/{inbox,outbox/{vendor_emails,internal_alerts,approval_requests},proposals,data,logs/audit,db,rfp_archive,config,app}
sudo chown -R "$USER":"$USER" $ROOT
cp config/orchestrator.yaml $ROOT/config/ 2>/dev/null || true

echo "== 2. Self-contained Python 3.11 runtime =="
tar xzf python-3.11-linux.tar.gz -C $ROOT   # creates $ROOT/python
PY=$ROOT/python/bin/python3
$PY --version

echo "== 3. Application =="
tar xzf app.tar.gz -C $ROOT/app

echo "== 4. Dependencies (offline, from wheelhouse) =="
$PY -m pip install --no-index --find-links wheelhouse -r requirements.txt

echo "== 5. Ollama connectivity check =="
OLLAMA_URL="${NL_OLLAMA_URL:-http://127.0.0.1:11434}"
curl -s -m 5 "$OLLAMA_URL/api/tags" >/dev/null \
  && echo "Ollama OK at $OLLAMA_URL" \
  || echo "WARNING: Ollama not reachable at $OLLAMA_URL — start it before launching."

echo "== 6. systemd service =="
sed "s|__OLLAMA_URL__|$OLLAMA_URL|" deploy/nationlabs-orchestrator.service \
  | sudo tee /etc/systemd/system/nationlabs-orchestrator.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now nationlabs-orchestrator

echo "== 7. Import vendor & ownership registers =="
echo "   1) Copy your filled vendor_master.xlsx and ownership_matrix.xlsx to $ROOT/data/"
echo "      (blank templates: $ROOT/app/data_templates/)"
echo "   2) Run: $PY $ROOT/app/scripts/import_registers.py $ROOT/data"
echo ""
echo "== Done. UI: http://<this-vm-ip>:8100 =="
