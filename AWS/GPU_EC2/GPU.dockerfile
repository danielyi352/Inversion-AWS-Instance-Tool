FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04 AS base

# Install system dependencies and Miniconda
RUN apt-get update && \
    apt-get install -y wget bzip2 git vim-tiny nano && \
    rm -rf /var/lib/apt/lists/* && \
    wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda clean -afy

ENV PATH="/opt/conda/bin:$PATH"

# Configure conda: disable auto-activation, add conda-forge, set strict priority
RUN conda config --set auto_activate_base false && \
    conda config --add channels conda-forge && \
    conda config --set channel_priority strict

# Install mamba for faster dependency solving
RUN conda install -y -c conda-forge mamba python=3.11

# Install FBPIC dependencies, FBPIC, Wake-T, and WarpX in one layer using mamba
RUN mamba install -y -c conda-forge \
        numba \
        scipy \
        h5py \
        mkl \
        mpi4py \
        pyfftw && \
    pip install --no-cache-dir fbpic && \
    pip install --no-cache-dir cupy-cuda12x && \
    mamba create -n warpx -c conda-forge warpx && \
    conda run -n warpx pip install Wake-T && \
    pip install --no-cache-dir cheetah-accelerator && \
    conda clean -afy

# Create a world-writable temporary directory
RUN mkdir -p /app/tmp && chmod 1777 /app/tmp

# Set working directory
WORKDIR /app

# Set PYTHONPATH
ENV PYTHONPATH="/app"

# Metadata labels
LABEL maintainer="daniel@inversionsemi.com" \
      version="0.2.0" \
      description="GPU simulation environment"
