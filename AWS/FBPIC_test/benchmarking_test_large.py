"""
FBPIC large-scale benchmarking simulation script.

This script runs a larger laser-wakefield acceleration simulation using FBPIC,
designed to better demonstrate multi-GPU performance scaling.
Includes MPI and multi-GPU support. Uses neutral Helium laser-ionization.

Typical usage:
    mpirun -n N python benchmarking_test_large.py

This version uses larger grid sizes to better utilize multiple GPUs.
"""

from typing import Callable
import numpy as np
from scipy.constants import c, e, m_e, m_p, pi

# Import the relevant structures from fbpic
from fbpic.main import Simulation
from fbpic.utils.random_seed import set_random_seed
from fbpic.lpa_utils.laser import add_laser_pulse
from fbpic.lpa_utils.laser.laser_profiles import GaussianLaser
from fbpic.openpmd_diag import (
    FieldDiagnostic,
    ParticleDiagnostic,
    ParticleChargeDensityDiagnostic,
    set_periodic_checkpoint,
    restart_from_checkpoint,
)

import sys
import time
from mpi4py import MPI
import os

LOG_TO_FILE = True
USE_CUDA = True

if LOG_TO_FILE:
    sys.stdout = open("output_large.log", "w")
    sys.stderr = open("error_large.log", "w")

# --------------------------------------------------------------------------
# MPI / GPU selection
# --------------------------------------------------------------------------

try:
    import cupy as cp
except ImportError:
    print("Module 'cupy' not available, will not run mpi")
    cp = None

if cp is not None:
    comm = MPI.COMM_WORLD
    world_rank = comm.Get_rank()

    # Detect the per-node rank if provided by the MPI runtime
    local_rank_env = (
        os.environ.get("OMPI_COMM_WORLD_LOCAL_RANK")
        or os.environ.get("MPI_LOCALRANKID")  # Intel MPI / MPICH
        or os.environ.get("MV2_COMM_WORLD_LOCAL_RANK")
    )

    if local_rank_env is not None:
        gpu_id = int(local_rank_env)
    else:
        # Fallback that also works in single-node tests
        n_gpu = cp.cuda.runtime.getDeviceCount()
        gpu_id = world_rank % n_gpu

    # Bind the rank to its GPU
    cp.cuda.Device(gpu_id).use()

    # Optional: only the master rank prints banner information
    if world_rank == 0:
        from fbpic import __version__ as fbpic_version

        print(
            f"FBPIC {fbpic_version} running with {comm.Get_size()} MPI ranks on {n_gpu if 'n_gpu' in locals() else 'unknown'} GPUs per node."
        )


def build_piecewise_linear_downramp(
    upramp_length: float,
    downramp_start_position: float,
    downramp_length: float,
    downramp_height_ratio: float,
    plataeu_end_position: float,
    plataeu_downramp_length: float,
) -> Callable:
    """
    Returns a callable for a density profile in z, uniform in r.
    """

    def dens_func(z, r):
        """
        Returns relative density at position z and r.
        """
        z = np.asarray(z)
        r = np.asarray(r)
        dens = np.zeros_like(z, dtype=float)
        # Linear upramp
        mask1 = (z >= 0) & (z < upramp_length)
        dens[mask1] = (z[mask1] - 0) / upramp_length
        # Plateau at 1
        mask2 = (z >= upramp_length) & (z < downramp_start_position)
        dens[mask2] = 1.0
        # Linear downramp from 1 to n0
        mask3 = (z >= downramp_start_position) & (
            z < downramp_start_position + downramp_length
        )
        dens[mask3] = (
            1.0
            + (downramp_height_ratio - 1.0)
            * (z[mask3] - downramp_start_position)
            / downramp_length
        )
        # Plateau at n0
        mask4 = (z >= downramp_start_position + downramp_length) & (
            z < plataeu_end_position
        )
        dens[mask4] = downramp_height_ratio
        # Linear downramp from n0 to 0
        mask5 = (z >= plataeu_end_position) & (
            z < plataeu_end_position + plataeu_downramp_length
        )
        dens[mask5] = downramp_height_ratio * (
            1 - (z[mask5] - plataeu_end_position) / plataeu_downramp_length
        )
        # Elsewhere, dens is 0
        return dens

    return dens_func


# ----------
# Parameters - LARGER GRID FOR BETTER MULTI-GPU SCALING
# ----------

# Whether to use the GPU
use_cuda: bool = USE_CUDA

# Order of the stencil for z derivatives in the Maxwell solver.
# Use -1 for infinite order, i.e. for exact dispersion relation in
# all direction (adviced for single-GPU/single-CPU simulation).
# Use a positive number (and multiple of 2) for a finite-order stencil
# (required for multi-GPU/multi-CPU with MPI). A large `n_order` leads
# to more overhead in MPI communications, but also to a more accurate
# dispersion relation for electromagnetic waves. (Typically,
# `n_order = 32` is a good trade-off.)
# See https://arxiv.org/abs/1611.05712 for more information.
n_order: int = 32

# The simulation box - MUCH LARGER FOR BETTER SCALING
Nz: int = 8000  # Number of gridpoints along z (4x larger)
zmax: float = 50.0e-6  # Right end of the simulation box (meters)
zmin: float = -50.0e-6  # Left end of the simulation box (meters)
Nr: int = 2000  # Number of gridpoints along r (4x larger)
rmax: float = 50.0e-6  # Length of the box along r (meters)
Nm: int = 2  # Number of modes used

