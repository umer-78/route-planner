"""Shortest and fastest routes over a road network: Dijkstra, A* and bidirectional search."""

from .graph import Edge, Graph, Node, Route, haversine
from .search import (
    Result,
    Stats,
    astar,
    bidirectional,
    by_distance,
    by_time,
    dijkstra,
    search,
    straight_line,
)

__all__ = [
    "Edge", "Graph", "Node", "Result", "Route", "Stats", "astar", "bidirectional",
    "by_distance", "by_time", "dijkstra", "haversine", "search", "straight_line",
]
__version__ = "1.0.0"
