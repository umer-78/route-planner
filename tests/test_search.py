"""Dijkstra, A* and bidirectional search: that they agree, and where they stop agreeing."""

from __future__ import annotations

import random

import pytest

from routeplanner import Edge, Graph, Node, astar, bidirectional, by_distance, by_time, dijkstra
from routeplanner.search import search, straight_line


def pairs(graph: Graph, count: int, seed: int = 0) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    ids = sorted(graph.nodes)
    out = []
    while len(out) < count:
        start, goal = rng.choice(ids), rng.choice(ids)
        if start != goal:
            out.append((start, goal))
    return out


# -- they must all find the same cost ----------------------------------------

def test_all_three_algorithms_agree(city):
    """The property that makes the comparison meaningful. A* expanding fewer
    nodes is only interesting if it reaches the same answer."""
    for start, goal in pairs(city, 60, seed=1):
        by_dijkstra = dijkstra(city, start, goal)
        by_astar = astar(city, start, goal)
        by_both_ends = bidirectional(city, start, goal)

        assert by_dijkstra.found
        assert by_astar.route.cost == pytest.approx(by_dijkstra.route.cost, abs=1e-9)
        assert by_both_ends.route.cost == pytest.approx(by_dijkstra.route.cost, abs=1e-9)


def test_all_three_agree_on_travel_time_too(city):
    for start, goal in pairs(city, 30, seed=2):
        costs = {
            round(dijkstra(city, start, goal, cost=by_time).route.cost, 9),
            round(astar(city, start, goal, cost=by_time).route.cost, 9),
            round(bidirectional(city, start, goal, cost=by_time).route.cost, 9),
        }
        assert len(costs) == 1


def test_a_route_is_a_real_path_through_the_graph(city):
    for start, goal in pairs(city, 20, seed=3):
        route = astar(city, start, goal).route
        assert route.nodes[0] == start
        assert route.nodes[-1] == goal
        for edge, source, target in zip(route.edges, route.nodes[:-1], route.nodes[1:], strict=True):
            assert edge.source == source
            assert edge.target == target
            assert edge in city.neighbours(source)


def test_the_reported_cost_matches_the_edges(city):
    for start, goal in pairs(city, 20, seed=4):
        route = astar(city, start, goal).route
        assert route.cost == pytest.approx(sum(e.length for e in route.edges))


# -- A* expands fewer nodes --------------------------------------------------

def test_astar_never_expands_more_than_dijkstra(city):
    """With an admissible heuristic it cannot: every node A* expands has
    f = g + h no greater than the optimal cost, and Dijkstra expands every node
    with g no greater than that."""
    for start, goal in pairs(city, 40, seed=5):
        assert astar(city, start, goal).stats.expanded <= dijkstra(city, start, goal).stats.expanded


