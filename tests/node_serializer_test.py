import pytest
import json

from livenodes.node import Node
from livenodes import get_registry

registry = get_registry()

@registry.nodes.decorator
class SimpleNode(Node):
    channels_in = ["Data"]
    channels_out = ["Data"]


@pytest.fixture
def node_a():
    return SimpleNode(name="A")


class TestNodeOperations():

    def test_settings(self, node_a):
        # check direct serialization
        d = node_a.get_settings()
        assert set(d.keys()) == set(["class", "settings", "inputs"])
        assert json.dumps(d['settings']) == json.dumps({
            "name":
            "A",
            "compute_on":
            node_a.compute_on
        })
        assert len(d['inputs']) == 0

    def test_copy(self, node_a):
        # check copy
        node_a_copy = node_a.copy()
        assert node_a_copy is not None
        assert json.dumps(node_a.get_settings()) == json.dumps(
            node_a_copy.get_settings())

    def test_json(self, node_a):
        # check json format
        assert json.dumps(node_a.to_dict()) == json.dumps(
            {str(node_a): node_a.get_settings()})

        node_a_des = SimpleNode.from_dict(node_a.to_dict())
        assert node_a_des is not None
        assert json.dumps(node_a.to_dict()) == json.dumps(node_a_des.to_dict())
