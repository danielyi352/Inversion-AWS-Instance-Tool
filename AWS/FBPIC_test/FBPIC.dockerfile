FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04 AS base

# Install system dependencies and Miniconda
RUN apt-get update && \
    apt-get install -y wget git nano && \
    rm -rf /var/lib/apt/lists/* && \
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda clean -afy

ENV PATH="/opt/conda/bin:$PATH"

ENV OMPI_MCA_pml=ucx \
    OMPI_MCA_osc=ucx \
    OMPI_MCA_btl=^openib \
    UCX_TLS=shm,cuda_copy,cuda_ipc \
    UCX_MEMTYPE_CACHE=n \
    FBPIC_ENABLE_GPUDIRECT=1 \
    OMP_NUM_THREADS=1

# Set working directory
WORKDIR /app

# Install FBPIC dependencies and FBPIC in one layer
RUN conda update -n base -c defaults conda && \
    conda install -y -c conda-forge \
        numba \
        scipy \
        h5py \
        mkl \
        openmpi \
        mpi4py \
        cupy \
        cuda-version=12.8 \
        cuda-nvcc \
        cuda-nvrtc && \
    pip install --no-cache-dir fbpic && \
    conda clean -afy

# Create temporary directory within /app
RUN mkdir -p /app/tmp && chmod 1777 /app/tmp

# Set python path
ENV PYTHONPATH=/app

# Add metadata labels
LABEL maintainer="daniel@inversionsemi.com" \
      version="1.2.3" \
      description="FBPIC simulation environment"