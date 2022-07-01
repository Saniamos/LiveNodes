import numpy as np
import queue

from graphviz import Digraph
from PIL import Image
from io import BytesIO

from .connection import Connection
from .port import Port, Port_Collection

class Connectionist():
    channels_in = Port_Collection(Port('port 1'))
    channels_out = Port_Collection(Port('port 1'))

    def __init__(self):
        self.input_connections = []
        self.output_connections = []

    def connect_inputs_to(self, emitting_node: 'Connectionist'):
        """
        Add all matching channels from the emitting nodes to self as input.
        Main function to connect two nodes together with add_input.
        """

        channels_in_common = set(self.channels_in).intersection(
            emitting_node.channels_out)
        for channel in channels_in_common:
            self.add_input(emitting_node=emitting_node,
                           emitting_channel=channel,
                           receiving_channel=channel)

    def add_input(self,
                  emitting_node: 'Connectionist',
                  emitting_channel: Port,
                  receiving_channel: Port):
        """
        Add one input to self via attributes.
        Main function to connect two nodes together with connect_inputs_to
        """

        if emitting_channel not in emitting_node.channels_out:
            raise ValueError(
                f"Emitting Channel not present on given emitting node ({str(emitting_node)}). Got",
                emitting_channel)

        if receiving_channel not in self.channels_in:
            raise ValueError(
                f"Receiving Channel not present on node ({str(self)}). Got",
                receiving_channel)

        # This is too simple, as when connecting two nodes, we really are connecting two sub-graphs, which need to be checked
        # TODO: implement this proper
        # nodes_in_graph = emitting_node.discover_full(emitting_node)
        # if list(map(str, nodes_in_graph)):
        #     raise ValueError("Name already in parent sub-graph. Got:", str(self))

        # Create connection instance
        connection = Connection(emitting_node,
                                self,
                                emitting_channel=emitting_channel,
                                receiving_channel=receiving_channel)

        if len(list(filter(connection.__eq__, self.input_connections))) > 0:
            raise ValueError("Connection already exists.")

        # Find existing connections of these nodes and channels
        counter = len(list(filter(connection._similar,
                                  self.input_connections)))
        # Update counter
        connection._set_connection_counter(counter)

        # Not sure if this'll actually work, otherwise we should name them _add_output
        emitting_node._add_output(connection)
        self.input_connections.append(connection)

    def remove_all_inputs(self):
        for con in self.input_connections:
            self.remove_input_by_connection(con)

    def remove_input(self,
                     emitting_node,
                     emitting_channel: Port,
                     receiving_channel: Port,
                     connection_counter=0):
        """
        Remove an input from self via attributes
        """
        return self.remove_input_by_connection(
            Connection(emitting_node,
                       self,
                       emitting_channel=emitting_channel,
                       receiving_channel=receiving_channel,
                       connection_counter=connection_counter))

    def remove_input_by_connection(self, connection):
        """
        Remove an input from self via a connection
        """
        if not isinstance(connection, Connection):
            raise ValueError("Passed argument is not a connection. Got",
                             connection)

        cons = list(filter(connection.__eq__, self.input_connections))
        if len(cons) == 0:
            raise ValueError("Passed connection is not in inputs. Got",
                             connection)

        # Remove first
        # -> in case something goes wrong on the parents side, the connection remains intact
        cons[0]._emitting_node._remove_output(cons[0])
        self.input_connections.remove(cons[0])


    def _add_output(self, connection):
        """
        Add an output to self. 
        Only ever called by another node, that wants this node as input
        """
        self.output_connections.append(connection)

    def _remove_output(self, connection):
        """
        Remove an output from self. 
        Only ever called by another node, that wants this node as input
        """
        cons = list(filter(connection.__eq__, self.output_connections))
        if len(cons) == 0:
            raise ValueError("Passed connection is not in outputs. Got",
                             connection)
        self.output_connections.remove(connection)

    def _is_input_connected(self, receiving_channel: Port):
        return any([
            x._receiving_channel == receiving_channel
            for x in self.input_connections
        ])


    @staticmethod
    def remove_discovered_duplicates(nodes):
        return list(set(nodes))

    @staticmethod
    def sort_discovered_nodes(nodes):
        return list(sorted(nodes, key=lambda x: f"{len(x.discover_output_deps(x))}_{str(x)}"))

    @staticmethod
    def discover_output_deps(node):
        # TODO: consider adding a channel parameter, ie only consider dependents of this channel
        """
        Find all nodes who depend on our output
        """
        if len(node.output_connections) > 0:
            output_deps = [
                con._receiving_node.discover_output_deps(con._receiving_node)
                for con in node.output_connections
            ]
            return [node] + list(np.concatenate(output_deps))
        return [node]

    @staticmethod
    def discover_input_deps(node):
        if len(node.input_connections) > 0:
            input_deps = [
                con._emitting_node.discover_input_deps(con._emitting_node)
                for con in node.input_connections
            ]
            return [node] + list(np.concatenate(input_deps))
        return [node]

    @staticmethod
    def discover_neighbors(node):
        childs = [con._receiving_node for con in node.output_connections]
        parents = [con._emitting_node for con in node.input_connections]
        return node.remove_discovered_duplicates([node] + childs + parents)

    @staticmethod
    def discover_graph(node):
        discovered_nodes = node.discover_neighbors(node)
        found_nodes = [node]
        stack = queue.Queue()
        for node in discovered_nodes:
            if not node in found_nodes:
                found_nodes.append(node)
                for n in node.discover_neighbors(node):
                    if not n in discovered_nodes:
                        discovered_nodes.append(n)
                        stack.put(n)

        return node.sort_discovered_nodes(node.remove_discovered_duplicates(found_nodes))

    def requires_input_of(self, node):
        # self is always a child of itself
        return node in self.discover_input_deps(self)

    def provides_input_to(self, node):
        # self is always a parent of itself
        return node in self.discover_output_deps(self)


    def dot_graph(self, nodes, name=False, transparent_bg=False):
        graph_attr = {"size": "10,10!", "ratio": "fill"}
        if transparent_bg: graph_attr["bgcolor"] = "#00000000"
        dot = Digraph(format='png', strict=False, graph_attr=graph_attr)

        for node in nodes:
            shape = 'rect'
            if len(node.channels_in) <= 0:
                shape = 'invtrapezium'
            if len(node.channels_out) <= 0:
                shape = 'trapezium'
            disp_name = node.name if name else str(node)
            dot.node(str(node), disp_name, shape=shape, style='rounded')

        # Second pass: add edges based on output links
        for node in nodes:
            for con in node.output_connections:
                dot.edge(str(node),
                         str(con._receiving_node),
                         label=str(con._emitting_channel))

        return Image.open(BytesIO(dot.pipe()))

    def dot_graph_full(self, **kwargs):
        return self.dot_graph(self.discover_graph(self), **kwargs)