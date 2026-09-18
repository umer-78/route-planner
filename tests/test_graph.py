"""The network itself: geometry, structure and persistence."""

from __future__ import annotations

import math
import random

import pytest

from routeplanner import Edge, Graph, Node, haversine
from routeplanner.search import astar, by_distance

# -- geometry ----------------------------------------------------------------

def test_haversine_is_zero_for_one_point():
    node = Node("a", 31.5, 74.3)
    assert haversine(node, node) == 0.0


def test_haversine_is_symmetric():
    a, b = Node("a", 31.5, 74.3), Node("b", 24.8, 67.0)
    assert haversine(a, b) == pytest.approx(haversine(b, a))


def test_haversine_against_a_known_distance():
    """Lahore to Karachi is about 1,020 km great-circle."""
    lahore = Node("lhe", 31.5204, 74.3587)
    karachi = Node("khi", 24.8607, 67.0011)
    assert haversine(lahore, karachi) == pytest.approx(1020, abs=15)


def test_a_degree_of_latitude_is_about_111_km():
    assert haversine(Node("a", 0.0, 0.0), Node("b", 1.0, 0.0)) == pytest.approx(111.2, abs=0.5)


def test_a_degree_of_longitude_shrinks_with_latitude():
    """The reason Euclidean distance on raw coordinates is not admissible.

    A degree of longitude is 111 km at the equator and 95 km in Lahore. Treating
    the two axes alike overestimates east-west distance away from the equator,
    and an overestimating heuristic makes A* return the wrong route.
    """
    at_equator = haversine(Node("a", 0.0, 0.0), Node("b", 0.0, 1.0))
    at_lahore = haversine(Node("a", 31.5, 0.0), Node("b", 31.5, 1.0))
    assert at_equator == pytest.approx(111.3, abs=0.5)
    assert at_lahore == pytest.approx(at_equator * math.cos(math.radians(31.5)), rel=0.01)
    assert at_lahore < at_equator


def test_haversine_obeys_the_triangle_inequality():
    rng = random.Random(0)
    for _ in range(300):
        points = [Node(str(i), rng.uniform(-80, 80), rng.uniform(-180, 180)) for i in range(3)]
        a, b, c = points
        assert haversine(a, c) <= haversine(a, b) + haversine(b, c) + 1e-9


# -- the heuristic is admissible on the real network -------------------------

def test_the_straight_line_never_exceeds_the_road_distance(city):
    """Admissibility, checked rather than assumed.

    A* is only exact when the heuristic never overestimates. Here that means the
    great-circle distance between two intersections must never exceed the actual
    driving distance between them — over 150 random pairs of the real network.
    """
    rng = random.Random(1)
    ids = sorted(city.nodes)

    for _ in range(150):
        start, goal = rng.choice(ids), rng.choice(ids)
        if start == goal:
            continue
        route = astar(city, start, goal, cost=by_distance).route
        assert route.found
        assert city.distance(start, goal) <= route.length_km + 1e-9


# -- structure ---------------------------------------------------------------

def test_a_two_way_road_is_two_directed_edges(tiny):
    graph = Graph()
    graph.add_node(Node("a", 31.0, 74.0))
    graph.add_node(Node("b", 31.01, 74.0))
    graph.add_road("a", "b", 50.0, "Mall Road")

    assert len(graph.neighbours("a")) == 1
    assert len(graph.neighbours("b")) == 1
    assert graph.edges == 2


def test_a_one_way_street_is_only_traversable_one_way(tiny):
    assert [edge.target for edge in tiny.neighbours("A")] == ["B", "D"]
    assert tiny.neighbours("D") == []


def test_incoming_edges_are_tracked(tiny):
    """Bidirectional search walks backwards from the goal, so it needs them."""
    assert [edge.source for edge in tiny.incoming("D")] == ["C", "A"]


def test_an_edge_to_an_unknown_node_is_rejected():
    graph = Graph()
    graph.add_node(Node("a", 31.0, 74.0))
    with pytest.raises(KeyError, match="unknown node"):
        graph.add_edge(Edge("a", "nowhere", 1.0, 50.0))


