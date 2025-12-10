#!/bin/bash
# Focused comparison script to identify differences between working and failing nodes
# Run this on BOTH nodes and save output

echo "=========================================="
echo "Node Environment Comparison"
echo "Hostname: $(hostname)"
echo "Date: $(date)"
echo "=========================================="

echo -e "\n### CUDA DRIVER & RUNTIME ###"
nvidia-smi --query-gpu=driver_version,name,compute_cap --format=csv,noheader
nvcc --version 2>&1 | grep "release"

echo -e "\n### PYTHON VERSION ###"
python --version
which python

echo -e "\n### CRITICAL PACKAGE VERSIONS ###"
python << 'EOF'
try:
    import cupy as cp
    print(f"CuPy: {cp.__version__}")
    print(f"  CUDA Runtime: {cp.cuda.runtime.runtimeGetVersion()}")
    print(f"  CUDA Driver: {cp.cuda.runtime.driverGetVersion()}")
except Exception as e:
    print(f"CuPy ERROR: {e}")

try:
    import numba
    print(f"Numba: {numba.__version__}")
except Exception as e:
    print(f"Numba ERROR: {e}")

try:
    from mpi4py import MPI
    print(f"mpi4py: {MPI.Get_version()}")
except Exception as e:
    print(f"mpi4py ERROR: {e}")

try:
    import fbpic
    print(f"FBPIC: {fbpic.__version__}")
except Exception as e:
    print(f"FBPIC ERROR: {e}")
EOF

echo -e "\n### CONDA PACKAGES (key ones) ###"
conda list | grep -E "(cupy|numba|fbpic|mpi4py|openmpi|ucx|cuda)"

echo -e "\n### UCX INFORMATION ###"
echo "UCX version:"
conda list | grep "^ucx "
echo -e "\nUCX CUDA support:"
ucx_info -v 2>&1 | grep -i version
ucx_info -d 2>&1 | grep -i cuda

echo -e "\n### OPENMPI BUILD INFO ###"
ompi_info --parsable | grep -E "(version|cuda|ucx)"

echo -e "\n### CRITICAL ENV VARS ###"
env | grep -E "(UCX_|OMPI_|CUDA_|FBPIC_|LD_LIBRARY)" | sort

echo -e "\n### LIBRARY PATHS FOR CUDA ###"
echo "libcuda.so.1:"
ldconfig -p | grep libcuda.so.1
echo -e "\nlibcudart.so:"
ldconfig -p | grep libcudart.so

echo -e "\n### MPI4PY LIBRARY DEPENDENCIES ###"
python -c "import mpi4py; import os; print(os.path.dirname(mpi4py.__file__))" | xargs -I {} find {} -name "*.so" | head -1 | xargs ldd | grep -E "(mpi|ucx|cuda)"

echo -e "\n=========================================="
echo "Comparison complete"
echo "=========================================="

