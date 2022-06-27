from functools import partial
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import animation
import matplotlib

import time
import math

import datetime
import time

import os

# from livenodes.nodes.in_playback import In_playback
# from livenodes.nodes.draw_lines import Draw_lines
from livenodes.node import Node
from livenodes.viewer import View_MPL
from livenodes.logger import logger

# from src.realtime_animation import RealtimeAnimation

import seaborn as sns

sns.set_style("darkgrid")
sns.set_context("paper")

matplotlib.rcParams['toolbar'] = 'None'


def _log_helper(f, msg):
    f.write(msg + '\n')
    f.flush()


if __name__ == '__main__':
    os.chdir('./projects/test_ask')

    log_file = f"./logs/{datetime.datetime.fromtimestamp(time.time())}"
    with open(log_file, 'a') as f:
        log = partial(_log_helper, f)
        logger.register_cb(log)

        print('=== Construct Pipeline ====')
        # channel_names_raw = ['EMG1', 'Gonio2', 'AccLow2']
        # # channel_names_fts = ['EMG1__calc_mean', 'Gonio2__calc_mean', 'AccLow2__calc_mean']
        # channel_names_fts = ['EMG1__rms', 'Gonio2__calc_mean', 'AccLow2__calc_mean']
        # recorded_channels = [
        #     'EMG1', 'EMG2', 'EMG3', 'EMG4',
        #     'Airborne',
        #     'AccUp1', 'AccUp2', 'AccUp3',
        #     'Gonio1',
        #     'AccLow1', 'AccLow2', 'AccLow3',
        #     'Gonio2',
        #     'GyroUp1', 'GyroUp2', 'GyroUp3',
        #     'GyroLow1', 'GyroLow2', 'GyroLow3']

        # meta = {
        #     "sample_rate": 1000,
        #     "channels": recorded_channels,
        #     "targets": ['cspin-ll', 'run', 'jump-2', 'shuffle-l', 'sit', 'cstep-r', 'vcut-rr', 'stair-down', 'stand-sit', 'jump-1', 'sit-stand', 'stand', 'cspin-lr', 'cspin-rr', 'cstep-l', 'vcut-ll', 'vcut-rl', 'shuffle-r', 'stair-up', 'walk', 'cspin-rl', 'vcut-lr']
        # }

        # # pipeline = In_playback(compute_on=Location.THREAD, block=False, files="./projects/test_ask/data/KneeBandageCSL2018/**/*.h5", meta=meta)
        # pipeline = In_playback(compute_on=Location.PROCESS, block=False, files="./projects/test_ask/data/KneeBandageCSL2018/**/*.h5", meta=meta)

        # channel_names = ['Gonio2', 'GyroLow1', 'GyroLow2', 'GyroLow3']
        # idx = np.isin(recorded_channels, channel_names).nonzero()[0]

        # # draw = Draw_lines(name='Raw Data', compute_on=Location.THREAD)
        # draw = Draw_lines(name='Raw Data', compute_on=Location.PROCESS)
        # # draw = Draw_lines(name='Raw Data', compute_on=Location.SAME)
        # draw.connect_inputs_to(pipeline)

        print('=== Load Pipeline ====')

        # pipeline = Node.load('./projects/test_ask/pipelines/recognize.json')
        pipeline = Node.load('./pipelines/preprocess.json')

        print('=== Start main loops ====')

        font = {'size': 6}
        plt.rc('font', **font)

        draws = {
            str(n): n.init_draw
            for n in Node.discover_graph(pipeline) if isinstance(n, View)
        }.values()
        print(draws)

        fig = plt.figure(num=0, figsize=(12, 7.5))
        # fig.suptitle("ASK", fontsize='x-large')
        fig.canvas.manager.set_window_title("ASK")

        if len(draws) <= 0:
            raise Exception('Must have at least one draw function registered')

        n_figs = len(draws)
        cols = min(2, n_figs)
        rows = math.ceil(n_figs / cols)  # ie max 3 columns

        # https://matplotlib.org/stable/gallery/subplots_axes_and_figures/subfigures.html
        subfigs = fig.subfigures(rows, cols)  #, wspace=1, hspace=0.07)

        if len(draws) == 1:
            subfigs = [
                subfigs
            ]  # matplotlibs subfigures call doesn't consistently return a list, but with n=1 the subfig directly...
        subfigs = np.array(subfigs).flatten()

        # artists = np.concatenate([setup_fn(subfig) for setup_fn, subfig in zip(draws, subfigs)])
        artists = [
            setup_fn(subfig) for setup_fn, subfig in zip(draws, subfigs)
        ]

        # not nice, as cannot be updated at runtime later on (not sure if that'll be necessary tho)
        def draw_update(i, **kwargs):
            ret_arts = list(
                np.concatenate([fn(**kwargs) for fn in artists], axis=0))

            if i % 100 == 0 and i != 0:
                el_time = time.time() - timer
                print(
                    f"Rendered {i} frames in {el_time:.2f} seconds. This equals {i/el_time:.2f}fps."
                )

            return ret_arts

        timer = time.time()
        pipeline.start()
        # time.sleep(1)
        # pipeline.stop()

        # time.sleep(4)
        print('test')

        def stop(*args):
            pipeline.stop()
            logger.remove_cb(log)
            return True

        animationProcess = animation.FuncAnimation(fig=fig,
                                                   func=draw_update,
                                                   interval=0,
                                                   blit=True)
        fig.canvas.mpl_connect("close_event", stop)

        plt.show()
