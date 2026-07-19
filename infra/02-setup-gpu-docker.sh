#!/usr/bin/env bash
# =============================================================================
# 02-setup-gpu-docker.sh
# Installs the NVIDIA driver + CUDA, Docker Engine, and nvidia-container-toolkit
# on a fresh Ubuntu Server 22.04 LTS install (the AI Inference VM guest).
#
# Run as a non-root user with sudo access, e.g.:
#   chmod +x 02-setup-gpu-docker.sh
#   ./02-setup-gpu-docker.sh
#
# Two manual steps happen AFTER this script - see the "Next steps" printout
# at the end. This script cannot fully automate them because a reboot and a
# fresh login are both required in between.
# =============================================================================
set -euo pipefail

echo "=== System update ==="
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential "linux-headers-$(uname -r)"

echo "=== NVIDIA driver + CUDA (NVIDIA's own apt repo, not Ubuntu's bundled driver) ==="
# Using NVIDIA's repo keeps driver and CUDA toolkit versions in sync, and gets a
# meaningfully newer driver than Ubuntu's default packages. On this build it
# resulted in driver 610.43.02 / CUDA 13.3 support - well ahead of what any
# current inference engine (Ollama, vLLM) actually requires.
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-drivers

echo "=== Docker Engine (official apt repo - NOT the snap package) ==="
# The snap-packaged Docker has known compatibility problems with
# nvidia-container-toolkit GPU passthrough. Always use the apt-installed
# Docker Engine on a GPU host.
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== Add current user to the docker group (so sudo isn't needed for docker commands) ==="
sudo usermod -aG docker "$USER"
echo "NOTE: this does NOT take effect in the current shell/session - see 'Next steps' below."

echo "=== nvidia-container-toolkit (lets containers see the GPU) ==="
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

cat <<'EOF'

=== Setup script finished. Two manual steps remain: ===

1. Reboot to load the new NVIDIA kernel module:
     sudo reboot

2. After reboot, log back in (fresh session picks up your docker group
   membership) and verify everything:
     nvidia-smi
     docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

   The second command is the real test - it confirms a container can
   actually reach the GPU, not just the host OS.

If `docker` commands still ask for sudo after logging back in, check your
group membership with `groups` - if `docker` isn't listed, the usermod
command above didn't take, and you'll need to log out/in again (NOT just
`newgrp docker`, which can prompt for a password it shouldn't need).

EOF