def test_a_negative_length_is_rejected():
    graph = Graph()
    for name in "ab":
        graph.add_node(Node(name, 31.0, 74.0))
    with pytest.raises(ValueError, match="shorter than nothing"):
        graph.add_edge(Edge("a", "b", -1.0, 50.0))


def test_a_non_positive_speed_is_rejected():
    graph = Graph()
    for name in "ab":
        graph.add_node(Node(name, 31.0, 74.0))
    with pytest.raises(ValueError, match="positive speed"):
        graph.add_edge(Edge("a", "b", 1.0, 0.0))


def test_edge_minutes():
    assert Edge("a", "b", 30.0, 60.0).minutes == pytest.approx(30.0)
    assert Edge("a", "b", 1.0, 120.0).minutes == pytest.approx(0.5)


def test_fastest_speed_is_the_maximum_anywhere(tiny):
    """Not the speed of the road the search happens to be standing on."""
    assert tiny.fastest_speed() == 100.0


def test_fastest_speed_of_an_empty_graph_does_not_divide_by_zero():
    assert Graph().fastest_speed() == 1.0


# -- the sample network ------------------------------------------------------

def test_the_sample_network_loaded(city):
    assert city.size == 1600
    assert city.edges == 5914


def test_every_intersection_can_reach_every_other(city):
    """The generator repairs anything its own thinning cut off, and this is the
    check that it actually did. A router cannot be exercised on a network where
    some pairs have no answer for reasons that are an accident of the seed."""
    seen = {"n0000"}
    stack = ["n0000"]
    while stack:
        node = stack.pop()
        for edge in city.neighbours(node):
            if edge.target not in seen:
                seen.add(edge.target)
                stack.append(edge.target)
    assert len(seen) == city.size


def test_every_edge_refers_to_a_real_node(city):
    for edges in city.out.values():
        for edge in edges:
            assert edge.source in city.nodes
            assert edge.target in city.nodes


def test_the_network_has_three_road_classes(city):
    speeds = {edge.speed for edges in city.out.values() for edge in edges}
    assert speeds == {35.0, 60.0, 100.0}


def test_edge_lengths_match_the_coordinates(city):
    for edges in list(city.out.values())[:50]:
        for edge in edges:
            assert edge.length == pytest.approx(city.distance(edge.source, edge.target), abs=1e-3)


# -- persistence -------------------------------------------------------------

def test_save_and_load_round_trip(city, tmp_path):
    reloaded = Graph.load(city.save(tmp_path / "copy"))
    assert reloaded.stats() == city.stats()

    for node_id, node in city.nodes.items():
        assert reloaded.nodes[node_id].lat == pytest.approx(node.lat, abs=1e-6)
        assert reloaded.nodes[node_id].name == node.name


def test_a_reloaded_network_routes_identically(city, tmp_path):
    reloaded = Graph.load(city.save(tmp_path / "copy"))
    before = astar(city, "n0101", "n3030").route
    after = astar(reloaded, "n0101", "n3030").route
    assert after.nodes == before.nodes
    assert after.cost == pytest.approx(before.cost, abs=1e-3)


# -- routes ------------------------------------------------------------------

def test_an_empty_route_is_not_found():
    from routeplanner import Route
    assert not Route().found


def test_roads_collapses_consecutive_segments_of_one_road(city):
    route = astar(city, "n0000", "n0010").route
    names = [name for name, _ in route.roads()]
    assert len(names) == len(set(names)) or names == sorted(set(names), key=names.index)
    assert all(names[i] != names[i + 1] for i in range(len(names) - 1))


def test_route_length_and_time_agree_with_its_edges(city):
    route = astar(city, "n0505", "n2525").route
    assert route.length_km == pytest.approx(sum(e.length for e in route.edges))
    assert route.minutes == pytest.approx(sum(e.minutes for e in route.edges))
