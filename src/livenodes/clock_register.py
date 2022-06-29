import multiprocessing as mp
import threading

class Clock_Register():
    state = {}
    times = {}

    queue = mp.SimpleQueue()

    _store = mp.Event()

    def __init__(self):
        self._owner_process = mp.current_process()
        self._owner_thread = threading.current_thread()

    # called in sub-processes
    def register(self, name, ctr):
        if not self._store.is_set():
            self.queue.put((name, ctr))

    def set_passthrough(self, node):
        print(f"Clock_Register set to passthrough by {str(node)}")
        self._store.set()
        self.queue = None

    # called in main/handling process
    def read_state(self):
        if self._owner_process != mp.current_process():
            raise Exception('Called from wrong process')
        if self._owner_thread != threading.current_thread():
            raise Exception('Called from wrong thread')
        if self._store.is_set():
            raise Exception('Clock Register was set to passthrough')

        while not self.queue.empty():
            name, ctr = self.queue.get()
            if name not in self.state:
                self.state[name] = []

            self.state[name].append(ctr)

        return self.state

    def all_at(self, ctr):
        states = self.read_state()

        for name, ctrs in states.items():
            if max(ctrs) < ctr:
                return False

        return True