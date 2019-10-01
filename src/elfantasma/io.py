#
# elfantasma.io.py
#
# Copyright (C) 2019 Diamond Light Source and Rosalind Franklin Institute
#
# Author: James Parkhurst
#
# This code is distributed under the GPLv3 license, a copy of
# which is included in the root directory of this package.
#
import h5py
import numpy
import mrcfile
import os
import PIL.Image


class Writer(object):
    """
    Interface to write the simulated data

    """

    @property
    def shape(self):
        """
        The shape property

        """
        return self._data.shape

    @property
    def data(self):
        """
        The data property

        """
        return self._data

    @property
    def angle(self):
        """
        The angle property

        """
        return self._angle

    @property
    def position(self):
        """
        The position property

        """
        return self._position


class MrcFileWriter(Writer):
    """
    Write to an mrcfile

    """

    class AngleProxy(object):
        """
        Proxy interface to angles

        """

        def __init__(self, handle):
            self.handle = handle

        def __setitem__(self, item, data):
            self.handle.extended_header[item]["Tilt axis angle"] = data

    class PositionProxy(object):
        """
        Proxy interface to positions

        """

        def __init__(self, handle):
            self.handle = handle
            n = len(self.handle.extended_header)
            self.x, self.y = numpy.meshgrid(numpy.arange(0, 3), numpy.arange(0, n))

        def __setitem__(self, item, data):

            # Set the items
            def setitem_internal(j, i, d):
                if i == 0:
                    self.handle.extended_header[j]["X-Stage"] = d
                elif i == 1:
                    self.handle.extended_header[j]["Y-Stage"] = d
                elif i == 2:
                    self.handle.extended_header[j]["Z-Stage"] = d

            # Get the indices from the item
            x = self.x[item]
            y = self.y[item]

            # Set the item
            if isinstance(x, numpy.ndarray):
                for j, i, d in zip(y, x, data):
                    setitem_internal(j, i, d)
            else:
                setitem_internal(y, x, data)

    def __init__(self, filename, shape):
        """
        Initialise the writer

        Args:
            filename (str): The filename
            shape (tuple): The shape of the data

        """

        # Open the handle to the mrcfile
        self.handle = mrcfile.new_mmap(
            filename, shape=shape, mrc_mode=6, overwrite=True
        )

        # Setup the extended header
        extended_header = numpy.zeros(
            shape=shape[0], dtype=mrcfile.dtypes.FEI_EXTENDED_HEADER_DTYPE
        )
        self.handle.set_extended_header(extended_header)
        self.handle.header.exttyp = "FEI1"

        # Set the data array
        self._data = self.handle.data
        self._angle = MrcFileWriter.AngleProxy(self.handle)
        self._position = MrcFileWriter.PositionProxy(self.handle)


class NexusWriter(Writer):
    """
    Write to a nexus file

    """

    class PositionProxy(object):
        """
        Proxy interface to positions

        """

        def __init__(self, handle):
            self.handle = handle
            n = self.handle["x_translation"].shape[0]
            self.x, self.y = numpy.meshgrid(numpy.arange(0, 3), numpy.arange(0, n))

        def __setitem__(self, item, data):

            # Set the items
            def setitem_internal(j, i, d):
                if i == 0:
                    self.handle["x_translation"][j] = d
                elif i == 1:
                    self.handle["y_translation"][j] = d
                elif i == 2:
                    self.handle["z_translation"][j] = d

            # Get the indices from the item
            x = self.x[item]
            y = self.y[item]

            # Set the item
            if isinstance(x, numpy.ndarray):
                for j, i, d in zip(y, x, data):
                    setitem_internal(j, i, d)
            else:
                setitem_internal(y, x, data)

    def __init__(self, filename, shape):
        """
        Initialise the writer

        Args:
            filename (str): The filename
            shape (tuple): The shape of the data

        """

        # Open the file for writing
        self.handle = h5py.File(filename, "w")

        # Create the entry
        entry = self.handle.create_group("entry")
        entry.attrs["NX_class"] = "NXentry"
        entry["definition"] = "NXtomo"

        # Create the instrument
        instrument = entry.create_group("instrument")
        instrument.attrs["NX_class"] = "NXinstrument"

        # Create the detector
        detector = instrument.create_group("detector")
        detector.attrs["NX_class"] = "NXdetector"
        detector.create_dataset("data", shape=shape, dtype=numpy.float32)
        detector["image_key"] = numpy.zeros(shape=shape[0])

        # Create the sample
        sample = entry.create_group("sample")
        sample.attrs["NX_class"] = "NXsample"
        sample["name"] = "elfantasma-simulation"
        sample.create_dataset("rotation_angle", shape=(shape[0],), dtype=numpy.float32)
        sample.create_dataset("x_translation", shape=(shape[0],), dtype=numpy.float32)
        sample.create_dataset("y_translation", shape=(shape[0],), dtype=numpy.float32)
        sample.create_dataset("z_translation", shape=(shape[0],), dtype=numpy.float32)

        # Create the data
        data = entry.create_group("data")
        data["data"] = detector["data"]
        data["rotation_angle"] = sample["rotation_angle"]
        data["x_translation"] = sample["x_translation"]
        data["y_translation"] = sample["y_translation"]
        data["z_translation"] = sample["z_translation"]
        data["image_key"] = detector["image_key"]

        # Set the data ptr
        self._data = data["data"]
        self._angle = data["rotation_angle"]
        self._position = NexusWriter.PositionProxy(data)


