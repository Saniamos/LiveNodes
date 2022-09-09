import asyncio
from enum import IntEnum
import time
import numpy as np
import multiprocessing as mp
import threading
import queue

from .connection import Connection

from .node_logger import Logger

class Location(IntEnum):
    SAME = 1
    THREAD = 2
    PROCESS = 3
    # SOCKET = 4



# class Bridge_local():
#     def __init__(self, _from=None, _to=None):
#         self._read = {}

#     def put(self, ctr, item, last_package):
#         self._read[ctr] = (item, last_package)

#     def discard_before(self, ctr):
#         self._read = {
#             key: val
#             for key, val in self._read.items() if key >= ctr
#         }
        
#     def get(self, ctr):
#         # in the process and thread case the queue should always be empty if we arrive here
#         # This should also never be executed in process or thread, as then the update function does not block and keys are skipped!
#         if ctr in self._read:
#             return True, *self._read[ctr]
#         return False, None

class Bridge_local():
    def __init__(self, _from=None, _to=None):
        self.queue = asyncio.Queue()
        self._read = {}

    def put(self, ctr, item, last_package):
        print('putting value')
        self.queue.put_nowait((ctr, item, last_package))

    def empty(self):
        return self.queue.qsize() <= 0
        
    async def update(self):
        print('waiting for asyncio to receive a value')
        itm_ctr, item, last_package = await self.queue.get()
        self._read[itm_ctr] = (item, last_package)
        return itm_ctr, last_package

    def discard_before(self, ctr):
        self._read = {
            key: val
            for key, val in self._read.items() if key >= ctr
        }

    def get(self, ctr):
        # in the process and thread case the queue should always be empty if we arrive here
        # This should also never be executed in process or thread, as then the update function does not block and keys are skipped!
        if ctr in self._read:
            return True, *self._read[ctr]
        return False, None, None


class Bridge_mp():
    def __init__(self, _from=None, _to=None):
        self.queue = mp.Queue()
        self._read = {}
        self._to = _to

    def put(self, ctr, item, last_package):
        self.queue.put((ctr, item, last_package))

    def update(self, timeout=0.01):
        try:
            itm_ctr, item, last_package = self.queue.get(block=True, timeout=timeout)
            self._read[itm_ctr] = (item, last_package)
            return True, itm_ctr
        except queue.Empty:
            pass
        return False, -1

    def empty(self):
        return self.queue.empty()

    def empty_queue(self):
        while not self.queue.empty():
            itm_ctr, item, last_package = self.queue.get()
            # TODO: if itm_ctr already exists, should we not rather extend than overwrite it? (thinking of the mulitple emit_data per process call examples (ie window))
            # TODO: yes! this is what we should do :D
            self._read[itm_ctr] = (item, last_package)

    def discard_before(self, ctr):
        self._read = {
            key: val
            for key, val in self._read.items() if key >= ctr
        }

    def get(self, ctr):
        if self._to == Location.SAME:
            # This is only needed in the location.same case, as in the process and thread case the queue should always be empty if we arrive here
            # This should also never be executed in process or thread, as then the update function does not block and keys are skipped!
            self.empty_queue()

        # in the process and thread case the queue should always be empty if we arrive here
        # This should also never be executed in process or thread, as then the update function does not block and keys are skipped!
        if ctr in self._read:
            return True, *self._read[ctr]
        return False, None, None


