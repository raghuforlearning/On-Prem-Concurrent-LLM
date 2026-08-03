@echo off
cd /d "C:\Raghu Official\AI works\Kimi\Research & Brainstorming\nationlabs-orchestrator"
"C:\Users\Raghunarayan Mohan\AppData\Roaming\kimi-desktop\daimon-share\daimon\runtime\python\.venv\Scripts\python.exe" -m uvicorn orchestrator.web.app:app --host 0.0.0.0 --port 7100 >> nationlabs_runtime\server.log 2>&1
