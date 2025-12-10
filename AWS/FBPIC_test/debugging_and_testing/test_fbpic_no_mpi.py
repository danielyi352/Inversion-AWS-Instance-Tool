#!/usr/bin/env python
"""
Test FBPIC without MPI - for single GPU only
Many FBPIC simulations don't need MPI if running on one GPU
"""

import sys

print("=" * 70)
print("Testing FBPIC WITHOUT MPI (single GPU)")
print("=" * 70)

# Test 1: Import FBPIC without importing mpi4py
print("\n[1/5] Importing FBPIC (no MPI import)...")
try:
    from fbpic.main import Simulation
    import cupy as cp
    print(f"✓ FBPIC imported successfully")
    print(f"  CuPy: {cp.__version__}")
except Exception as e:
    print(f"✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Create simulation
print("\n[2/5] Creating simulation...")
try:
    sim = Simulation(
        Nz=100, zmax=0.e-6, zmin=-100.e-6,
        Nr=50, rmax=50.e-6,
        Nm=2, dt=1.e-17,
        use_cuda=True, n_order=-1
    )
    print(f"✓ Simulation created")
    print(f"  Grid: Nz={sim.fld.Nz}, Nr={sim.fld.Nr}, Nm={sim.fld.Nm}")
except Exception as e:
    print(f"✗ Simulation creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Run a few steps (THIS IS WHERE IT USUALLY CRASHES)
print("\n[3/5] Running 10 simulation steps...")
try:
    sim.step(10)
    print(f"✓ 10 steps completed successfully!")
except Exception as e:
    print(f"✗ sim.step() failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Add a particle beam
print("\n[4/5] Adding particle beam...")
try:
    from fbpic.lpa_utils.bunch import add_particle_bunch
    add_particle_bunch(
        sim, 1.e-9, -10.e-6, 0., 0., 3.e-6, 3.e-6,
        1.e7, 1.e7, 1.
    )
    print(f"✓ Particle bunch added")
except Exception as e:
    print(f"✗ Adding particles failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Run more steps with particles
print("\n[5/5] Running 10 more steps with particles...")
try:
    sim.step(10)
    print(f"✓ 10 more steps completed!")
except Exception as e:
    print(f"✗ Steps with particles failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("✓✓✓ ALL TESTS PASSED!")
print("=" * 70)
print("")
print("FBPIC works WITHOUT MPI on single GPU!")
print("")
print("For single-GPU simulations, you don't need MPI at all.")
print("Just run: python your_simulation.py")
print("=" * 70)

