#!/bin/bash
# FBPIC setup for CUDA 13.0 with MPICH (H100 compatible)
# Based on Maxwell cluster recipe, using MPICH instead of OpenMPI

set -e

echo "=========================================="
echo "FBPIC Setup for CUDA 13.0 with MPICH"
echo "=========================================="

# 1. Install system dependencies
apt-get update
apt-get install -y wget git nano build-essential
rm -rf /var/lib/apt/lists/*

# 2. Install Miniconda if not already present
if [ ! -d /opt/conda ]; then
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
    bash miniconda.sh -b -p /opt/conda
    rm miniconda.sh
    /opt/conda/bin/conda clean -afy
fi
export PATH="/opt/conda/bin:$PATH"
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 3. Set environment variables
export OMP_NUM_THREADS=1
export PYTHONPATH=/app
export LD_LIBRARY_PATH="/opt/conda/lib:${LD_LIBRARY_PATH}"

# 4. Install Python 3.11 (CRITICAL!)
echo "Installing Python 3.11..."
conda install -y python=3.11

# 5. Install basic packages
echo "Installing basic packages..."
conda install -y scipy h5py mkl

# 6. Install CUDA 13 specific packages WITH HEADERS
echo "Installing CUDA 13 packages with headers..."
conda install -y -c conda-forge -c nvidia \
    numba-cuda \
    cutensor \
    nccl \
    cuda-tools \
    cuda-toolkit \
    cuda-nvvp \
    cuda-nvtx \
    cuda-nvrtc \
    cuda-nvcc \
    cuda-cudart-dev \
    cuda-driver-dev \
    cuda-nvrtc-dev \
    cuda-version=13.0

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main            
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r  

# 7. Install nvidia_nvjitlink for CUDA 13 (CRITICAL)
echo "Installing nvidia_nvjitlink..."
pip install 'nvidia_nvjitlink>13.0'

# 8. Install CuPy for CUDA 13
echo "Installing cupy-cuda13x..."
pip install cupy-cuda13x

# 9. Install MPICH and mpi4py
echo "Installing MPICH and mpi4py..."
# Install mpich and mpi4py together from conda (pre-built, compatible)
conda install -y -c conda-forge mpich mpi4py

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main            
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r  

# 10. Install patched FBPIC
echo "Installing patched FBPIC..."
cd /tmp
rm -rf fbpic
git clone -b inline_false https://github.com/delaossa/fbpic.git
cd fbpic
pip install -e .
cd /app

# 11. Install openpmd-viewer and optimas (CUDA 13 compatible)
echo "Installing openpmd-viewer and optimas-related packages..."
conda install -y -c conda-forge openpmd-viewer

echo "Installing PyTorch and optimas for CUDA 13..."
# Install Intel libraries (fixes iJIT_NotifyEvent error)
conda install -y -c conda-forge intel-openmp mkl mkl-service
# Install PyTorch CPU-only via pip (avoids CUDA 12 packages)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
# Install ax-platform (won't pull CUDA 12 packages now)
pip install ax-platform==0.5.0
# Install optimas
pip install 'optimas[all]'

# 12. Create /app/tmp directory
mkdir -p /app/tmp && chmod 1777 /app/tmp

echo "=========================================="
echo "Setting CUDA_HOME for CUDA 13.0"
echo "=========================================="

# Check system CUDA first (from devel image)
if [ -f /usr/local/cuda-13.0/targets/x86_64-linux/include/cuda_fp16.h ]; then
    CUDA_HOME="/usr/local/cuda-13.0/targets/x86_64-linux"
    echo "✓ Using system CUDA: $CUDA_HOME"
elif [ -f /usr/local/cuda/targets/x86_64-linux/include/cuda_fp16.h ]; then
    CUDA_HOME="/usr/local/cuda/targets/x86_64-linux"
    echo "✓ Using system CUDA: $CUDA_HOME"
elif [ -f /opt/conda/targets/x86_64-linux/include/cuda_fp16.h ]; then
    CUDA_HOME="/opt/conda/targets/x86_64-linux"
    echo "✓ Using conda CUDA: $CUDA_HOME"
else
    echo "❌ Cannot find CUDA headers!"
    exit 1
fi

# Export for current session
export CUDA_HOME
export CUDA_PATH="$CUDA_HOME"

# Update bashrc
sed -i '/export CUDA_HOME=/d' ~/.bashrc 2>/dev/null || true
sed -i '/export CUDA_PATH=/d' ~/.bashrc 2>/dev/null || true
echo "export CUDA_HOME=\"$CUDA_HOME\"" >> ~/.bashrc
echo "export CUDA_PATH=\"$CUDA_PATH\"" >> ~/.bashrc

echo ""
echo "CUDA_HOME set to: $CUDA_HOME"
echo ""
echo "Verifying:"
ls -la "$CUDA_HOME/include/cuda_fp16.h"

echo ""
echo "=========================================="
echo "FBPIC CUDA 13.0 setup complete (MPICH)!"
echo "=========================================="
echo ""
echo "For new shells, the environment is saved in ~/.bashrc"
python --version
python -c "import cupy; print(f'CuPy: {cupy.__version__}')"
python -c "import numba; print(f'Numba: {numba.__version__}')"
python -c "import fbpic; print(f'FBPIC: {fbpic.__version__} (patched)')"
echo ""
echo "Run with: python optimas_script.py"
echo "=========================================="
echo "✅ Done! Run your simulation now."
echo "=========================================="
echo ""
