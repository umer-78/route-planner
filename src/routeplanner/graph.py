"""The road network: nodes with coordinates, directed edges with a cost."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Node:
    id: str
    lat: float
    lon: float
    name: str = ""


@dataclass(frozen=True)
class Edge:
    """A one-way stretch of road.

    `length` is kilometres and `speed` km/h, kept apart rather than collapsed
    into a single travel time, because the two cost models a router needs —
    shortest distance and fastest route — disagree, and a graph that stores only
    one of them cannot answer for the other.
    """

    source: str
    target: str
    length: float
    speed: float
    name: str = ""

    @property
    def minutes(self) -> float:
        return 60.0 * self.length / self.speed


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.out: dict[str, list[Edge]] = {}
        self.into: dict[str, list[Edge]] = {}

    # -- building ---------------------------------------------------------

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.out.setdefault(node.id, [])
        self.into.setdefault(node.id, [])

    def add_edge(self, edge: Edge) -> None:
        for end in (edge.source, edge.target):
            if end not in self.nodes:
                raise KeyError(f"edge refers to unknown node {end!r}")
        if edge.length < 0:
            raise ValueError("an edge cannot be shorter than nothing")
        if edge.speed <= 0:
            raise ValueError("an edge needs a positive speed")
        self.out[edge.source].append(edge)
        self.into[edge.target].append(edge)

    def add_road(self, a: str, b: str, speed: float, name: str = "") -> None:
        """A two-way road: two edges, because the graph is directed underneath.

        Modelling a two-way street as one undirected edge works until the first
        one-way street, and then every algorithm has to learn about a special
        case. Two directed edges cost one extra object and no special cases.
        """
        length = self.distance(a, b)
        self.add_edge(Edge(a, b, length, speed, name))
        self.add_edge(Edge(b, a, length, speed, name))

    # -- geometry ---------------------------------------------------------

    def distance(self, a: str, b: str) -> float:
        return haversine(self.nodes[a], self.nodes[b])

    # -- statistics -------------------------------------------------------

    @property
    def size(self) -> int:
        return len(self.nodes)

    @property
    def edges(self) -> int:
        return sum(len(edges) for edges in self.out.values())

    def neighbours(self, node: str) -> list[Edge]:
        return self.out.get(node, [])

    def incoming(self, node: str) -> list[Edge]:
        return self.into.get(node, [])

    def fastest_speed(self) -> float:
        """The highest speed anywhere in the graph.

        A travel-time heuristic has to divide by this, not by the speed of the
        road it is standing on: assuming the rest of the journey happens at the
        current road's speed overestimates the time whenever a motorway is
        ahead, and an overestimate is what makes A* return the wrong answer.
        """
        speeds = [edge.speed for edges in self.out.values() for edge in edges]
        return max(speeds) if speeds else 1.0

    def stats(self) -> dict[str, float]:
        degrees = [len(edges) for edges in self.out.values()]
        return {
            "nodes": self.size,
            "edges": self.edges,
            "average_degree": round(sum(degrees) / len(degrees), 2) if degrees else 0.0,
            "fastest_speed": self.fastest_speed(),
        }

    # -- persistence ------------------------------------------------------

    def save(self, directory: str | Path) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        with (directory / "nodes.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["id", "lat", "lon", "name"])
            for node in sorted(self.nodes.values(), key=lambda n: n.id):
                writer.writerow([node.id, f"{node.lat:.6f}", f"{node.lon:.6f}", node.name])

        with (directory / "edges.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["source", "target", "length_km", "speed_kph", "name"])
            for edges in (self.out[key] for key in sorted(self.out)):
                for edge in edges:
                    writer.writerow([edge.source, edge.target, f"{edge.length:.4f}",
                                     f"{edge.speed:g}", edge.name])
        return directory

    @classmethod
    def load(cls, directory: str | Path) -> Graph:
        directory = Path(directory)
        graph = cls()

        with (directory / "nodes.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                graph.add_node(Node(row["id"], float(row["lat"]), float(row["lon"]),
                                    row.get("name", "")))

        with (directory / "edges.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                graph.add_edge(Edge(row["source"], row["target"], float(row["length_km"]),
                                    float(row["speed_kph"]), row.get("name", "")))
        return graph


def haversine(a: Node, b: Node) -> float:
    """Great-circle distance in kilometres.

    Straight-line distance on a sphere, which is what makes it a *lower bound*
    on any road distance and therefore an admissible A* heuristic. Euclidean
    distance on raw latitude and longitude is not: a degree of longitude is
    111 km at the equator and 95 km in Lahore, so it overestimates east-west
    distance away from the equator and A* stops being exact.
    """
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    inner = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(inner))


@dataclass
class Route:
    """A path through the graph, and what it cost."""

    nodes: list[str] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    cost: float = 0.0

    @property
    def found(self) -> bool:
        return bool(self.nodes)

    @property
    def length_km(self) -> float:
        return sum(edge.length for edge in self.edges)

    @property
    def minutes(self) -> float:
        return sum(edge.minutes for edge in self.edges)

    def roads(self) -> list[tuple[str, float]]:
        """The route collapsed to named roads with their distances, which is
        what a person reading directions wants rather than 300 node ids."""
        out: list[tuple[str, float]] = []
        for edge in self.edges:
            name = edge.name or "unnamed"
            if out and out[-1][0] == name:
                out[-1] = (name, out[-1][1] + edge.length)
            else:
                out.append((name, edge.length))
        return [(name, round(distance, 2)) for name, distance in out]