class Multiprocessing_Data_Storage():
    def __init__(self) -> None:
        self.bridges = {}

    @staticmethod
    def resolve_bridge(connection: Connection):
        emit_loc = connection._emit_node.compute_on
        recv_loc = connection._recv_node.compute_on

        if emit_loc in [Location.PROCESS, Location.THREAD] or recv_loc in [Location.PROCESS, Location.THREAD]:
            return Bridge_mp(_from=emit_loc, _to=recv_loc)
        else:
            return Bridge_local(_from=emit_loc, _to=recv_loc)

    def set_inputs(self, input_connections):
        for con in input_connections:
            self.bridges[con._recv_port.key] = self.resolve_bridge(con)

    def empty(self):
        return all([q.empty() for q in self.bridges.values()])

    # can be called from any process
    def put(self, connection, ctr, data, last_package=False):
        print('data storage putting value', connection._recv_port.key, type(self.bridges[connection._recv_port.key]))
        self.bridges[connection._recv_port.key].put(ctr, data, last_package)

    # will only be called within the processesing process
    def get(self, ctr):
        res = {}
        # update current state, based on own clock
        for key, queue in self.bridges.items():
            # discard everything, that was before our own current clock
            found_value, cur_value, last_value = queue.get(ctr)

            if found_value:
                # TODO: instead of this key transformation/tolower consider actually using classes for data types... (allows for gui names alongside dev names and not converting between the two)
                res[key] = cur_value
        return res 
    
    # will only be called within the processesing process
    def discard_before(self, ctr):
        for bridge in self.bridges.values():
            bridge.discard_before(ctr) 


