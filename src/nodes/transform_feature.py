import numpy as np
from .node import Node

import multiprocessing as mp

### File mostly copy pasted from my mkr libaray (yh)

from .features.base import BaseTransformer_eager, FeatureUnion
from . import features as mkr_features
import tsfel.feature_extraction.features as tsfel
from inspect import signature


class SingleChannelFeature (BaseTransformer_eager):
    def __init__(self, fn, fnParams={}):
        self.fn = fn
        self.fnParams = fnParams
        
    def transformSingleChannelTS(self, ts):
        return np.array([self.fn(window, **self.fnParams) for window in ts])
    
    def transform(self, wts):
        return list(map(self.transformSingleChannelTS, wts))
    
class MultiChannelFeature (BaseTransformer_eager):
    def __init__(self, fn, fnParams={}):
        self.fn = fn
        self.fnParams = fnParams

    def transform(self, wts):
        return self.fn(wts, **self.fnParams)
    
class MultipleWrapper (BaseTransformer_eager):
    def __init__(self, estimator: BaseTransformer_eager):
        self.estimator = estimator

    def transform(self, wts):
        res = np.array(self.estimator.transform(wts))
        if len(res.shape) == 2: # -> the feature returned an array on each channel for each window
            self.dimensions_ = np.ma.size(res, axis=-1)
            return np.hstack(res.transpose(2, 0, 1))
        elif len(res.shape) == 1: # -> the feature returned a single value on each channel for each window
            self.dimensions_ = 1
            return res


class Transform_feature(Node):
    def __init__(self, name="Features", features=["calc_mean"], feature_args={}, **kwargs):
        super().__init__(name, dont_time)

        self.features = features
        self.feature_args = feature_args

        self.featureList = []
        for f_name in features:
            if f_name.startswith('tsfel:'):
                ftfn = getattr(tsfel, f_name[len('tsfel:'):])
                ftTransformer = SingleChannelFeature
            else:
                ftfn = getattr(mkr_features, f_name)
                ftTransformer = MultiChannelFeature
                
            ftfnParams = signature(ftfn).parameters
            ftArgs = {key: feature_args[key] for key in feature_args if key in ftfnParams and not key == 'wts'}
            
            self.featureList.append(MultipleWrapper(estimator=ftTransformer(ftfn, ftArgs)))          

        self._union = FeatureUnion(self.featureList, featureNames=self.features)
        # self._union = FeatureUnion(self.featureList, featureNames=self.features, **self.unionParams)

        self.channel_names = []
        self.out_channels = None

    @staticmethod
    def info():
        return {
            "class": "Transform_feature",
            "file": "Transform_feature.py",
            "in": ["Data", "Channel Names"],
            "out": ["Data", "Channel Names"],
            "init": {
                "name": "Name"
            },
            "category": "Transform"
        }
        
    @property
    def in_map(self):
        return {
            "Data": self.receive_data,
            "Channel Names": self.receive_channels
        }
        
    def _settings(self):
        return {\
            "features": self.features,
            "feature_args": self.feature_args
        }

    def receive_channels(self, names, **kwargs):
        self.channel_names = names
        self.out_channels = None

    def process(self, data, **kwargs):
        # TODO: update the union stuff etc to not expect a tuple as input
        # TODO: update this to not expect it to be wrapped in a list
        # TODO: update this to not use a map anymore
        # TODO: currently ft.transform is called twice, as the dimensions_ will otherwise not be set -> most of the time we do double the work for no benefit 
        # data, channels = self._union.transform((data_frame, self.channel_names))
        data, channels = self._union.transform(([np.array(data_frame).T], self.channel_names))
        self._emit_data(list(data))

        if self.out_channels == None and len(channels) != 0:
            print(channels)
            self.out_channels = channels
            self._emit_data(channels, channel="Channel Names")
