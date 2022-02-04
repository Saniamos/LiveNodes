import numpy as np
from .node import Node

class Transform_majority_select(Node):

    def receive_data(self, data_frame, **kwargs):
        val, counts = np.unique(data_frame, axis=-1, return_counts=True)
        self.send_data([val[np.argmax(counts, axis=-1)]]) # TODO: not sure if this is fully correct, maybe write some tests, but works for now
        