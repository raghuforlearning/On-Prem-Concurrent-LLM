# NationLabs AI Presales Orchestrator — Air-Gap Transfer Bundle

Copy this entire folder to a USB drive, then to the AI VM (Linux x86_64).

## Contents
| Item | Purpose |
|---|---|
| `python-3.11-linux.tar.gz` | Self-contained Python 3.11.15 runtime (no OS packages needed) |
| `wheelhouse/` (48 wheels) | All Python dependencies, Linux x86_64 binaries |
| `app.tar.gz` | Application source (orchestrator, scripts, templates) |
| `config/orchestrator.yaml` | Runtime config (thresholds, VAT, follow-up time, holidays) |
| `install_offline.sh` | One-shot installer (no Docker, no internet) |
| `deploy/nationlabs-orchestrator.service` | systemd unit template |

## Install (on the VM)
```bash
cd <bundle-directory>
chmod +x install_offline.sh
./install_offline.sh
```
The installer:
1. creates `/opt/nationlabs/` runtime tree
2. unpacks the Python runtime and app
3. installs dependencies **offline** from the wheelhouse
4. checks Ollama reachability (set `NL_OLLAMA_URL` if not `127.0.0.1:11434`)
5. registers and starts a systemd service on **port 8100**

## After install
1. Fill `vendor_master.xlsx` + `ownership_matrix.xlsx` (blank templates in
   `/opt/nationlabs/app/data_templates/`), copy to `/opt/nationlabs/data/`
2. Import: `/opt/nationlabs/python/bin/python3 /opt/nationlabs/app/scripts/import_registers.py /opt/nationlabs/data`
3. Open `http://<vm-ip>:8100`

## Notes
- Models required in Ollama: **qwen3:14b** (main) and **gemma3:4b** (fast) — both already on the VM.
- Scanned-image OCR needs the `tesseract` binary (not bundled; text/PDF/docx/xlsx intake works without it).
  If needed later, carry `tesseract-ocr` .debs for your distro and `sudo dpkg -i` them.
- Service control: `sudo systemctl status|restart|stop nationlabs-orchestrator`
- Logs: `journalctl -u nationlabs-orchestrator -f`
