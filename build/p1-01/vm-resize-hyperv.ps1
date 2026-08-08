# ============================================================================
# P1-01 — AI VM Resize Runbook (Hyper-V host side)
# Run ON THE PHYSICAL HOST NLABDLAS01 (192.168.71.2) in an ELEVATED PowerShell.
# IMPACT: the AI VM 'aiinference' will be SHUT DOWN for ~2-3 minutes.
#         Ollama + guardrails containers auto-start on boot (verify after).
# Target state (Architecture v2.0 §21 / Phase 0 §3): >=16 vCPU, >=48 GiB RAM.
# ============================================================================

$VMName      = "aiinference"          # <-- confirm with: Get-VM
$TargetVCPU  = 16
$TargetRAMGB = 56                     # 56 GiB startup; host has 128 GB total

Write-Host "=== P1-01 Resize: $VMName -> $TargetVCPU vCPU / $TargetRAMGB GiB ===" -ForegroundColor Cyan

# --- 0. Pre-flight: show current allocation -------------------------------
Get-VM $VMName | Select-Object Name, State, ProcessorCount,
    @{n='MemoryStartupGB';e={[math]::Round($_.MemoryStartup/1GB,1)}} | Format-List

# --- 1. Graceful shutdown (Docker containers stop cleanly) ----------------
Write-Host "Shutting down $VMName gracefully (120 s timeout)..."
Stop-VM -Name $VMName -Force:$false
$deadline = (Get-Date).AddSeconds(120)
do { Start-Sleep 3; $state = (Get-VM $VMName).State } while ($state -ne 'Off' -and (Get-Date) -lt $deadline)
if ((Get-VM $VMName).State -ne 'Off') {
    Write-Host "Graceful shutdown timed out. Investigate inside the VM; NOT force-powering off." -ForegroundColor Red
    exit 1
}

# --- 2. Apply resize ------------------------------------------------------
Set-VMProcessor -VMName $VMName -Count $TargetVCPU
# Static memory (Dynamic Memory complicates guaranteed headroom for inference):
Set-VMMemory -VMName $VMName -StartupBytes ($TargetRAMGB * 1GB) -DynamicMemoryEnabled $false

# --- 3. Power on ----------------------------------------------------------
Start-VM -Name $VMName
Write-Host "Waiting for VM heartbeat..."
$deadline = (Get-Date).AddSeconds(180)
do { Start-Sleep 5; $hb = (Get-VMIntegrationService -VMName $VMName |
      Where-Object {$_.Name -eq 'Heartbeat'}).PrimaryStatusDescription } while ($hb -ne 'OK' -and (Get-Date) -lt $deadline)
Write-Host "Heartbeat: $hb"

# --- 4. Post-check from host ----------------------------------------------
Get-VM $VMName | Select-Object Name, State, ProcessorCount,
    @{n='MemoryStartupGB';e={[math]::Round($_.MemoryStartup/1GB,1)}} | Format-List
Write-Host "=== Host-side resize complete. Next: run vm-validate.sh INSIDE the VM ===" -ForegroundColor Green