# The simulation timestep
dt: float = (zmax - zmin) / Nz / c  # Timestep (seconds)

# The particles
p_zmin: float = 0.0e-6  # Position of the beginning of the plasma (meters)
p_zmax: float = 4.0e-3  # Position of the end of the plasma (meters)
p_rmax: float = 130.0e-6  # Maximal radial position of the plasma (meters)
n_gas: float = 4.0e18 * 1.0e6  # Density (electrons.meters^-3)
p_nz: int = 2  # Number of particles per cell along z
p_nr: int = 2  # Number of particles per cell along r
p_nt: int = 4  # Number of particles per cell along theta

# The laser
laser_energy: float = 2.5  # J
tau: float = 38.0e-15  # Laser duration
w0: float = 17.0e-6  # Laser waist
peak_intensity: float = (
    2 / pi * laser_energy / (tau * (w0 * 100) ** 2)
)  # Peak intensity, W/cm2
wavelength: float = 0.800  # um
a0: float = np.sqrt(
    7.3e-19 * wavelength**2 * peak_intensity
)  # Works out to 2.6 for HTU
z0: float = -30.0e-6  # Laser centroid
z_foc: float = 2.0e-3  # Focal position

# The moving window
v_window: float = c  # Speed of the window

# The diagnostics and the checkpoints/restarts
diag_period: int = 1000  # Period of the diagnostics in number of timesteps
save_checkpoints: bool = False  # Whether to write checkpoint files
checkpoint_period: int = 100  # Period for writing the checkpoints
use_restart: bool = False  # Whether to restart from a previous checkpoint
track_electrons: bool = False  # Whether to track and write particle ids

# The density profile
upramp_len = 10e-6
downramp_pos = 15e-6
downramp_len = 5 - 6
downramp_height = 0.5
plateau_end_pos = 20e-6
plateau_downramp_len = 10e-6
density = build_piecewise_linear_downramp(
    upramp_length=upramp_len,
    downramp_start_position=downramp_pos,
    downramp_length=downramp_len,
    downramp_height_ratio=downramp_height,
    plataeu_end_position=plateau_end_pos,
    plataeu_downramp_length=plateau_downramp_len,
)

# The interaction length of the simulation (meters)
L_interact: float = (
    plateau_end_pos + plateau_downramp_len
)  # increase to simulate longer distance!
# Interaction time (seconds) (to calculate number of PIC iterations)
T_interact: float = (L_interact + (zmax - zmin)) / v_window


def setup_simulation() -> Simulation:
    """
    Sets up and configures the FBPIC simulation.

    Returns:
        Simulation: A configured Simulation object ready to run.
    """
    # Set the random seed
    set_random_seed(0)
    # Initialize the simulation object
    sim = Simulation(
        Nz,
        zmax,
        Nr,
        rmax,
        Nm,
        dt,
        zmin=zmin,
        n_order=n_order,
        use_cuda=use_cuda,
        boundaries={"z": "open", "r": "reflective"},
    )
    # 'r': 'open' can also be used, but is more computationally expensive
    # Add the Helium ions (pre-ionized up to level 1),
    # the Nitrogen ions (pre-ionized up to level 5)
    # and the associated electrons (from the pre-ionized levels)
    atoms_He = sim.add_new_species(
        q=0,
        m=4.0 * m_p,
        n=n_gas,
        dens_func=density,
        p_nz=p_nz,
        p_nr=p_nr,
        p_nt=p_nt,
        p_zmin=p_zmin,
    )
    # Activate ionization of He ions (for levels above 1).
    # Store the created electrons in the species `elec`
    elec = sim.add_new_species(q=-e, m=m_e)
    atoms_He.make_ionizable("He", target_species=elec, level_start=0)
    # Load initial fields
    # Create a Gaussian laser profile
    laser_profile = GaussianLaser(a0, w0, tau, z0, zf=z_foc)
    # Add the laser to the fields of the simulation
    add_laser_pulse(sim, laser_profile)
    if not use_restart:
        # Track electrons if required (species 0 correspond to the electrons)
        if track_electrons:
            elec.track(sim.comm)
    else:
        # Load the fields and particles from the latest checkpoint file
        restart_from_checkpoint(sim)
    # Configure the moving window
    sim.set_moving_window(v=v_window)
    # Add diagnostics
    sim.diags = [
        FieldDiagnostic(diag_period, sim.fld, comm=sim.comm),
        ParticleDiagnostic(
            diag_period,
            {"electrons": elec},
            comm=sim.comm,
        ),
        ParticleChargeDensityDiagnostic(diag_period, sim, {"electrons": elec}),
    ]
    # Add checkpoints
    if save_checkpoints:
        set_periodic_checkpoint(sim, checkpoint_period)
    return sim


if __name__ == "__main__":
    # Set up the simulation
    sim = setup_simulation()

    # Number of iterations to perform
    N_step = 100
    print(f" -Number of steps: {N_step}")
    print(f" -Grid size: {Nz} x {Nr} = {Nz*Nr:,} total grid points")
    print(f" -MPI ranks: {MPI.COMM_WORLD.Get_size()}")

    # Run the simulation
    start_time = time.time()
    sim.step(N_step, show_progress=not LOG_TO_FILE)
    print(f" -Finished in {(time.time() - start_time) / 60} min")
    print("")
