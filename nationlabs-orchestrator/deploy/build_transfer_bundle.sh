#!/bin/bash
# build_transfer_bundle.sh — run on a CONNECTED machine.
# Produces transfer_bundle/ ready to carry to the air-gapped VM via USB.
set -euo pipefail
BUNDLE=transfer_bundle
mkdir -p $BUNDLE/wheelhouse $BUNDLE/images

echo "== 1. Python wheelhouse (linux/amd64 wheels for VM) =="
pip download -r requirements.txt -d $BUNDLE/wheelhouse \
  --platform manylinux2014_x86_64 --python-version 3.11 --only-binary=:all: || {
    echo "some packages lack binary wheels; retrying without platform pin (check arch!)"
    pip download -r requirements.txt -d $BUNDLE/wheelhouse
}

echo "== 2. Base image for Docker build =="
docker pull python:3.11-slim
docker save -o $BUNDLE/images/python-3.11-slim.tar python:3.11-slim

echo "== 3. Application source =="
tar czf $BUNDLE/app.tar.gz orchestrator scripts data_templates requirements.txt deploy

echo "== 4. Config template =="
mkdir -p $BUNDLE/config
cat > $BUNDLE/config/orchestrator.yaml <<'YAML'
# NationLabs Orchestrator — air-gapped VM config
finance_threshold_aed: 200000
vat_percent: 5.0
followup_time: "09:00"
timezone: "Asia/Dubai"
# Populate with UAE public holidays (ISO dates) each year:
uae_holidays: []
# finance_team_email: "finance@nationlabs.ae"
# presales_manager_email: "presales@nationlabs.ae"
YAML

echo "Bundle ready in $BUNDLE/ — copy the whole folder to USB."
