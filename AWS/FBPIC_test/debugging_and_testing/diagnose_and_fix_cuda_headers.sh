#!/bin/bash
# Diagnose and fix missing CUDA headers issue

echo "=========================================="
echo "CUDA Headers Diagnostic & Fix"
echo "=========================================="

echo ""
echo "Step 1: Check Docker image type..."
if [ -f /.dockerenv ]; then
    echo "Running in Docker"
    # Check if CUDA devel tools exist
    if [ -f /usr/local/cuda/bin/nvcc ]; then
        echo "✓ Base image appears to be 'devel' (has /usr/local/cuda/bin/nvcc)"
    else
        echo "❌ Base image appears to be 'runtime' (missing /usr/local/cuda/bin/nvcc)"
        echo ""
        echo "ERROR: You MUST use nvidia/cuda:13.0.0-devel-ubuntu24.04 (not -runtime!)"
        echo ""
        echo "Recreate container with:"
        echo "  docker run -d --name NAME --gpus all nvidia/cuda:13.0.0-devel-ubuntu24.04 tail -f /dev/null"
        exit 1
    fi
fi

echo ""
echo "Step 2: Check for cuda_fp16.h in system..."
SYSTEM_CUDA_H=$(find /usr/local/cuda* -name "cuda_fp16.h" 2>/dev/null | head -1)
if [ -n "$SYSTEM_CUDA_H" ]; then
    echo "✓ Found in system: $SYSTEM_CUDA_H"
    SYSTEM_CUDA_DIR=$(dirname $(dirname $SYSTEM_CUDA_H))
    echo "  System CUDA: $SYSTEM_CUDA_DIR"
else
    echo "❌ Not found in /usr/local/cuda"
fi

echo ""
echo "Step 3: Check for cuda_fp16.h in conda..."
CONDA_CUDA_H=$(find /opt/conda -name "cuda_fp16.h" 2>/dev/null | head -1)
if [ -n "$CONDA_CUDA_H" ]; then
    echo "✓ Found in conda: $CONDA_CUDA_H"
    CONDA_CUDA_DIR=$(dirname $(dirname $CONDA_CUDA_H))
    echo "  Conda CUDA: $CONDA_CUDA_DIR"
else
    echo "❌ Not found in conda - need to install dev headers!"
    echo ""
    echo "Installing CUDA development headers..."
    conda install -y -c conda-forge -c nvidia \
        cuda-cudart-dev \
        cuda-driver-dev \
        cuda-nvrtc-dev
    
    # Check again
    CONDA_CUDA_H=$(find /opt/conda -name "cuda_fp16.h" 2>/dev/null | head -1)
    if [ -n "$CONDA_CUDA_H" ]; then
        echo "✓ Headers installed successfully"
        CONDA_CUDA_DIR=$(dirname $(dirname $CONDA_CUDA_H))
    else
        echo "❌ Installation failed!"
        exit 1
    fi
fi

echo ""
echo "Step 4: Check CUDA_HOME environment variable..."
if [ -n "$CUDA_HOME" ]; then
    echo "CUDA_HOME=$CUDA_HOME"
    if [ -f "$CUDA_HOME/include/cuda_fp16.h" ]; then
        echo "✓ CUDA_HOME points to valid CUDA installation"
    else
        echo "⚠️  CUDA_HOME set but cuda_fp16.h not found there"
    fi
else
    echo "❌ CUDA_HOME not set!"
fi

echo ""
echo "Step 5: Setting CUDA_HOME..."
# Prefer conda's CUDA if available, otherwise system
if [ -n "$CONDA_CUDA_DIR" ]; then
    export CUDA_HOME="$CONDA_CUDA_DIR"
    export CUDA_PATH="$CONDA_CUDA_DIR"
    echo "Set CUDA_HOME=$CUDA_HOME (conda)"
elif [ -n "$SYSTEM_CUDA_DIR" ]; then
    export CUDA_HOME="$SYSTEM_CUDA_DIR"
    export CUDA_PATH="$SYSTEM_CUDA_DIR"
    echo "Set CUDA_HOME=$CUDA_HOME (system)"
fi

# Add to bashrc for persistence
if ! grep -q "export CUDA_HOME=" ~/.bashrc 2>/dev/null; then
    echo "export CUDA_HOME=\"$CUDA_HOME\"" >> ~/.bashrc
    echo "export CUDA_PATH=\"$CUDA_PATH\"" >> ~/.bashrc
    echo "Added to ~/.bashrc for persistence"
fi

echo ""
echo "Step 6: Verify cuda_fp16.h is accessible..."
if [ -f "$CUDA_HOME/include/cuda_fp16.h" ]; then
    echo "✓ $CUDA_HOME/include/cuda_fp16.h exists"
else
    echo "❌ Still can't find cuda_fp16.h!"
    echo ""
    echo "All locations found:"
    find /usr/local /opt/conda -name "cuda_fp16.h" 2>/dev/null || echo "None found!"
    exit 1
fi

echo ""
echo "=========================================="
echo "Fix Complete!"
echo "=========================================="
echo ""
echo "CUDA_HOME is set to: $CUDA_HOME"
echo ""
echo "Test your simulation again:"
echo "  source ~/.bashrc  # Load new environment"
echo "  python your_script.py"
echo ""
echo "=========================================="

