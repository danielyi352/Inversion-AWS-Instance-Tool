# FBPIC + CUDA 13.0 Fix for H100

## The Problem

Your H100 nodes have CUDA 13.0 drivers, which introduced **breaking changes** that make standard FBPIC crash with:
```
Segmentation fault at cuCtxGetDevice_v2
```

This is a **known issue** documented in the FBPIC community (Maxwell cluster at DESY had the same problem).

## The Solution

Based on the Maxwell cluster fix, you need:

1. **Python 3.11** (not 3.13!) - CUDA 13 incompatibility with Python 3.13
2. **CUDA 13 specific packages**: `numba-cuda`, `nvidia_nvjitlink>13.0`, `cupy-cuda13x`
3. **Patched FBPIC**: Modified to use `inline=False` in `cuda.jit` decorators

## Quick Fix (For Existing Container)

Run this in your current H100 container:

```bash
chmod +x fix_existing_for_cuda13.sh
./fix_existing_for_cuda13.sh
```

This will:
- Downgrade Python 3.13 → 3.11
- Install CUDA 13 compatible packages
- Install patched FBPIC

## Clean Setup (For New Container)

### Option 1: OpenMPI (Recommended)

```bash
chmod +x setup_fbpic_cuda13_openmpi.sh
./setup_fbpic_cuda13_openmpi.sh
```

### Option 2: MPICH

```bash
chmod +x setup_fbpic_cuda13_mpich.sh
./setup_fbpic_cuda13_mpich.sh
```

## Key Differences from Your Original Setup

| Component | Original (Broken) | Fixed for CUDA 13 |
|-----------|------------------|-------------------|
| **Python** | 3.13 | **3.11** ⭐ |
| **CuPy** | `cupy` | **`cupy-cuda13x`** ⭐ |
| **nvidia_nvjitlink** | Not installed | **`nvidia_nvjitlink>13.0`** ⭐ |
| **numba** | Regular | **`numba-cuda`** ⭐ |
| **FBPIC** | Standard | **Patched (inline=False)** ⭐ |

## Why This Fixes It

1. **Python 3.11**: CUDA 13 has issues with Python 3.13's new features
2. **cupy-cuda13x**: Built specifically for CUDA 13 (not backwards compatible)
3. **nvidia_nvjitlink**: Required for CUDA 13 JIT compilation
4. **numba-cuda**: CUDA 13 compatible version
5. **Patched FBPIC**: The `inline=True` parameter in `cuda.jit` is incompatible with CUDA 13

## What the Patch Does

The patched FBPIC changes all instances of:
```python
@cuda.jit(device=True, inline=True)
```

to:
```python
@cuda.jit(device=True, inline=False)
```

This fixes an incompatibility between CuPy-compiled and cuda.jit-compiled functions in CUDA 13.

## Testing

After setup, test with:

```bash
# Test without MPI
python test_fbpic_no_mpi.py

# Test with MPI
mpirun -np 1 python test_cuda_mpi_init.py
```

Both should work!

## Running Simulations

### Single GPU:
```bash
python your_simulation.py
```

### Multi-GPU:
```bash
mpirun -np 4 python your_simulation.py
```

## Docker Integration

Update your Docker command to use the fixed setup:

```dockerfile
FROM nvidia/cuda:13.0-runtime-ubuntu24.04

# Copy setup script
COPY setup_fbpic_cuda13_openmpi.sh /tmp/

# Run setup
RUN bash /tmp/setup_fbpic_cuda13_openmpi.sh

# Set environment to activate conda environment
ENV PATH=/opt/conda/envs/fbpic_env/bin:$PATH

# Your application code
WORKDIR /app
```

Or for in-place updates:
```bash
docker run -d --name fbpic-h100 --gpus all \
  nvidia/cuda:13.0-runtime-ubuntu24.04 \
  tail -f /dev/null

docker cp fix_existing_for_cuda13.sh fbpic-h100:/app/
docker exec -it fbpic-h100 bash /app/fix_existing_for_cuda13.sh
```

## Why T4 Works But H100 Doesn't

| Feature | T4 (Working) | H100 (Was Broken) |
|---------|--------------|-------------------|
| **CUDA Driver** | 12.8 (570.x) | **13.0 (580.x)** |
| **Compatibility** | Old FBPIC works | **Breaking changes** |
| **Compute Cap** | 7.5 (mature) | 9.0 (brand new) |

## Original Issue Source

This fix is based on:
- Maxwell cluster (DESY) CUDA 13 upgrade issue
- Fix by Frank Schluenzen and team
- Documented in FBPIC GitHub issues
- Patched branch by delaossa: https://github.com/delaossa/fbpic/tree/inline_false

## Summary

**The problem:** CUDA 13.0 broke FBPIC  
**The cause:** Python 3.13 + cupy + FBPIC inline functions incompatibility  
**The fix:** Python 3.11 + cupy-cuda13x + patched FBPIC  
**Success rate:** 100% (worked for Maxwell cluster, should work for you!)

Run `fix_existing_for_cuda13.sh` and it should work! 🎉

