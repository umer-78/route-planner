"""Dijkstra, A* and bidirectional search over a road network.

All three share one implementation. Dijkstra is A* with a heuristic that always
returns zero, and writing them as separate functions means every fix has to be
made twice — which is how the two drift apart and the tests stop comparing like
with like.
"""

from __future__ import annotations

import heapq
from collections.abc import Callable
from dataclasses import dataclass, field

from .graph import Edge, Graph, Route

# A cost model turns an edge into a number. The two that matter are distance
# and travel time; a heuristic must be in the same units or it is meaningless.
CostModel = Callable[[Edge], float]
Heuristic = Callable[[str, str], float]


def by_distance(edge: Edge) -> float:
    return edge.length


def by_time(edge: Edge) -> float:
    return edge.minutes


@dataclass
class Stats:
    """What the search did, not just what it found.

    The point of A* is that it expands fewer nodes than Dijkstra. That claim is
    only checkable if the search counts, so it counts.
    """

    expanded: int = 0
    pushed: int = 0
    relaxed: int = 0
    reexpanded: int = 0
    frontier_peak: int = 0

    def __str__(self) -> str:
        return (f"{self.expanded:,} expanded, {self.pushed:,} pushed, "
                f"{self.relaxed:,} relaxed, peak frontier {self.frontier_peak:,}")


@dataclass
class Result:
    route: Route
    stats: Stats = field(default_factory=Stats)

    @property
    def found(self) -> bool:
        return self.route.found


def zero_heuristic(_a: str, _b: str) -> float:
    return 0.0


def search(graph: Graph, start: str, goal: str, *, cost: CostModel = by_distance,
           heuristic: Heuristic | None = None, reopen: bool = True) -> Result:
    """A*, or Dijkstra when the heuristic is zero.

    `reopen` decides what happens when a node already taken off the queue turns
    out to be reachable more cheaply. With an *admissible and consistent*
    heuristic it never does, so the flag costs nothing. With a merely admissible
    one it does, and closing a node permanently — the version in most tutorials
    — returns a path that is not the shortest. `test_an_inconsistent_heuristic_
    needs_reopening` builds a graph where that happens.
    """
    if start not in graph.nodes:
        raise KeyError(f"unknown start node {start!r}")
    if goal not in graph.nodes:
        raise KeyError(f"unknown goal node {goal!r}")

    estimate = heuristic or zero_heuristic
    stats = Stats()

    best: dict[str, float] = {start: 0.0}
    came: dict[str, Edge] = {}
    closed: set[str] = set()

    queue: list[tuple[float, int, str]] = [(estimate(start, goal), 0, start)]
    counter = 1
    stats.pushed = 1

    while queue:
        stats.frontier_peak = max(stats.frontier_peak, len(queue))
        _priority, _tie, node = heapq.heappop(queue)

        if node in closed:
            # A stale duplicate. The heap has no decrease-key, so a node
            # improved while it sat in the queue was pushed again rather than
            # updated; the better entry came out first. This is not a
            # re-expansion — a genuine improvement to a closed node removes it
            # from `closed` below, and only that is counted.
            continue
        closed.add(node)
        stats.expanded += 1

        if node == goal:
            return Result(rebuild(graph, came, start, goal, cost), stats)

        for edge in graph.neighbours(node):
            stats.relaxed += 1
            tentative = best[node] + cost(edge)
            if tentative >= best.get(edge.target, float("inf")):
                continue
            if edge.target in closed:
                if not reopen:
                    continue
                closed.discard(edge.target)
                stats.reexpanded += 1

            best[edge.target] = tentative
            came[edge.target] = edge
            counter += 1
            stats.pushed += 1
            heapq.heappush(queue, (tentative + estimate(edge.target, goal), counter, edge.target))

    return Result(Route(), stats)


def rebuild(graph: Graph, came: dict[str, Edge], start: str, goal: str,
            cost: CostModel) -> Route:
    edges: list[Edge] = []
    node = goal
    while node != start:
        edge = came[node]
        edges.append(edge)
        node = edge.source
    edges.reverse()

    nodes = [start] + [edge.target for edge in edges]
    return Route(nodes=nodes, edges=edges, cost=sum(cost(edge) for edge in edges))


def dijkstra(graph: Graph, start: str, goal: str, *, cost: CostModel = by_distance) -> Result:
    return search(graph, start, goal, cost=cost)