def test_astar_usually_expands_far_fewer(city):
    savings = []
    for start, goal in pairs(city, 40, seed=6):
        d = dijkstra(city, start, goal).stats.expanded
        a = astar(city, start, goal).stats.expanded
        savings.append(d / a)

    savings.sort()
    median = savings[len(savings) // 2]
    assert median > 2.0, f"median saving only {median:.2f}x"


def test_a_consistent_heuristic_causes_no_reexpansions(city):
    """The straight-line distance is consistent, not merely admissible, so no
    node is ever reached more cheaply after it has been settled. If this starts
    failing, the heuristic has stopped being what the README says it is."""
    for start, goal in pairs(city, 30, seed=7):
        assert astar(city, start, goal).stats.reexpanded == 0
        assert dijkstra(city, start, goal).stats.reexpanded == 0


# -- the inconsistent heuristic ----------------------------------------------

def test_an_inconsistent_heuristic_needs_reopening(inconsistent):
    """The failure that the `reopen` flag exists for.

    The heuristic is admissible — it never overestimates — so A* is *supposed*
    to be exact. But it is inconsistent across one edge, which means a node can
    be reached more cheaply after it has been settled. Closing nodes permanently,
    as most tutorial implementations do, throws that cheaper route away.
    """
    graph, heuristic, _ = inconsistent

    correct = search(graph, "S", "G", cost=by_distance, heuristic=heuristic, reopen=True)
    wrong = search(graph, "S", "G", cost=by_distance, heuristic=heuristic, reopen=False)

    assert correct.route.nodes == ["S", "C", "A", "G"]
    assert correct.route.cost == pytest.approx(12.0)

    assert wrong.route.nodes == ["S", "A", "G"]
    assert wrong.route.cost == pytest.approx(13.0)
    assert wrong.route.cost > correct.route.cost


def test_the_heuristic_in_that_example_really_is_admissible(inconsistent):
    """Otherwise the example proves nothing: an inadmissible heuristic is
    allowed to return a suboptimal path, reopening or not."""
    graph, _, estimates = inconsistent
    for node in graph.nodes:
        if node == "G":
            continue
        true_cost = dijkstra(graph, node, "G").route.cost
        assert estimates[node] <= true_cost + 1e-9, f"h({node}) overestimates"


def test_the_heuristic_in_that_example_really_is_inconsistent(inconsistent):
    graph, _, estimates = inconsistent
    violations = [(edge.source, edge.target)
                  for edges in graph.out.values() for edge in edges
                  if estimates[edge.source] > edge.length + estimates[edge.target] + 1e-9]
    assert violations == [("C", "A")]


def test_reopening_costs_an_extra_expansion_there(inconsistent):
    graph, heuristic, _ = inconsistent
    correct = search(graph, "S", "G", cost=by_distance, heuristic=heuristic, reopen=True)
    assert correct.stats.reexpanded == 1


# -- the inflated heuristic --------------------------------------------------

def test_an_inflated_heuristic_is_faster_and_worse(city):
    """The trade a weighted A* makes, measured rather than assumed."""
    sample = pairs(city, 30, seed=8)

    exact = [astar(city, s, g) for s, g in sample]
    greedy = [astar(city, s, g, weight=2.0) for s, g in sample]

    expanded_exact = sum(r.stats.expanded for r in exact)
    expanded_greedy = sum(r.stats.expanded for r in greedy)
    assert expanded_greedy < expanded_exact / 4

    cost_exact = sum(r.route.cost for r in exact)
    cost_greedy = sum(r.route.cost for r in greedy)
    assert cost_greedy > cost_exact                  # it really is worse
    assert cost_greedy < cost_exact * 1.02           # but only just


def test_a_weighted_route_stays_within_the_weight(city):
    """The guarantee weighted A* does still give: at most `weight` times the
    optimal cost. Losing that would make the trade unbounded and useless."""
    for start, goal in pairs(city, 20, seed=9):
        optimal = astar(city, start, goal).route.cost
        for weight in (1.5, 2.0, 3.0):
            inflated = astar(city, start, goal, weight=weight).route.cost
            assert inflated <= weight * optimal + 1e-9


def test_a_small_inflation_costs_more_than_it_saves(city):
    """The non-obvious one. Inflating by 1.2 makes the heuristic inconsistent
    without making the search meaningfully greedier, so it pays for hundreds of
    re-expansions and gets nothing: it expands *more* nodes than the exact
    search it was supposed to speed up."""
    sample = pairs(city, 25, seed=10)

    exact = sum(astar(city, s, g).stats.expanded for s, g in sample)
    barely = sum(astar(city, s, g, weight=1.2).stats.expanded for s, g in sample)
    greedy = sum(astar(city, s, g, weight=2.0).stats.expanded for s, g in sample)

    assert barely > exact, "expected the mild inflation to be slower, not faster"
    assert greedy < exact


def test_the_mild_inflation_is_slower_because_of_reexpansions(city):
    sample = pairs(city, 25, seed=10)
    assert sum(astar(city, s, g).stats.reexpanded for s, g in sample) == 0
    assert sum(astar(city, s, g, weight=1.2).stats.reexpanded for s, g in sample) > 100


# -- the two cost models -----------------------------------------------------

def test_the_fastest_route_is_not_the_shortest(tiny):
    shortest = astar(tiny, "A", "D", cost=by_distance).route
    fastest = astar(tiny, "A", "D", cost=by_time).route

    assert shortest.nodes == ["A", "B", "C", "D"]
    assert shortest.length_km == pytest.approx(3.0)

    assert fastest.nodes == ["A", "D"]
    assert fastest.length_km == pytest.approx(4.0)
    assert fastest.minutes < shortest.minutes


def test_on_the_real_network_they_usually_differ(city):
    sample = pairs(city, 60, seed=11)
    differ = sum(1 for s, g in sample
                 if astar(city, s, g, cost=by_distance).route.nodes
                 != astar(city, s, g, cost=by_time).route.nodes)
    assert differ > len(sample) // 2


def test_the_fastest_route_is_never_slower(city):
    for start, goal in pairs(city, 25, seed=12):
        shortest = astar(city, start, goal, cost=by_distance).route
        fastest = astar(city, start, goal, cost=by_time).route
        assert fastest.minutes <= shortest.minutes + 1e-9
        assert shortest.length_km <= fastest.length_km + 1e-9


def test_the_time_heuristic_divides_by_the_fastest_speed_in_the_graph(tiny):
    """Dividing by anything slower overestimates the remaining time, and an
    overestimate is exactly what breaks A*'s guarantee."""
    estimate = straight_line(tiny, by_time)
    straight = tiny.distance("A", "D")
    assert estimate("A", "D") == pytest.approx(60.0 * straight / 100.0)

    true_time = astar(tiny, "A", "D", cost=by_time).route.minutes
    assert estimate("A", "D") <= true_time


# -- edges and failures ------------------------------------------------------

def test_a_route_to_itself_is_empty(city):
    for run in (dijkstra, astar, bidirectional):
        route = run(city, "n0505", "n0505").route
        assert route.nodes == ["n0505"]
        assert route.cost == 0.0


def test_no_route_when_there_is_none():
    graph = Graph()
    for name in ("a", "b", "island"):
        graph.add_node(Node(name, 31.0, 74.0))
    graph.add_road("a", "b", 50.0)

    for run in (dijkstra, astar, bidirectional):
        result = run(graph, "a", "island")
        assert not result.found
        assert result.route.cost == 0.0


def test_a_one_way_street_is_respected():
    graph = Graph()
    for i, name in enumerate("ab"):
        graph.add_node(Node(name, 31.0 + i * 0.01, 74.0))
    graph.add_edge(Edge("a", "b", 1.0, 50.0))

    assert astar(graph, "a", "b").found
    assert not astar(graph, "b", "a").found


def test_bidirectional_search_respects_direction():
    """It walks backwards from the goal, so it has to follow incoming edges the
    right way round. Getting this wrong finds routes that do not exist."""
    graph = Graph()
    for i, name in enumerate("abc"):
        graph.add_node(Node(name, 31.0 + i * 0.01, 74.0))
    graph.add_edge(Edge("a", "b", 1.0, 50.0))
    graph.add_edge(Edge("b", "c", 1.0, 50.0))

    assert bidirectional(graph, "a", "c").found
    assert not bidirectional(graph, "c", "a").found


def test_an_unknown_node_is_an_error(city):
    with pytest.raises(KeyError):
        astar(city, "nowhere", "n0000")
    with pytest.raises(KeyError):
        astar(city, "n0000", "nowhere")


def test_the_first_meeting_point_is_not_always_on_the_shortest_path():
    """Why bidirectional search cannot stop at the first node both sides have
    settled. The obvious stopping rule returns a path through that node; the
    correct one keeps going until the two frontier keys together exceed the best
    complete path found so far.
    """
    graph = Graph()
    for i, name in enumerate(["s", "m", "x", "y", "t"]):
        graph.add_node(Node(name, 31.0, 74.0 + i * 0.01))

    # Through m: 5 + 5 = 10. Through x and y: 4 + 1 + 4 = 9.
    for source, target, length in [("s", "m", 5.0), ("m", "t", 5.0),
                                   ("s", "x", 4.0), ("x", "y", 1.0), ("y", "t", 4.0)]:
        graph.add_edge(Edge(source, target, length, 50.0))
        graph.add_edge(Edge(target, source, length, 50.0))

    result = bidirectional(graph, "s", "t")
    assert result.route.cost == pytest.approx(9.0)
    assert result.route.nodes == ["s", "x", "y", "t"]


def test_stats_are_counted(city):
    result = astar(city, "n0000", "n2020")
    assert result.stats.expanded > 0
    assert result.stats.pushed >= result.stats.expanded
    assert result.stats.relaxed > 0
    assert result.stats.frontier_peak > 0
    assert "expanded" in str(result.stats)


def test_expanded_never_exceeds_the_node_count(city):
    """A search that expands more nodes than the graph has is counting stale
    queue entries as expansions, which makes every comparison meaningless."""
    for start, goal in pairs(city, 20, seed=13):
        assert dijkstra(city, start, goal).stats.expanded <= city.size
        assert astar(city, start, goal).stats.expanded <= city.size
