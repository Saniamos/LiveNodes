import numpy as np
from .node import Sender
import glob, random
import h5py
import pandas as pd
import random

from joblib import Parallel, delayed

from .utils import printProgressBar


def read_data(f):
    # Read and send data from file
    with h5py.File(f, "r") as dataFile:
        dataSet = dataFile.get("data")
        data = dataSet[:]  # load into mem

        # Prepare framewise annotation to be send
        ref = pd.read_csv(f.replace('.h5', '.csv'),
                          names=["act", "start", "end"])
        targs = []
        last_end = 0
        for _, row in ref.iterrows():
            filler = "stand"  # use stand as filler for unknown. #Hack! TODO: remove
            targs.append([filler] * (row['start'] - last_end))
            targs.append([row['act']] * (row['end'] - row['start']))
            last_end = row['end']
        targs.append([filler] * (len(data) - last_end))
        targs = list(np.concatenate(targs))

    return data, targs


class In_data(Sender):
    """
    Playsback previously recorded data.

    Expects the following setup variables:
    - files (str): glob pattern for files 
    - sample_rate (number): sample rate to simulate in frames per second
    # - emit_at_once_size (int, default=5): number of frames that are sent at the same time -> not implemented yet
    """

    channels_in = []
    channels_out = [
        'Data', 'File', 'Annotation', 'Meta', 'Channel Names', 'Termination'
    ]

    category = "Data Source"
    description = ""

    example_init = {
        "files": "./files/**/.h5",
        "meta": {
            "sample_rate": 100,
            "targets": ["target 1"],
            "channels": ["Channel 1"]
        },
        "shuffle": True,
        "emit_at_once": 1,
        "name": "Data input",
    }

    # TODO: consider using a file for meta data instead of dictionary...
    def __init__(self,
                 files,
                 meta,
                 shuffle=True,
                 emit_at_once=1,
                 name="Data input",
                 **kwargs):
        super().__init__(name, **kwargs)

        self.meta = meta
        self.files = files
        self.emit_at_once = emit_at_once
        self.shuffle = shuffle

        self.sample_rate = meta.get('sample_rate')
        self.targets = meta.get('targets')
        self.channels = meta.get('channels')

    def _settings(self):
        return {\
            "emit_at_once": self.emit_at_once,
            "files": self.files,
            "meta": self.meta,
            "shuffle": self.shuffle
        }

    def _run(self):
        """
        Streams the data and calls frame callbacks for each frame.
        """
        fs = glob.glob(self.files)

        if self.shuffle:
            random.shuffle(fs)

        self._emit_data(self.meta, channel="Meta")
        self._emit_data(self.channels, channel="Channel Names")

        # TODO: create a producer/consumer (blocking)queue (with fixed items) here for best of both worlds ie fixed amount of mem with no hw access delay
        # for now: just preload everything
        in_mem = Parallel(n_jobs=10)(delayed(read_data)(f) for f in fs)

        l = len(fs)
        printProgressBar(0, l, prefix='Progress:', suffix='', length=50)
        for file_number, (f, (data, targs)) in enumerate(zip(fs, in_mem)):
            # for file_number, f in enumerate(fs):
            printProgressBar(file_number,
                             l,
                             prefix='Progress:',
                             suffix=f,
                             length=50)

            # self.info(f)

            # data, targs = read_data(f)

            for i in range(0, len(data), self.emit_at_once):
                d_len = len(data[i:i + self.emit_at_once]
                            )  # usefull if i+self.emit_at_once > len(data)
                self._emit_data(np.array([data[i:i + self.emit_at_once]]))
                # use reshape -1, as the data can also be shorter than emit_at_once and will be adjusted accordingly
                self._emit_data(np.array(
                    targs[i:i + self.emit_at_once]).reshape((1, -1, 1)),
                                channel='Annotation')
                # self.info('send', np.unique(targs[i:i + self.emit_at_once], return_counts=True))
                self._emit_data(np.array([file_number] * d_len).reshape(
                    (1, -1, 1)),
                                channel="File")

                finished = (l == file_number + 1) and (i + self.emit_at_once >= len(data))
                self._emit_data(
                    finished, channel='Termination'
                )  # TODO: maybe we could use something like this for syncing... ie seperate stream with just a counter
                
                self.info('finished?', not finished)
                yield not finished
