#!/usr/bin/env python3
"""
Test script to verify GPU binding for MPI ranks.
This helps diagnose if the MPI configuration is working correctly.
"""

import os
from mpi4py import MPI

try:
    import cupy as cp

    CUPY_AVAILABLE = True
except ImportError:
    print("CuPy not available")
    CUPY_AVAILABLE = False


def test_gpu_binding():
    """Test that each MPI rank is bound to a different GPU."""

    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    print(f"Rank {rank}/{size}: Starting GPU binding test")

    if not CUPY_AVAILABLE:
        print(f"Rank {rank}: CuPy not available, skipping GPU test")
        return

    # Get local rank information
    local_rank_env = (
        os.environ.get("OMPI_COMM_WORLD_LOCAL_RANK")
        or os.environ.get("MPI_LOCALRANKID")
        or os.environ.get("MV2_COMM_WORLD_LOCAL_RANK")
    )

    print(f"Rank {rank}: Local rank env = {local_rank_env}")

    # Get number of GPUs
    n_gpu = cp.cuda.runtime.getDeviceCount()
    print(f"Rank {rank}: Found {n_gpu} GPUs")

    # Determine GPU ID
    if local_rank_env is not None:
        gpu_id = int(local_rank_env)
        print(f"Rank {rank}: Using local rank for GPU binding: GPU {gpu_id}")
    else:
        gpu_id = rank % n_gpu
        print(f"Rank {rank}: Using fallback GPU binding: GPU {gpu_id}")

    # Bind to GPU
    cp.cuda.Device(gpu_id).use()

    # Verify we're on the correct GPU
    current_device = cp.cuda.Device()
    print(f"Rank {rank}: Successfully bound to GPU {current_device.id}")

    # Test GPU memory allocation
    try:
        test_array = cp.zeros((1000, 1000), dtype=cp.float32)
        print(f"Rank {rank}: Successfully allocated memory on GPU {current_device.id}")
        del test_array
    except Exception as e:
        print(f"Rank {rank}: Error allocating memory: {e}")

    # Synchronize all ranks
    comm.Barrier()

    if rank == 0:
        print("\n=== GPU Binding Test Summary ===")
        print(f"Total MPI ranks: {size}")
        print(f"Total GPUs available: {n_gpu}")
        print("Each rank should be bound to a different GPU")
        print("Check the output above to verify correct binding\n")


if __name__ == "__main__":
    test_gpu_binding()
