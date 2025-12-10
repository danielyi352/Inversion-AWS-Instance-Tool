#!/bin/bash
set -e

# 1. Install system dependencies
apt-get update
apt-get install -y wget git nano
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
export OMPI_MCA_pml=ucx
export OMPI_MCA_osc=ucx
export OMPI_MCA_btl=^openib
export UCX_TLS=shm,cuda_copy,cuda_ipc
export UCX_MEMTYPE_CACHE=n
export FBPIC_ENABLE_GPUDIRECT=1
export OMP_NUM_THREADS=1
export PYTHONPATH=/app

# 4. Create environment with Python
echo "Creating cuda12_8_openmpi environment..."
conda create -n cuda12_8_openmpi -y
source /opt/conda/etc/profile.d/conda.sh
conda activate cuda12_8_openmpi

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 6. Install CUDA 12.8 packages with nvcc
echo "Installing CUDA 12.8 packages..."
conda install -y -c conda-forge \
    numba \
    scipy \
    h5py \
    mkl \
    openmpi \
    mpi4py \
    cupy \
    cuda-version=12.8 \
    cuda-toolkit=12.8 \
    cuda-nvcc \
    cuda-nvrtc
conda clean -afy

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 8. Install patched FBPIC (with inline=False fix)
echo "Installing patched FBPIC..."
cd /tmp
rm -rf fbpic
git clone -b inline_false https://github.com/delaossa/fbpic.git
cd fbpic
pip install -e .
cd /app

# 9. Create /app/tmp directory
mkdir -p /app/tmp && chmod 1777 /app/tmp

echo ""
echo "=========================================="
echo "FBPIC CUDA 12.8 setup complete!"
echo "=========================================="
echo ""
echo "Environment: cuda12_8_openmpi"
echo "To activate: source /opt/conda/etc/profile.d/conda.sh && conda activate cuda12_8_openmpi"
echo "Important: After activation, ensure PATH includes the conda environment bin:"
echo "  export PATH=\"/opt/conda/envs/cuda12_8_openmpi/bin:\$PATH\""
echo ""
echo "Verifying installation:"
nvcc --version
echo ""
python -c "import cupy as cp; print(f'CuPy: {cp.__version__}')"
python -c "import numba; print(f'Numba: {numba.__version__}')"
python -c "import fbpic; print(f'FBPIC: {fbpic.__version__} (patched for CUDA 12.8)')"
echo ""
echo "Verifying MPI:"
mpirun --version | head -1
python -c "from mpi4py import MPI; print(f'mpi4py: MPI version {MPI.Get_version()[0]}.{MPI.Get_version()[1]}')"
echo "==========================================" 