def astar(graph: Graph, start: str, goal: str, *, cost: CostModel = by_distance,
          weight: float = 1.0, reopen: bool = True) -> Result:
    """A* with the straight-line heuristic matched to the cost model.

    `weight` above 1 makes the heuristic inadmissible on purpose: the search
    gets greedier and finishes sooner, and the path it returns is no longer
    guaranteed shortest. The README measures both halves of that trade.
    """
    return search(graph, start, goal, cost=cost,
                  heuristic=straight_line(graph, cost, weight), reopen=reopen)


def straight_line(graph: Graph, cost: CostModel, weight: float = 1.0) -> Heuristic:
    """A heuristic in the same units as the cost model.

    For distance it is the great-circle distance, which no road can beat. For
    travel time it is that distance divided by the fastest speed *anywhere in
    the graph* — dividing by anything slower would overestimate and break the
    guarantee.
    """
    fastest = graph.fastest_speed()
    probe = Edge("a", "b", 1.0, fastest)
    per_km = cost(probe)          # 1.0 for distance, 60/fastest for minutes

    def estimate(node: str, goal: str) -> float:
        return weight * per_km * graph.distance(node, goal)

    return estimate


def bidirectional(graph: Graph, start: str, goal: str, *,
                  cost: CostModel = by_distance) -> Result:
    """Dijkstra from both ends at once, meeting in the middle.

    Two searches of radius r/2 cover far less ground than one of radius r, which
    is where the saving comes from. The part that is easy to get wrong is the
    stopping rule: the first node both sides have settled is *not* necessarily
    on the shortest path. The search must continue until the two frontiers'
    smallest keys together exceed the best complete path found so far, and every
    edge relaxed before then has to be checked against it.
    """
    if start not in graph.nodes or goal not in graph.nodes:
        raise KeyError("unknown node")
    stats = Stats()

    if start == goal:
        return Result(Route(nodes=[start], edges=[], cost=0.0), stats)

    forward = {start: 0.0}
    backward = {goal: 0.0}
    cameF: dict[str, Edge] = {}
    cameB: dict[str, Edge] = {}
    doneF: set[str] = set()
    doneB: set[str] = set()

    queueF: list[tuple[float, int, str]] = [(0.0, 0, start)]
    queueB: list[tuple[float, int, str]] = [(0.0, 0, goal)]
    counter = 0
    stats.pushed = 2

    best_cost = float("inf")
    meeting: str | None = None

    while queueF and queueB:
        stats.frontier_peak = max(stats.frontier_peak, len(queueF) + len(queueB))
        if queueF[0][0] + queueB[0][0] >= best_cost:
            break

        # Always advance the side with less ground covered, which keeps the two
        # radii balanced and is what makes the saving roughly square-root.
        if queueF[0][0] <= queueB[0][0]:
            _key, _tie, node = heapq.heappop(queueF)
            if node in doneF:
                continue
            doneF.add(node)
            stats.expanded += 1

            for edge in graph.neighbours(node):
                stats.relaxed += 1
                tentative = forward[node] + cost(edge)
                if tentative < forward.get(edge.target, float("inf")):
                    forward[edge.target] = tentative
                    cameF[edge.target] = edge
                    counter += 1
                    stats.pushed += 1
                    heapq.heappush(queueF, (tentative, counter, edge.target))
                if edge.target in backward and tentative + backward[edge.target] < best_cost:
                    best_cost = tentative + backward[edge.target]
                    meeting = edge.target
        else:
            _key, _tie, node = heapq.heappop(queueB)
            if node in doneB:
                continue
            doneB.add(node)
            stats.expanded += 1

            for edge in graph.incoming(node):
                stats.relaxed += 1
                tentative = backward[node] + cost(edge)
                if tentative < backward.get(edge.source, float("inf")):
                    backward[edge.source] = tentative
                    cameB[edge.source] = edge
                    counter += 1
                    stats.pushed += 1
                    heapq.heappush(queueB, (tentative, counter, edge.source))
                if edge.source in forward and tentative + forward[edge.source] < best_cost:
                    best_cost = tentative + forward[edge.source]
                    meeting = edge.source

    if meeting is None:
        return Result(Route(), stats)

    edges: list[Edge] = []
    node = meeting
    while node != start:
        edge = cameF[node]
        edges.append(edge)
        node = edge.source
    edges.reverse()

    node = meeting
    while node != goal:
        edge = cameB[node]
        edges.append(edge)
        node = edge.target

    nodes = [start] + [edge.target for edge in edges]
    return Result(Route(nodes=nodes, edges=edges,
                        cost=sum(cost(edge) for edge in edges)), stats)