class ImageWriter(Writer):
    """
    Write to a images

    """

    class DataProxy(object):
        """
        A proxy interface for the data

        """

        def __init__(self, template, shape=None, vmin=None, vmax=None):
            self.template = template
            self.shape = shape
            self.vmin = vmin
            self.vmax = vmax

        def __setitem__(self, item, data):

            # Check the input
            assert isinstance(item, tuple)
            assert isinstance(item[1], slice)
            assert isinstance(item[2], slice)
            assert item[1].start is None
            assert item[1].stop is None
            assert item[1].step is None
            assert item[2].start is None
            assert item[2].stop is None
            assert item[2].step is None
            assert len(data.shape) == 2
            assert data.shape[0] == self.shape[1]
            assert data.shape[1] == self.shape[2]

            # Compute scale factors to put between 0 and 255
            if self.vmin is None:
                vmin = numpy.min(data)
            else:
                vmin = self.vmin
            if self.vmax is None:
                vmax = numpy.max(data)
            else:
                vmax = self.vmax
            s1 = 255.0 / (vmax - vmin)
            s0 = -s1 * vmin

            # Save the image to file
            filename = self.template % (item[0] + 1)
            print(f"    writing image {item[0]+1} to {filename}")
            image = (data * s1 + s0).astype(numpy.uint8)
            PIL.Image.fromarray(image).save(filename)

    def __init__(self, template, shape=None, vmin=None, vmax=None):
        """
        Initialise the writer

        Args:
            filename (str): The filename
            shape (tuple): The shape of the data

        """

        # Set the proxy data interface
        self._data = ImageWriter.DataProxy(template, shape, vmin, vmax)

        # Create dummy arrays for angle and position
        self._angle = numpy.zeros(shape=shape[0], dtype=numpy.float32)
        self._position = numpy.zeros(shape=(shape[0], 3), dtype=numpy.float32)


class Reader(object):
    """
    Interface to write the simulated data

    """

    def __init__(self, handle, data, angle, position):
        """
        Initialise the data

        Args:
            data (array): The data array
            angle (array): The angle array
            position (array): The position array

        """
        # Check the size
        assert len(angle) == data.shape[0], "Inconsistent dimensions"
        assert len(position) == data.shape[0], "Inconsistent dimensions"

        # Set the array
        self.data = data
        self.angle = angle
        self.position = position

    @classmethod
    def from_mrcfile(Class, filename):
        """
        Read the simulated data from a mrc file

        Args:
            filename (str): The input filename

        """

        # Read the data
        handle = mrcfile.mmap(filename, "r")

        # Check the header info
        assert handle.header.exttyp == b"FEI1"
        assert handle.extended_header.dtype == mrcfile.dtypes.FEI_EXTENDED_HEADER_DTYPE
        assert len(handle.extended_header.shape) == 1
        assert handle.extended_header.shape[0] == handle.data.shape[0]

        # Read the angles
        angle = numpy.zeros(handle.data.shape[0], dtype=numpy.float32)
        for i in range(handle.extended_header.shape[0]):
            angle[i] = handle.extended_header[i]["Tilt axis angle"]

        # Read the positions
        position = numpy.zeros(shape=(handle.data.shape[0], 3), dtype=numpy.float32)
        for i in range(handle.extended_header.shape[0]):
            position[i, 0] = handle.extended_header[i]["X-Stage"]
            position[i, 1] = handle.extended_header[i]["Y-Stage"]
            position[i, 2] = handle.extended_header[i]["Z-Stage"]

        # Create the reader
        return Reader(handle, handle.data, angle, position)

    @classmethod
    def from_nexus(Class, filename):
        """
        Read the simulated data from a nexus file

        Args:
            filename (str): The input filename

        """

        # Read the data from disk
        handle = h5py.File(filename, "r")

        # Get the entry
        entry = handle["entry"]
        assert entry.attrs["NX_class"] == "NXentry"
        assert entry["definition"][()] == "NXtomo"

        # Get the data
        data = entry["data"]

        position = numpy.array(
            (data["x_translation"], data["y_translation"], data["z_translation"])
        ).T

        # Create the reader
        return Reader(handle, data["data"], data["rotation_angle"], position)

    @classmethod
    def from_file(Class, filename):
        """
        Read the simulated data from file

        Args:
            filename (str): The output filename

        """
        extension = os.path.splitext(filename)[1].lower()
        if extension in [".mrc"]:
            return Class.from_mrcfile(filename)
        elif extension in [".h5", ".hdf5", ".nx", ".nxs", ".nexus", "nxtomo"]:
            return Class.from_nexus(filename)
        else:
            raise RuntimeError(f"File with unknown extension: {filename}")


def new(filename, shape=None, vmin=None, vmax=None):
    """
    Create a new file for writing

    Args:
        filename (str): The output filename
        shape (tuple): The output shape
        vmin (int): The minimum value (only used in ImageWriter)
        vmax (int): The maximum value (only used in ImageWriter)

    Returns:
        object: The file writer

    """
    extension = os.path.splitext(filename)[1].lower()
    if extension in [".mrc"]:
        return MrcFileWriter(filename, shape)
    elif extension in [".h5", ".hdf5", ".nx", ".nxs", ".nexus", "nxtomo"]:
        return NexusWriter(filename, shape)
    elif extension in [".png", ".jpg", ".jpeg"]:
        return ImageWriter(filename, shape, vmin, vmax)
    else:
        raise RuntimeError(f"File with unknown extension: {filename}")


def open(filename):
    """
    Read the simulated data from file

    Args:
        filename (str): The output filename

    """
    return Reader.from_file(filename)
