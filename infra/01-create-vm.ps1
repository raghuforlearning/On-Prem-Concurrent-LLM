# =============================================================================
# 01-create-vm.ps1
# Provisions the AI Inference VM on Hyper-V with NVIDIA GPU DDA passthrough.
# Run as Administrator on the Hyper-V host (NLABDLAS01), in PowerShell.
#
# Prereqs on the host:
#   - Hyper-V role already enabled
#   - Ubuntu Server 22.04.x LTS ISO staged locally (adjust $ISOPath below)
#   - GPU must be free (not currently assigned to another VM). If it's
#     assigned elsewhere, detach it first - see README.md troubleshooting.
# =============================================================================

$VMName          = "NL-AI-Inference-01"
$VMPath          = "D:\Virtual Machines"
$VHDPath         = "$VMPath\$VMName\$VMName.vhdx"
$VHDSizeBytes    = 250GB
$MemoryBytes     = 24GB
$CPUCount        = 8
$ExternalSwitch  = "Broadcom NetXtreme Gigabit Ethernet - Virtual Switch"   # LAN, adjust to your Get-VMSwitch output
$MgmtSwitch      = "Mgmt-Switch"                                            # internal management network
$ISOPath         = "D:\ISO\ubuntu-22.04.5-live-server-amd64.iso"

# The GPU's LocationPath, as reported by Get-VMHostAssignableDevice / Get-VMAssignableDevice.
# This is specific to the physical PCIe slot the GPU sits in - verify on your own host,
# do not assume this value is correct for a different server.
$GPULocationPath = "PCIROOT(C9)#PCI(0200)#PCI(0000)"

# -----------------------------------------------------------------------------
# 1. Create the VM
# -----------------------------------------------------------------------------
New-VM -Name $VMName -Generation 1 -MemoryStartupBytes $MemoryBytes `
  -NewVHDPath $VHDPath -NewVHDSizeBytes $VHDSizeBytes -SwitchName $ExternalSwitch

Add-VMNetworkAdapter -VMName $VMName -SwitchName $MgmtSwitch

Set-VM -VMName $VMName -ProcessorCount $CPUCount -AutomaticStopAction TurnOff `
  -CheckpointType Disabled -DynamicMemory:$false

# AutomaticStopAction MUST be TurnOff and checkpoints MUST be disabled -
# both are hard requirements for GPU DDA passthrough to work at all.

# -----------------------------------------------------------------------------
# 2. Attach the GPU via Discrete Device Assignment (DDA)
# -----------------------------------------------------------------------------
# If the GPU is currently bound to the host OS (e.g. after a driver install
# for a health check), it must be disabled and dismounted first:
#
#   Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match "NVIDIA" }
#   Disable-PnpDevice -InstanceId "<InstanceId from above>" -Confirm:$false
#   Dismount-VMHostAssignableDevice -LocationPath $GPULocationPath -Force
#
# If it's currently assigned to a DIFFERENT VM, detach it from that VM first:
#   Stop-VM -Name "<other VM>" -Force
#   Remove-VMAssignableDevice -VMName "<other VM>" -LocationPath $GPULocationPath
#   Mount-VMHostAssignableDevice -LocationPath $GPULocationPath   # returns it to host
#   (then disable/dismount as above)

Dismount-VMHostAssignableDevice -LocationPath $GPULocationPath -Force

# IMPORTANT - MMIO space gotcha (cost us a debugging round on this build):
# HighMemoryMappedIoSpace must comfortably exceed the GPU's BAR1 aperture size.
# The A30's BAR1 is exactly 32GB. Setting HighMemoryMappedIoSpace to exactly
# 32GB was NOT enough - the GPU never enumerated on the guest's PCI bus at all,
# and `dmesg` inside the guest showed:
#   "hv_pci ...: Need 0x802000000 of high MMIO space. Consider reconfiguring the VM."
# (0x802000000 = ~32.03GB - about 32MB short of what we'd given it.)
# Use 64GB for real headroom, not the card's exact VRAM size.
Set-VM -VMName $VMName -GuestControlledCacheTypes $true
Set-VM -VMName $VMName -LowMemoryMappedIoSpace 3GB
Set-VM -VMName $VMName -HighMemoryMappedIoSpace 64GB

Add-VMAssignableDevice -VMName $VMName -LocationPath $GPULocationPath

# Verify the assignment took:
Get-VMAssignableDevice -VMName $VMName

# -----------------------------------------------------------------------------
# 3. Attach installer ISO and boot
# -----------------------------------------------------------------------------
Add-VMDvdDrive -VMName $VMName -Path $ISOPath
Set-VMBios -VMName $VMName -StartupOrder @("CD", "IDE", "LegacyNetworkAdapter", "Floppy")

Start-VM -Name $VMName

Write-Host ""
Write-Host "VM '$VMName' created and booting. Connect via Hyper-V Manager (right-click -> Connect)"
Write-Host "to complete the interactive Ubuntu Server install. See RUNBOOK.md for the exact"
Write-Host "install-time choices (network config, storage layout, SSH, etc.)."
Write-Host ""
Write-Host "After the OS install finishes and the VM reboots, eject the ISO so it doesn't"
Write-Host "boot back into the installer:"
Write-Host '  Set-VMDvdDrive -VMName "NL-AI-Inference-01" -Path $null'
