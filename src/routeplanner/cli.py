"""routeplanner: shortest and fastest routes over a road network."""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from pathlib import Path

from . import __version__
from .graph import Graph, haversine
from .search import astar, bidirectional, by_distance, by_time, dijkstra

DEFAULT_NETWORK = Path("data/city")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="routeplanner", description=__doc__)
    parser.add_argument("--version", action="version", version=f"routeplanner {__version__}")
    parser.add_argument("-n", "--network", type=Path, default=DEFAULT_NETWORK,
                        help="directory holding nodes.csv and edges.csv")
    sub = parser.add_subparsers(dest="cmd", required=True)

    route = sub.add_parser("route", help="find a route between two nodes")
    route.add_argument("start")
    route.add_argument("goal")
    route.add_argument("--fastest", action="store_true", help="minimise time rather than distance")
    route.add_argument("-a", "--algorithm", default="astar",
                       choices=["astar", "dijkstra", "bidirectional"])
    route.add_argument("-w", "--weight", type=float, default=1.0,
                       help="inflate the heuristic; above 1.0 it stops being admissible")
    route.add_argument("--no-reopen", action="store_true",
                       help="close nodes permanently, as most tutorials do")

    compare = sub.add_parser("compare", help="run every algorithm on one pair")
    compare.add_argument("start")
    compare.add_argument("goal")
    compare.add_argument("--fastest", action="store_true")

    weights = sub.add_parser("weights", help="what inflating the heuristic costs and saves")
    weights.add_argument("-p", "--pairs", type=int, default=40)
    weights.add_argument("-s", "--seed", type=int, default=1)

    bench = sub.add_parser("bench", help="average expansions over random pairs")
    bench.add_argument("-p", "--pairs", type=int, default=100)
    bench.add_argument("-s", "--seed", type=int, default=1)

    sub.add_parser("stats", help="what is in the network")

    near = sub.add_parser("nearest", help="the nearest intersection to a coordinate")
    near.add_argument("lat", type=float)
    near.add_argument("lon", type=float)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Wraps the real work so piping into `head` — which closes the
    pipe early — ends quietly instead of printing a BrokenPipeError."""
    try:
        return _run(argv)
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    except (KeyError, ValueError, FileNotFoundError) as error:
        print(f"routeplanner: {error}", file=sys.stderr)
        return 2


def load(path: Path) -> Graph:
    if not (path / "nodes.csv").exists():
        raise FileNotFoundError(
            f"no network at {path} — run `python tools/make_network.py` first")
    return Graph.load(path)


def describe(graph: Graph, result, label: str, fastest: bool) -> None:
    route = result.route
    if not route.found:
        print(f"{label}: no route")
        return

    print(f"{label}")
    print(f"  {route.length_km:.2f} km, {route.minutes:.1f} minutes, "
          f"{len(route.edges)} segments")
    print(f"  {result.stats}")
    print()
    for name, distance in route.roads():
        print(f"    {distance:6.2f} km  {name}")
    if fastest:
        motorway = sum(d for name, d in route.roads() if "Motorway" in name)
        if motorway:
            print(f"\n  {motorway:.2f} km of that is motorway")


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    graph = load(args.network)
    cost = by_time if getattr(args, "fastest", False) else by_distance

    if args.cmd == "stats":
        stats = graph.stats()
        print(f"{stats['nodes']:,} intersections")
        print(f"{stats['edges']:,} directed edges")
        print(f"average out-degree {stats['average_degree']}")
        print(f"fastest road {stats['fastest_speed']:g} km/h")
        speeds: dict[float, int] = {}
        for edges in graph.out.values():
            for edge in edges:
                speeds[edge.speed] = speeds.get(edge.speed, 0) + 1
        print("\nedges by speed:")
        for speed in sorted(speeds, reverse=True):
            print(f"  {speed:6.0f} km/h  {speeds[speed]:>6,}")
        return 0

    if args.cmd == "nearest":
        from .graph import Node
        probe = Node("probe", args.lat, args.lon)
        node = min(graph.nodes.values(), key=lambda n: haversine(probe, n))
        print(f"{node.id}  {node.name}")
        print(f"  {haversine(probe, node) * 1000:.0f} m away "
              f"({node.lat:.5f}, {node.lon:.5f})")
        return 0

    if args.cmd == "route":
        if args.algorithm == "dijkstra":
            result = dijkstra(graph, args.start, args.goal, cost=cost)
        elif args.algorithm == "bidirectional":
            result = bidirectional(graph, args.start, args.goal, cost=cost)
        else:
            result = astar(graph, args.start, args.goal, cost=cost,
                           weight=args.weight, reopen=not args.no_reopen)
        label = f"{args.algorithm}, {'fastest' if cost is by_time else 'shortest'}"
        if args.weight != 1.0:
            label += f", heuristic x{args.weight:g}"
        describe(graph, result, label, cost is by_time)
        return 0 if result.found else 1

    if args.cmd == "compare":
        runs = [
            ("dijkstra", dijkstra(graph, args.start, args.goal, cost=cost)),
            ("a*", astar(graph, args.start, args.goal, cost=cost)),
            ("bidirectional", bidirectional(graph, args.start, args.goal, cost=cost)),
        ]
        unit = "min" if cost is by_time else "km"
        print(f"{args.start} -> {args.goal}   ({'fastest' if cost is by_time else 'shortest'})\n")
        print(f"{'algorithm':<16}{'expanded':>10}{'pushed':>10}{'peak':>8}{'cost (' + unit + ')':>14}")
        for name, result in runs:
            print(f"{name:<16}{result.stats.expanded:>10,}{result.stats.pushed:>10,}"
                  f"{result.stats.frontier_peak:>8,}{result.route.cost:>14.3f}")

        costs = {round(result.route.cost, 6) for _, result in runs}
        print(f"\nall three agree on the cost: {len(costs) == 1}")
        baseline = runs[0][1].stats.expanded
        for name, result in runs[1:]:
            print(f"{name} expanded {baseline / result.stats.expanded:.2f}x fewer nodes than dijkstra")
        return 0

    if args.cmd == "weights":
        pairs = sample_pairs(graph, args.pairs, args.seed)
        print(f"{args.pairs} random pairs, distance cost\n")
        print(f"{'weight':>7}{'expanded':>10}{'reexpanded':>12}{'km':>9}{'excess':>9}{'speedup':>9}")
        baseline_cost = baseline_expanded = None
        for weight in (1.0, 1.1, 1.2, 1.3, 1.5, 2.0, 3.0):
            expanded, reexpanded, costs = [], [], []
            for start, goal in pairs:
                result = astar(graph, start, goal, weight=weight)
                expanded.append(result.stats.expanded)
                reexpanded.append(result.stats.reexpanded)
                costs.append(result.route.cost)
            mean_expanded = statistics.mean(expanded)
            mean_cost = statistics.mean(costs)
            if baseline_cost is None:
                baseline_cost, baseline_expanded = mean_cost, mean_expanded
            print(f"{weight:>7.1f}{mean_expanded:>10.0f}{statistics.mean(reexpanded):>12.1f}"
                  f"{mean_cost:>9.3f}{100 * (mean_cost / baseline_cost - 1):>8.2f}%"
                  f"{baseline_expanded / mean_expanded:>8.2f}x")
        print("\nabove 1.0 the heuristic is no longer admissible, so the route is no")
        print("longer guaranteed shortest — and a small inflation is the worst of")
        print("both worlds, because the re-expansions cost more than the greed saves.")
        return 0

    pairs = sample_pairs(graph, args.pairs, args.seed)
    print(f"{len(pairs)} random pairs over {graph.size:,} nodes\n")
    print(f"{'algorithm':<16}{'mean expanded':>15}{'median saving':>16}{'seconds':>10}")

    results: dict[str, list[int]] = {}
    for name, run in (("dijkstra", dijkstra), ("a*", astar), ("bidirectional", bidirectional)):
        start_time = time.perf_counter()
        counts = [run(graph, start, goal).stats.expanded for start, goal in pairs]
        elapsed = time.perf_counter() - start_time
        results[name] = counts
        saving = statistics.median(
            d / c for d, c in zip(results["dijkstra"], counts, strict=True))
        print(f"{name:<16}{statistics.mean(counts):>15,.0f}{saving:>15.2f}x{elapsed:>10.2f}")
    return 0


def sample_pairs(graph: Graph, count: int, seed: int) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    ids = sorted(graph.nodes)
    pairs = []
    while len(pairs) < count:
        start, goal = rng.choice(ids), rng.choice(ids)
        if start != goal:
            pairs.append((start, goal))
    return pairs
