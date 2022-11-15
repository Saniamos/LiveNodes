
import asyncio
import logging
from logging.handlers import QueueHandler
import threading as th
import multiprocessing as mp
from itertools import groupby
import traceback
from livenodes.components.utils.log import drain_log_queue


from livenodes.components.node_logger import Logger

# TODO: is this also possibly without creating a new thread, ie inside of main thread? 
# i'm guessing no, as then the start likely does not return and then cannot be stopped by hand, but only if it returns by itself

def parse_location(location):
    comps = ['', '', '', '']
    
    splits = location.split(':')
    for i, split in enumerate(reversed(splits)):
        comps[i] = split

    thread, process, port, host = comps        
    host = f"{host}:{port}"

    return host, process, thread

class Processor_threads(Logger):
    def __init__(self, nodes, location, bridges) -> None:
        super().__init__()
        # -- both threads
        # indicates that the subprocess is ready
        self.ready_event = th.Event() 
        # indicates that the readied nodes should start sending data
        self.start_lock = th.Lock() 
        # indicates that the started nodes should stop sending data
        self.stop_lock = th.Lock() 
        # indicates that the thread should be closed without waiting on the nodes to finish
        self.close_lock = th.Lock() 
        # used for logging identification
        self.location = location

        # -- parent thread
        self.nodes = nodes
        self.bridges = bridges
        self.subprocess = None
        self.start_lock.acquire()
        self.stop_lock.acquire()
        self.close_lock.acquire()

        self.info(f'Creating Threading Computer with {len(self.nodes)} nodes.')

    def __str__(self) -> str:
        return f"Computer:{self.location}"

    # parent thread
    def setup(self):
        self.info('Readying')

        self.subprocess = th.Thread(
                        target=self.start_subprocess,
                        args=(self.bridges,), name=str(self))
        self.subprocess.start()
        
        self.info('Waiting for worker to be ready')
        self.ready_event.wait()

    # parent thread
    def start(self):
        self.info('Starting')
        self.start_lock.release()

    # parent thread
    def join(self):
        """ used if the processing is nown to end"""
        self.info('Joining')
        self.subprocess.join()

    # parent thread
    def stop(self, timeout=0.1):
        """ used if the processing is nown to be endless"""

        self.info('Stopping')
        self.stop_lock.release()
        self.subprocess.join(timeout)
        self.info('Returning; thread finished: ', not self.subprocess.is_alive())

    # parent thread
    def close(self, timeout=0.1):
        self.info('Closing')
        self.close_lock.release()
        self.subprocess.join(timeout)
        if self.subprocess.is_alive():
            self.info('Timout reached, but still alive')
        # self.subprocess = None
    
    # parent thread
    def is_finished(self):
        return (self.subprocess is not None) and (not self.subprocess.is_alive())
        
    # worker thread
    def start_subprocess(self, bridges):
        self.info('Starting Thread')
        self.ready_event.set()

        def custom_exception_handler(loop, context):
            nonlocal self
            self.error(context)
            return loop.default_exception_handler(context)

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        # TODO: this doesn't seem to do much?
        self.loop.set_exception_handler(custom_exception_handler)

        futures = []

        for node, bridges in zip(self.nodes, bridges):
            input_bridges, output_bridges = bridges['recv'], bridges['emit']
            futures.append(node.ready(input_endpoints=input_bridges, output_endpoints=output_bridges))

        self.start_lock.acquire()
        for node in self.nodes:
            node.start()

        self.onprocess_task = asyncio.gather(*futures)
        self.onprocess_task.add_done_callback(self.handle_finished)
        self.onstop_task = asyncio.gather(self.handle_stop())
        self.onclose_task = asyncio.gather(self.handle_close())

        # async def combined_tasks():
        #     try:
        #         await asyncio.gather(self.onprocess_task, self.onstop_task, self.onclose_task)
        #     except Exception as e:
        #         self.error(f'failed on one of the combined tasks in: {str(self)}')
        #         self.error(e)
        #         self.error(traceback.format_exc())

        # with the return_exceptions, we don't care how the processe
        self.loop.run_until_complete(asyncio.gather(self.onprocess_task, self.onstop_task, self.onclose_task, return_exceptions=True))

        # wrap up the asyncio event loop
        self.loop.stop()
        self.loop.close()

        self.info('Finished subprocess and returning')

    # worker thread
    def handle_finished(self, *args):
        self.info('All Tasks finished, aborting stop and close listeners')

        self.onstop_task.cancel()
        self.onclose_task.cancel()

    # worker thread
    async def handle_stop(self):

        # loop non-blockingly until we can acquire the stop lock
        while not self.stop_lock.acquire(timeout=0):
            await asyncio.sleep(0.001)
        
        self.info('Stopped called, stopping nodes')
        for node in self.nodes:
            node.stop()

    # worker thread
    async def handle_close(self):
        # loop non-blockingly until we can acquire the close/termination lock
        while not self.close_lock.acquire(timeout=0):
            await asyncio.sleep(0.001)
        
        # print('Closing running nodes')
        # for node in self.nodes:
        #     node.close()

        # give one last chance to all to finish
        # await asyncio.sleep(0)

        self.info('Closed called, stopping all remaining tasks')
        self.onprocess_task.cancel()










