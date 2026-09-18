from pathlib import Path

import pytest

from routeplanner import Edge, Graph, Node

NETWORK = Path(__file__).resolve().parent.parent / "data" / "city"


@pytest.fixture(scope="session")
def city():
    return Graph.load(NETWORK)


@pytest.fixture()
def tiny():
    """Four nodes in a line, with a shortcut that is longer but faster.

      A --1km/35--> B --1km/35--> C --1km/35--> D
      A ----------- 4km at 100 km/h ----------> D

    The shortest route is 3 km and the fastest is the 4 km one, which is the
    smallest graph that can tell the two cost models apart.
    """
    graph = Graph()
    for i, name in enumerate("ABCD"):
        graph.add_node(Node(name, 31.0 + i * 0.009, 74.0))
    for a, b in zip("ABC", "BCD", strict=True):
        graph.add_edge(Edge(a, b, 1.0, 35.0, "local"))
    graph.add_edge(Edge("A", "D", 4.0, 100.0, "motorway"))
    return graph


@pytest.fixture()
def inconsistent():
    """A graph with an admissible but inconsistent heuristic.

    Found by search over small random graphs, then reduced by hand. The
    heuristic never overestimates — h(A)=1 against a true 5, h(C)=7 against a
    true 7, h(S)=2 against a true 12 — but the edge C->A costs 2 while h(C) - h(A)
    is 6, which breaks consistency. That is enough to make an A* that closes
    nodes permanently return the wrong answer.
    """
    graph = Graph()
    for i, name in enumerate(["S", "A", "C", "G"]):
        graph.add_node(Node(name, 31.0, 74.0 + i * 0.01))
    for source, target, length in [("S", "A", 8.0), ("S", "C", 5.0),
                                   ("C", "A", 2.0), ("A", "G", 5.0)]:
        graph.add_edge(Edge(source, target, length, 60.0))

    estimates = {"S": 2.0, "A": 1.0, "C": 7.0, "G": 0.0}
    return graph, (lambda node, _goal: estimates[node]), estimates
