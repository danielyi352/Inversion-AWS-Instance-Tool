#!/bin/bash
# FBPIC setup for CUDA 13.0 (H100 compatible)
# Based on Maxwell cluster recipe from FBPIC GitHub issue
#
# IMPORTANT: Use nvidia/cuda:13.0.0-devel-ubuntu24.04 (not -runtime!)
# CuPy needs CUDA headers for JIT compilation

set -e

echo "=========================================="
echo "FBPIC Setup for CUDA 13.0 (H100)"
echo "=========================================="
echo ""
echo "Based on Maxwell cluster fix for CUDA 13.0 compatibility"
echo ""
echo "NOTE: If using Docker, use nvidia/cuda:13.0.0-devel image"
echo "      (devel has headers, runtime doesn't)"
echo ""

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

# 3. Create environment with Python 3.11 (CRITICAL - not 3.13!)
echo "Creating Python 3.11 environment..."
conda create -n fbpic_env python=3.11 -y
source /opt/conda/etc/profile.d/conda.sh
conda activate fbpic_env

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 4. Install basic packages
echo "Installing basic packages..."
conda install -y scipy h5py mkl

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 5. Install CUDA 13 specific packages (THE CRUCIAL BITS)
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

# 6. Install nvidia_nvjitlink for CUDA 13 (CRITICAL)
echo "Installing nvidia_nvjitlink..."
pip install 'nvidia_nvjitlink>13.0'

# 7. Install CuPy for CUDA 13 (NOT regular cupy!)
echo "Installing cupy-cuda13x..."
pip install cupy-cuda13x

# 8. Install MPI packages
echo "Installing OpenMPI and mpi4py..."
# Install full OpenMPI (not external placeholder) and mpi4py together
conda install -y -c conda-forge openmpi=5.0.8 mpi4py

# 9. Install patched FBPIC (with inline=False fix)
echo "Installing patched FBPIC..."
cd /tmp
rm -rf fbpic
git clone -b inline_false https://github.com/delaossa/fbpic.git
cd fbpic
pip install -e .
cd /app

# 10. Install openpmd-viewer (optional, skip optimas)
echo "Installing openpmd-viewer..."
conda install -y -c conda-forge openpmd-viewer

# 11. Set environment variables
export OMP_NUM_THREADS=1
export PYTHONPATH=/app
export LD_LIBRARY_PATH="/opt/conda/envs/fbpic_env/lib:${LD_LIBRARY_PATH}"
# Point CuPy to conda's CUDA headers (CRITICAL for JIT compilation!)
export CUDA_HOME="/opt/conda/envs/fbpic_env/targets/x86_64-linux"
export CUDA_PATH="/opt/conda/envs/fbpic_env/targets/x86_64-linux"

# 12. Create /app/tmp directory
mkdir -p /app/tmp && chmod 1777 /app/tmp

echo ""
echo "=========================================="
echo "FBPIC CUDA 13.0 setup complete!"
echo "=========================================="
echo ""
echo "Environment: fbpic_env (Python 3.11)"
echo ""
echo "Key packages installed:"
python --version
python -c "import cupy; print(f'  CuPy: {cupy.__version__}')"
python -c "import numba; print(f'  Numba: {numba.__version__}')"
python -c "import fbpic; print(f'  FBPIC: {fbpic.__version__} (patched for CUDA 13)')"
python -c "from mpi4py import MPI; print(f'  mpi4py: {MPI.Get_version()}')"
echo ""
echo "To activate environment:"
echo "  conda activate fbpic_env"
echo ""
echo "To run simulations:"
echo "  mpirun -np 4 python your_script.py"
echo "=========================================="

