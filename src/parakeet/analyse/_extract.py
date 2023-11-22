#
# parakeet.analyse.extract.py
#
# Copyright (C) 2019 Diamond Light Source and Rosalind Franklin Institute
#
# Author: James Parkhurst
#
# This code is distributed under the GPLv3 license, a copy of
# which is included in the root directory of this package.
#
import concurrent.futures
import numpy as np
import mrcfile
import random
import h5py
import parakeet.sample
from functools import singledispatch
from math import sqrt, ceil
from parakeet.analyse._average_particles import lazy_map
from parakeet.analyse._average_particles import _process_sub_tomo
from parakeet.analyse._average_particles import _iterate_particles


__all__ = ["extract", "average_extracted_particles"]


# Set the random seed
random.seed(0)


@singledispatch
def extract(
    config_file,
    sample_file: str,
    rec_file: str,
    particles_file: str,
    particle_size: int,
):
    """
    Perform sub tomogram extraction

    Args:
        config_file: The input config filename
        sample_file: The sample filename
        rec_file: The reconstruction filename
        particles_file: The file to extract the particles to
        particle_size: The particle size (px)

    """

    # Load the full configuration
    config = parakeet.config.load(config_file)

    # Print some options
    parakeet.config.show(config)

    # Load the sample
    sample = parakeet.sample.load(sample_file)

    # Do the sub tomogram averaging
    _extract_Config(config, sample, rec_file, particles_file, particle_size)


@extract.register(parakeet.config.Config)
def _extract_Config(
    config: parakeet.config.Config,
    sample: parakeet.sample.Sample,
    rec_filename: str,
    extract_file: str,
    particle_size: int = 0,
):
    """
    Extract particles for post-processing

    """

    # Get the scan config
    # scan = config.dict()

    # Get the sample centre
    centre = np.array(sample.centre)

    # Read the reconstruction file
    tomo_file = mrcfile.mmap(rec_filename)
    tomogram = tomo_file.data

    # Get the size of the volume
    voxel_size = np.array(
        (
            tomo_file.voxel_size["x"],
            tomo_file.voxel_size["y"],
            tomo_file.voxel_size["z"],
        )
    )
    assert voxel_size[0] > 0
    assert voxel_size[0] == voxel_size[1]
    assert voxel_size[0] == voxel_size[2]
    size = np.array(tomogram.shape)[[2, 0, 1]] * voxel_size

    # Loop through the
    assert sample.number_of_molecules == 1
    for name, (atoms, positions, orientations) in sample.iter_molecules():
        # Compute the box size based on the size of the particle so that any
        # orientation should fit within the box
        xmin = atoms.data["x"].min()
        xmax = atoms.data["x"].max()
        ymin = atoms.data["y"].min()
        ymax = atoms.data["y"].max()
        zmin = atoms.data["z"].min()
        zmax = atoms.data["z"].max()
        xc = (xmax + xmin) / 2.0
        yc = (ymax + ymin) / 2.0
        zc = (zmax + zmin) / 2.0

        if particle_size == 0:
            half_length = (
                int(
                    ceil(
                        sqrt(
                            ((xmin - xc) / voxel_size[0]) ** 2
                            + ((ymin - yc) / voxel_size[1]) ** 2
                            + ((zmin - zc) / voxel_size[2]) ** 2
                        )
                    )
                )
                + 1
            )
        else:
            half_length = particle_size // 2
        length = 2 * half_length
        assert len(positions) == len(orientations)
        num_particles = len(positions)
        print(
            "Extracting %d %s particles with box size %d"
            % (num_particles, name, length)
        )

        # Create the average array
        shape = (length, length, length)
        num = 0

        # Sort the positions and orientations by y
        positions, orientations = zip(
            *sorted(zip(positions, orientations), key=lambda x: x[0][1])
        )

        # Get the random indices
        indices = [list(range(len(positions)))]

        # Create a file to store particles
        handle = h5py.File(extract_file, "w")
        handle["voxel_size"] = voxel_size
        data_handle = handle.create_dataset(
            "data", (0,) + shape, maxshape=(None,) + shape
        )

        # Loop through all the particles
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            for half_index, data in lazy_map(
                executor,
                _process_sub_tomo,
                _iterate_particles(
                    indices,
                    positions,
                    orientations,
                    centre,
                    size,
                    half_length,
                    shape,
                    voxel_size,
                    tomogram,
                ),
            ):
                # Add the particle to the file
                data_handle.resize(num + 1, axis=0)
                data_handle[num, :, :, :] = data
                num += 1
                print("Count: ", num)


def average_extracted_particles(
    particles_filename: str,
    half1_filename: str,
    half2_filename: str,
    num_particles: int = 0,
):
    """
    Average the extracted particles

    """

    # Open the particles file
    handle = h5py.File(particles_filename, "r")
    data = handle["data"]
    voxel_size = tuple(handle["voxel_size"][:])
    print("Voxel size: %s" % str(voxel_size))

    # Get the number of particles
    if num_particles is None or num_particles <= 0:
        num_particles = data.shape[0]
    half_num_particles = num_particles // 2
    assert half_num_particles > 0
    assert num_particles <= data.shape[0]

    # Setup the arrays
    half = np.zeros((2,) + data.shape[1:], dtype="float32")
    num = np.zeros(2)

    # Get the random indices
    indices = list(
        np.random.choice(range(data.shape[0]), size=num_particles, replace=False)
    )
    indices = [indices[:half_num_particles], indices[half_num_particles:]]

    # Average the particles
    print("Summing particles")
    for half_index, particle_indices in enumerate(indices):
        for i, particle_index in enumerate(particle_indices):
            print(
                "Half %d: adding %d / %d"
                % (half_index + 1, i + 1, len(particle_indices))
            )
            half[half_index, :, :, :] += data[particle_index, :, :, :]
            num[half_index] += 1

    # Average the sub tomograms
    print("Averaging half 1 with %d particles" % num[0])
    print("Averaging half 2 with %d particles" % num[1])
    if num[0] > 0:
        half[0, :, :, :] = half[0, :, :, :] / num[0]
    if num[1] > 0:
        half[1, :, :, :] = half[1, :, :, :] / num[1]

    # Save the averaged data
    print("Saving half 1 to %s" % half1_filename)
    handle = mrcfile.new(half1_filename, overwrite=True)
    handle.set_data(half[0, :, :, :])
    handle.voxel_size = voxel_size
    print("Saving half 2 to %s" % half2_filename)
    handle = mrcfile.new(half2_filename, overwrite=True)
    handle.set_data(half[1, :, :, :])
    handle.voxel_size = voxel_size