class Processor_process(Logger):
    def __init__(self, nodes, location, bridges, stop_timeout_threads=0.1, close_timeout_threads=0.1) -> None:
        super().__init__()
        # -- both processes
        # indicates that the subprocess is ready
        self.ready_event = mp.Event() 
        # indicates that the readied nodes should start sending data
        self.start_lock = mp.Lock() 
        # indicates that the started nodes should stop sending data
        self.stop_lock = mp.Lock() 
        # indicates that the thread should be closed without waiting on the nodes to finish
        self.close_lock = mp.Lock() 
        # used for logging identification
        self.location = location

        # -- main process
        self.nodes = nodes
        self.bridges = bridges
        self.subprocess = None
        self.start_lock.acquire()
        self.stop_lock.acquire()
        self.close_lock.acquire()

        # -- worker process
        self.stop_timeout_threads = stop_timeout_threads
        self.close_timeout_threads = close_timeout_threads

        self.info(f'Creating Process Computer with {len(self.nodes)} nodes.')


    def __str__(self) -> str:
        return f"Computer:{self.location}"

    # parent process
    def setup(self):
        self.info('Readying')

        parent_log_queue = mp.Queue()
        logger_name = 'livenodes'
        
        self.worker_log_handler_termi_sig = th.Event()

        self.worker_log_handler = th.Thread(target=drain_log_queue, args=(parent_log_queue, logger_name, self.worker_log_handler_termi_sig))
        self.worker_log_handler.deamon = True
        self.worker_log_handler.name = f"LogDrain-{self.worker_log_handler.name.split('-')[-1]}"
        self.worker_log_handler.start()

        self.subprocess = mp.Process(
                        target=self.start_subprocess,
                        args=(self.bridges, parent_log_queue, logger_name,), name=str(self))
        self.subprocess.start()
        
        self.info('Waiting for worker to be ready')
        self.ready_event.wait()

    # parent process
    def start(self):
        self.info('Starting')
        self.start_lock.release()

    # TODO: this will not work
    # as: the start() of the thread processor used inside of this processors supbrocess are non-blockign
    # therefore: we are waiting on the stop-lock which will be released once someone calls stop -> thus joining the subprocess will never return!
    # in the join case we would want to be able to join each thread cmp instead of waiting on stop or close...
    # FIXED: inside of the subprocess we are short_ciruiting the stop and close locks if the threads have returned by themselves, thus the join returns once close is called or the sub-threads return
    # parent process
    def join(self):
        """ used if the processing is nown to end"""
        self.info('Joining')
        self.subprocess.join()

    # parent process
    def stop(self, timeout=0.3):
        """ used if the processing is nown to be endless"""

        self.info('Stopping')
        self.stop_lock.release()
        self.subprocess.join(timeout)
        self.info('Returning; Process finished: ', not self.subprocess.is_alive())

    # parent process
    def close(self, timeout=0.5):
        self.info('Closing')
        self.close_lock.release()
        self.subprocess.join(timeout)
        if self.subprocess.is_alive():
            self.subprocess.terminate()
            self.info('Timout reached: killed process')
        # self.subprocess = None
        self.info('Closing Log Drain')
        self.worker_log_handler_termi_sig.set()

    # parent thread
    def is_finished(self):
        return self.subprocess is not None and not self.subprocess.is_alive()
        
    # worker process
    def check_threads_finished(self, computers):
        return all([cmp.is_finished() for cmp in computers])

    # worker process
    def start_subprocess(self, bridges, subprocess_log_queue, logger_name):
        logger = logging.getLogger(logger_name)
        logger.addHandler(QueueHandler(subprocess_log_queue))

        self.info('Starting Process')
        self.ready_event.set()

        computers = []
        # TODO: it's a little weird, that bridges are specifically passed, but nodes are not, we should investigate that
        # ie, probably this is fine, as we specifcially need the bridge endpoints, but the nodes may just be pickled, but looking into this never hurts....
        bridge_lookup = {str(node): bridge for node, bridge in zip(self.nodes, bridges)}

        locations = groupby(sorted(self.nodes, key=lambda n: n.compute_on), key=lambda n: n.compute_on)
        for loc, loc_nodes in locations:
            loc_nodes = list(loc_nodes)
            print(f'Resolving computer group. Location: {loc}; Nodes: {len(loc_nodes)}')
            node_specific_bridges = [bridge_lookup[str(n)] for n in loc_nodes]
            cmp = Processor_threads(nodes=loc_nodes, location=loc, bridges=node_specific_bridges)
            cmp.setup()
            computers.append(cmp)

        self.start_lock.acquire()
        self.info('Starting Computers')
        for cmp in computers:
            # this is non-blocking -> this process will lock until the stop_lock can be aquired
            # inside of this process all sub-threads will run until stop is called
            cmp.start()


        all_computers_finished = False
        while not self.stop_lock.acquire(timeout=0.1) and not all_computers_finished:
            all_computers_finished = all([cmp.is_finished() for cmp in computers])
        
        if all_computers_finished:
            self.info('All Computers have finished, returning')
        else:
            self.info('Stopping Computers')
            for cmp in computers:
                # the cmps are all returning after the timeout, as they all are Processor_Threads
                # -> therefore, this cannot block indefinetly and we can soon wait on the close_lock
                cmp.stop(timeout=self.stop_timeout_threads)

            # if not all_computers_finished:
            self.close_lock.acquire()
            self.info('Closing Computers')
            for cmp in computers:
                cmp.close(timeout=self.close_timeout_threads)

        self.info('Finished Process and returning')
