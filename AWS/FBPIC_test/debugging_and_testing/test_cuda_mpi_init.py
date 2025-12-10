#!/usr/bin/env python
"""
Test CUDA and MPI initialization order to diagnose segfault issues.
Run with: mpirun --allow-run-as-root -np 1 python test_cuda_mpi_init.py
"""

import sys

print("=" * 60)
print("Testing CUDA + MPI initialization order")
print("=" * 60)

# Test 1: CUDA first
print("\n[1/4] Testing CUDA alone...")
try:
    import cupy as cp
    device = cp.cuda.Device(0)
    device.use()
    print(f"✓ CuPy {cp.__version__} initialized successfully")
    print(f"  - GPU 0: {device.compute_capability}")
    print(f"  - CUDA Runtime: {cp.cuda.runtime.runtimeGetVersion()}")
except Exception as e:
    print(f"✗ CUDA failed: {e}")
    sys.exit(1)

# Test 2: MPI next
print("\n[2/4] Testing MPI initialization...")
try:
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()
    print(f"✓ MPI initialized: rank {rank}/{size}")
except Exception as e:
    print(f"✗ MPI failed: {e}")
    sys.exit(1)

# Test 3: FBPIC import
print("\n[3/4] Testing FBPIC import...")
try:
    from fbpic import __version__ as fbpic_version
    print(f"✓ FBPIC {fbpic_version} imported successfully")
except Exception as e:
    print(f"✗ FBPIC import failed: {e}")
    sys.exit(1)

# Test 4: Simple FBPIC simulation setup
print("\n[4/4] Testing minimal FBPIC simulation...")
try:
    from fbpic.main import Simulation
    sim = Simulation(
        Nz=100, zmax=0.e-6, zmin=-100.e-6, Nr=50, rmax=50.e-6, Nm=2, dt=1.e-17,
        use_cuda=True, n_order=-1
    )

    sim.step(10)

    print(f"✓ FBPIC simulation object created successfully")
    print(f"  - Grid: Nz={sim.fld.Nz}, Nr={sim.fld.Nr}, Nm={sim.fld.Nm}")
except Exception as e:
    print(f"✗ FBPIC simulation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ All tests passed! CUDA+MPI+FBPIC working correctly")
print("=" * 60)

