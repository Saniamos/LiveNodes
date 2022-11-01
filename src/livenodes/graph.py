from collections import defaultdict
from itertools import groupby
from .node import Node
from .components.computer import parse_location, Processor_threads, Processor_process

class Graph():

    def __init__(self, start_node) -> None:
        self.start_node = start_node
        self.nodes = Node.discover_graph(start_node)

        self.computers = []

    def lock_all(self):
        # Lock all nodes for processing (ie no input/output or setting changes allowed from here on)
        # also resolves bridges between nodes soon to be bridges across computers
        bridges = {str(n): {'emit': defaultdict(list), 'recv': {}} for n in self.nodes}

        for node in self.nodes:
            send_bridges, recv_bridges = node.lock()

            # one node can output/emit to multiple other nodes!
            # these connections may be unique, but at this point we don't really care about where they go, just that the output differs
            for con, bridge in send_bridges:
                bridges[str(con._emit_node)]['emit'][con._emit_port.key].append(bridge)

            # currently we only have one input connection per channel on each node
            # TODO: change this if we at some point allow multiple inputs per channel per node
            for con, bridge in recv_bridges:
                bridges[str(con._recv_node)]['recv'][con._recv_port.key] = bridge

        return bridges

    def start_all(self):
        hosts, processes, threads = list(zip(*[parse_location(n.compute_on) for n in self.nodes]))
        
        # not sure yet if this should be called externally yet...
        bridges = self.lock_all()
        # bridges = {}
        # ignore hosts for now, as we do not have an implementation for them atm
        # host_group = groupby(sorted(zip(hosts, self.nodes), key=lambda t: t[0]))
        # for host in hosts:

        process_groups = groupby(sorted(zip(processes, threads, self.nodes), key=lambda t: t[0]), key=lambda t: t[0])
        for process, process_group in process_groups:
            _, process_threads, process_nodes = list(zip(*list(process_group)))

            if not process == '':
                node_specific_bridges = [bridges[str(n)] for n in process_nodes]
                cmp = Processor_process(nodes=process_nodes, location=process, bridges=node_specific_bridges)
                cmp.setup()
                self.computers.append(cmp)
            else:
                thread_groups = groupby(sorted(zip(process_threads, process_nodes), key=lambda t: t[0]), key=lambda t: t[0])
                for thread, thread_group in thread_groups:
                    _, thread_nodes = list(zip(*list(thread_group)))
                    node_specific_bridges = [bridges[str(n)] for n in thread_nodes]
                    cmp = Processor_threads(nodes=thread_nodes, location=thread, bridges=node_specific_bridges)
                    cmp.setup()
                    self.computers.append(cmp)

        for cmp in self.computers:
            cmp.start()
                
    def is_finished(self):
        # print([(str(cmp), cmp.is_finished()) for cmp in self.computers])
        return all([cmp.is_finished() for cmp in self.computers])

    def join_all(self):
        for cmp in self.computers:
            cmp.join()

    def stop_all(self, stop_timeout=0.1, close_timeout=0.1):
        for cmp in self.computers:
            cmp.stop(timeout=stop_timeout)

        for cmp in self.computers:
            cmp.close(timeout=close_timeout)

        self.computers = []