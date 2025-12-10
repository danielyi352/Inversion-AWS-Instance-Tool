#!/bin/bash
set -e

# Retry function for conda commands with exponential backoff
# Handles transient network errors (e.g., HTTP 503 from conda-forge)
# Retries up to 5 times with exponential backoff (10s, 20s, 40s, 80s, 160s)
# Usage: conda_retry <command> [args...]
conda_retry() {
    local max_attempts=5
    local attempt=1
    local delay=10
    local command="$1"
    shift
    local args=("$@")
    
    # Temporarily disable exit on error for this function
    set +e
    
    while [ $attempt -le $max_attempts ]; do
        echo "[Attempt $attempt/$max_attempts] Running: conda $command ${args[@]}"
        
        conda "$command" "${args[@]}"
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            echo "✓ Success on attempt $attempt"
            set -e  # Re-enable exit on error
            return 0
        else
            if [ $attempt -lt $max_attempts ]; then
                echo "✗ Failed with exit code $exit_code. Retrying in ${delay}s..."
                sleep $delay
                delay=$((delay * 2))  # Exponential backoff
                attempt=$((attempt + 1))
            else
                echo "✗ Failed after $max_attempts attempts. Exit code: $exit_code"
                set -e  # Re-enable exit on error
                return $exit_code
            fi
        fi
    done
    
    set -e  # Re-enable exit on error
    return 1
}

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
export UCX_TLS=shm,cuda_copy,cuda_ipc
export UCX_MEMTYPE_CACHE=n
export FBPIC_ENABLE_GPUDIRECT=0
export OMP_NUM_THREADS=1
export PYTHONPATH=/app
export MPICH_NO_GPU_DIRECT=1

# 4. Create environment with Python
echo "Creating cuda12_8 environment..."
conda create -n cuda12_8 -y
source /opt/conda/etc/profile.d/conda.sh
conda activate cuda12_8

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 5. Install basic packages
echo "Installing basic packages..."
conda install -y scipy h5py mkl

# 6. Install CUDA 12.8 packages with nvcc
echo "Installing CUDA 12.8 packages..."
conda_retry install -y -c conda-forge \
    numba-cuda \
    cuda-toolkit=12.8 \
    cuda-nvcc \
    cuda-nvrtc \
    cuda-tools \
    cuda-version=12.8

conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# 7. Install MPI and other packages
echo "Installing MPICH and mpi4py..."
conda_retry install -y -c conda-forge mpich mpi4py cupy numba

# 8. Install patched FBPIC (with inline=False fix)
echo "Installing patched FBPIC..."
cd /tmp
rm -rf fbpic
git clone -b inline_false https://github.com/delaossa/fbpic.git
cd fbpic
pip install -e .
cd /app

# 9. Install optimas and openpmd-viewer
echo "Installing optimas and openpmd-viewer..."
pip install 'optimas[all]'
conda_retry install -y -c conda-forge openpmd-viewer

# 10. Create /app/tmp directory
mkdir -p /app/tmp && chmod 1777 /app/tmp

echo ""
echo "=========================================="
echo "FBPIC CUDA 12.8 setup complete!"
echo "=========================================="
echo ""
echo "Environment: cuda12_8"
echo "To activate: source /opt/conda/etc/profile.d/conda.sh && conda activate cuda12_8"
echo ""
echo "Verifying installation:"
nvcc --version
echo ""
python -c "import cupy as cp; print(f'CuPy: {cp.__version__}')"
python -c "import numba; print(f'Numba: {numba.__version__}')"
python -c "import fbpic; print(f'FBPIC: {fbpic.__version__} (patched for CUDA 12.8)')"
echo "==========================================" 