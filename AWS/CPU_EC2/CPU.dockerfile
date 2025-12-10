# Base image: lightweight Ubuntu 24.04
FROM ubuntu:24.04 AS base

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
        wget \
        git \
        nano \
        vim \
        libopenmpi-dev \
        openmpi-bin \
        tmux \
        screen && \
    rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh && \
    bash miniconda.sh -b -p /opt/conda && \
    rm miniconda.sh && \
    /opt/conda/bin/conda clean -afy

ENV PATH="/opt/conda/bin:$PATH"

# Auto-accept Anaconda TOS
ENV CONDA_PLUGINS_AUTO_ACCEPT_TOS=true

WORKDIR /app

# Install required conda packages including MPI builds of Genesis
RUN conda update -n base -c defaults conda && \
    conda install -y -c conda-forge \
        numpy \
        h5py \
        scipy \
        "genesis2=*=mpi_openmpi*" \
        "genesis4=*=mpi_openmpi*" \
        lume-genesis \
        openpmd-beamphysics && \
    conda clean -afy

# Create world-writable tmp dir
RUN mkdir -p /app/tmp && chmod 1777 /app/tmp

# MPI stability environment
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
ENV OMP_NUM_THREADS=1
ENV OMPI_MCA_btl=self,tcp

# Set PYTHONPATH
ENV PYTHONPATH="/app"

# Metadata labels
LABEL maintainer="daniel@inversionsemi.com" \
      version="0.5.0" \
      description="CPU simulation environment with MPI support"