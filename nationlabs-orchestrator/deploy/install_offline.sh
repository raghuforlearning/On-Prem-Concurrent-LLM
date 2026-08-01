#!/bin/bash
# install_offline.sh — run ON THE AIR-GAPPED VM from the USB bundle directory.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Runtime tree =="
sudo mkdir -p /opt/nationlabs/{inbox,outbox/{vendor_emails,internal_alerts,approval_requests},proposals,data,logs/audit,db,rfp_archive,config}
sudo chown -R "$USER":"$USER" /opt/nationlabs
cp transfer_bundle/config/orchestrator.yaml /opt/nationlabs/config/ 2>/dev/null || true

echo "== 2. Load base image =="
docker load -i transfer_bundle/images/python-3.11-slim.tar

echo "== 3. Unpack app =="
tar xzf transfer_bundle/app.tar.gz

echo "== 4. Build orchestrator image offline (wheelhouse, no index) =="
docker build --network=none \
  --build-arg PIP_NO_INDEX=1 \
  -f deploy/Dockerfile.offline -t nationlabs-orchestrator:1.0 .

echo "== 5. Import vendor & ownership registers =="
echo "   Edit /opt/nationlabs/data/vendor_master.xlsx and ownership_matrix.xlsx, then:"
echo "   docker run --rm -v /opt/nationlabs:/opt/nationlabs nationlabs-orchestrator:1.0 \\"
echo "     python scripts/import_registers.py /opt/nationlabs/data"

echo "== 6. Start services =="
cd deploy && docker compose up -d

echo "== Done. UI: http://192.168.71.11:8100 =="
