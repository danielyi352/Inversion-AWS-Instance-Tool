#!/bin/bash

# Optimized FBPIC launch script for better multi-GPU performance
# This version uses optimized MPI settings for H100 GPUs

# Get number of GPUs
NUM_GPUS=$(nvidia-smi --list-gpus | wc -l)
echo "Detected $NUM_GPUS GPUs"

# Check if script provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <python_script.py>"
    echo "Example: $0 benchmarking_test_large.py"
    exit 1
fi

PYTHON_SCRIPT=$1

echo "Launching FBPIC with $NUM_GPUS MPI ranks (optimized settings)"
echo "Script: $PYTHON_SCRIPT"

# Launch with optimized MPI settings for H100
mpirun --allow-run-as-root \
       -np $NUM_GPUS \
       --bind-to none \
       --map-by slot \
       --mca btl_base_warn_component_unused 0 \
       --mca btl ^openib \
       --mca pml ucx \
       --mca osc ucx \
       --mca coll ^hcoll \
       -x CUDA_DEVICE_ORDER=PCI_BUS_ID \
       -x OMPI_MCA_pml=ucx \
       -x OMPI_MCA_osc=ucx \
       -x OMPI_MCA_btl=^openib \
       -x UCX_TLS=shm,cuda_copy,cuda_ipc \
       -x UCX_MEMTYPE_CACHE=n \
       -x UCX_NET_DEVICES=mlx5_0:1 \
       -x FBPIC_ENABLE_GPUDIRECT=1 \
       -x OMP_NUM_THREADS=1 \
       -x CUDA_LAUNCH_BLOCKING=0 \
       python $PYTHON_SCRIPT 