class Processor(Logger):

    def __init__(self, compute_on=Location.SAME, **kwargs) -> None:
        super().__init__(**kwargs)
        self.compute_on = compute_on

        self._subprocess_info = {}
        if self.compute_on in [Location.PROCESS]:
            self._subprocess_info = {
                "process": None,
                "termination_lock": mp.Lock()
            }
        elif self.compute_on in [Location.THREAD]:
            self._subprocess_info = {
                "process": None,
                "termination_lock":
                threading.Lock()  # as this is called from the main process
            }

        self.info('Computing on: ', self.compute_on)    

        self.data_storage = Multiprocessing_Data_Storage()
        # this will be instantiated once the whole thing starts, as before connections (and compute_ons) might change

    # required if we do the same=main process thing, as we cannot create the processes on instantiation
    def spawn_processes(self):
        graph_nodes = self.discover_graph(self)
        for node in graph_nodes:
            if 'process' in node._subprocess_info and node._subprocess_info['process'] is None:
                if node.compute_on == Location.PROCESS:
                    node._subprocess_info['process'] = mp.Process(
                        target=node._process_on_proc)
                elif node.compute_on == Location.THREAD:
                    node._subprocess_info['process'] = threading.Thread(
                        target=node._process_on_proc)


    def _acquire_lock(self, lock, block=True, timeout=None):
        if self.compute_on in [Location.PROCESS]:
            res = lock.acquire(block=block, timeout=timeout)
        elif self.compute_on in [Location.THREAD]:
            if block:
                res = lock.acquire(blocking=True,
                                   timeout=-1 if timeout is None else timeout)
            else:
                res = lock.acquire(
                    blocking=False)  # forbidden to specify timeout
        else:
            raise Exception(
                'Cannot acquire lock in non multi process/threading environment'
            )
        return res

    def start_node(self):
        # create bridges and storage based on the connections we have once we've started?
        # as then compute_on and number of connections etc should not change anymore
        self.data_storage.set_inputs(self.input_connections)

        # TODO: consider moving this in the node constructor, so that we do not have this nested behaviour processeses due to parents calling their childs start()
        # TODO: but maybe this is wanted, just buggy af atm
        if self.compute_on in [Location.PROCESS, Location.THREAD]:
            # if self.compute_on == Location.PROCESS:
            #     self._subprocess_info['process'] = mp.Process(
            #         target=self._process_on_proc)
            # elif self.compute_on == Location.THREAD:
            #     self._subprocess_info['process'] = threading.Thread(
            #         target=self._process_on_proc)

            self.info('create subprocess')
            self._acquire_lock(self._subprocess_info['termination_lock'])
            self.info('start subprocess')
            self._subprocess_info['process'].start()
        elif self.compute_on in [Location.SAME]:
            self._call_user_fn(self._onstart, '_onstart')
            self.info('Executed _onstart')
            
            self.info('Waiting on inputs')
            # await self._setup_process()

            # just to make sure a loop exists, which it likely already does 
            self._loop = asyncio.get_event_loop()
            self._finished = self._loop.create_future()
            self._setup_process()

    def _setup_process_cb(self, task):
        ctr, last_package = task.result()
        # finished, unfinished = task.result()

        # for t in unfinished:
        #     # these will be setup in the recursion again
        #     t.cancel()

        # for t in finished:
        #     ctr, last_package = t.result()
        print('task finished', ctr, last_package)
        self._process(ctr)
        if not self.data_storage.empty():
            print('recursing')
            # recurse and wait for next queue item to become available
            self._setup_process()
        else:
            self._finished.set_result(True)
            self._current_task = None
    
    async def _setup_process_race(self):
        async_bridges = [queue.update() for queue in self.data_storage.bridges.values()]
        # wait until one of them returns
        done, pending = await asyncio.wait(async_bridges, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        
        return list(done)[0].result()

    def _setup_process(self):
        # start infinite coroutine, until closed
        # will use asyncio await to wait for new tasks which then will be processed
        if self._running:
            print('Setting awaits', str(self))
            # collect all asyncio queues from our bridges
            # async_bridges = [queue.update() for queue in self.data_storage.bridges.values()]
            # wait until one of them returns
            self._current_task = self._loop.create_task(self._setup_process_race())
            # if one returns get the current ctr and pass it to _process inside of setup_cb
            # which will then recurse to wait for the next queue to spit up a value
            self._current_task.add_done_callback(self._setup_process_cb)
            print('finished setting await callbacks')


    async def _join_local(self):
        # while self._current_task is not None:
        #     await asyncio.gather(self._current_task)
        await self._finished
        # await asyncio.sleep(2)

    def stop_node(self, force=False):
        if self.compute_on in [Location.PROCESS, Location.THREAD]:
            self.info(self._subprocess_info['process'].is_alive(),
                        self._subprocess_info['process'].name)
            self._subprocess_info['termination_lock'].release()
            if not force:
                self._subprocess_info['process'].join()
            else:da 
                self._subprocess_info['process'].join(1)
                self.info(self._subprocess_info['process'].is_alive(),
                            self._subprocess_info['process'].name)

                if self.compute_on in [Location.PROCESS]:
                    self._subprocess_info['process'].terminate()
                    self.info(self._subprocess_info['process'].is_alive(),
                                self._subprocess_info['process'].name)

        elif self.compute_on in [Location.SAME]:            
            if force:
                self._loop.close()
            else:
                self._loop.run_until_complete(self._join_local())
                # self._loop.run_until_complete(asyncio.wait([self._finished]))
                self._loop.stop()

            self.error('Executing _onstop')
            self._call_user_fn(self._onstop, '_onstop')

    def _process_on_proc(self):
        self.info('Started subprocess')

        self._call_user_fn(self._onstart, '_onstart')
        self.info('Executed _onstart')

        # as long as we do not receive a termination signal, we will wait for data to be processed
        # the .empty() is not reliable (according to the python doc), but the best we have at the moment
        was_queue_empty_last_iteration = 0
        queue_empty = False
        was_terminated = False

        # one iteration takes roughly 0.00001 * channels -> 0.00001 * 10 * 100 = 0.01
        while not was_terminated or was_queue_empty_last_iteration < 10:
            could_acquire_term_lock = self._acquire_lock(
                self._subprocess_info['termination_lock'], block=False)
            was_terminated = was_terminated or could_acquire_term_lock
            # block until signaled that we have new data
            # as we might receive not data after having received a termination
            #      -> we'll just poll, so that on termination we do terminate after no longer than 0.1seconds
            # self.info(was_terminated, was_queue_empty_last_iteration)
            queue_empty = True
            for queue in self.data_storage.bridges.values():
                found_value, ctr = queue.update(timeout=0.00001)
                if found_value:
                    self._process(ctr)
                    queue_empty = False
            if queue_empty:
                was_queue_empty_last_iteration += 1
            else:
                was_queue_empty_last_iteration = 0

        self.info('Executing _onstop')
        self._call_user_fn(self._onstop, '_onstop')

        self.info('Finished subprocess')