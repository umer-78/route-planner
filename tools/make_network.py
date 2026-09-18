"""Generate the sample road network.

Deterministic: the same seed gives the same network byte for byte, and CI
regenerates it and fails if a byte changes. A routing project whose numbers
cannot be reproduced is a routing project whose numbers cannot be checked.

The network is a grid of intersections with three road classes, because a graph
where every edge has the same speed cannot show the difference between the
shortest route and the fastest one — which is the whole reason a router has two
cost models.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from routeplanner.graph import Graph, Node  # noqa: E402

ROWS, COLUMNS = 40, 40
SOUTH, WEST = 31.4200, 74.2000          # a 40x40 grid over central Lahore
LAT_STEP, LON_STEP = 0.0060, 0.0070

LOCAL, ARTERIAL, MOTORWAY = 35.0, 60.0, 100.0
ARTERIAL_EVERY = 5
MISSING_EDGE_CHANCE = 0.08              # blocks that do not join up


def identifier(row: int, column: int) -> str:
    return f"n{row:02d}{column:02d}"


def road_name(row: int, column: int, horizontal: bool) -> str:
    if horizontal:
        kind = "Avenue" if row % ARTERIAL_EVERY == 0 else "Street"
        return f"{ordinal(row + 1)} {kind}"
    kind = "Boulevard" if column % ARTERIAL_EVERY == 0 else "Lane"
    return f"{letters(column)} {kind}"


def ordinal(n: int) -> str:
    # The teens are the exception: 11th, 12th and 13th, not 11st, 12nd, 13rd.
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def letters(n: int) -> str:
    """Excel-style column names, so the 27th street is AA rather than a repeat."""
    name = ""
    n += 1
    while n:
        n, remainder = divmod(n - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def build() -> Graph:
    rng = random.Random(20240918)
    graph = Graph()

    for row in range(ROWS):
        for column in range(COLUMNS):
            graph.add_node(Node(
                id=identifier(row, column),
                lat=SOUTH + row * LAT_STEP,
                lon=WEST + column * LON_STEP,
                name=f"{road_name(row, column, True)} & {road_name(row, column, False)}",
            ))

    for row in range(ROWS):
        for column in range(COLUMNS):
            for dr, dc, horizontal in ((0, 1, True), (1, 0, False)):
                r, c = row + dr, column + dc
                if r >= ROWS or c >= COLUMNS:
                    continue

                arterial = (horizontal and row % ARTERIAL_EVERY == 0) or \
                           (not horizontal and column % ARTERIAL_EVERY == 0)
                # Arterials stay connected; ordinary blocks sometimes do not,
                # which is what stops the grid being a perfect lattice where
                # every route is the same length.
                if not arterial and rng.random() < MISSING_EDGE_CHANCE:
                    continue

                graph.add_road(identifier(row, column), identifier(r, c),
                               ARTERIAL if arterial else LOCAL,
                               road_name(row, column, horizontal))

    # A ring motorway around the edge of the grid: fast, but a long way round
    # unless the journey is long enough to be worth it.
    ring = ([(0, c) for c in range(0, COLUMNS, 5)] +
            [(r, COLUMNS - 1) for r in range(0, ROWS, 5)][1:] +
            [(ROWS - 1, c) for c in range(COLUMNS - 1, -1, -5)][1:] +
            [(r, 0) for r in range(ROWS - 1, -1, -5)][1:])
    # The ring closes on itself, so the last node pairs with the first.
    for (r1, c1), (r2, c2) in zip(ring, ring[1:] + ring[:1], strict=True):
        graph.add_road(identifier(r1, c1), identifier(r2, c2), MOTORWAY, "Ring Motorway")

    return graph


def repair(graph: Graph) -> int:
    """Reconnect anything the random thinning cut off.

    Dropping 8% of blocks gives the grid some texture, but it can also strip an
    intersection of every one of its four roads, and an intersection with no
    roads is not an intersection. Worse, a router cannot be exercised on a
    network where some pairs have no answer for reasons that are an accident of
    the seed rather than a fact about the map.

    So every node outside the largest component gets one road back, chosen as
    the shortest grid link to a node already inside it. The count is printed,
    because a generator that quietly repairs its own output is a generator whose
    output nobody can reason about.
    """
    main = largest_component(graph)
    added = 0

    while len(main) < graph.size:
        for node_id in sorted(set(graph.nodes) - main):
            row, column = int(node_id[1:3]), int(node_id[3:5])
            for dr, dc, horizontal in ((0, 1, True), (0, -1, True), (1, 0, False), (-1, 0, False)):
                r, c = row + dr, column + dc
                if not (0 <= r < ROWS and 0 <= c < COLUMNS):
                    continue
                neighbour = identifier(r, c)
                if neighbour not in main:
                    continue
                graph.add_road(node_id, neighbour, LOCAL,
                               road_name(min(row, r), min(column, c), horizontal))
                added += 1
                break
            else:
                continue
            break
        main = largest_component(graph)

    return added


def largest_component(graph: Graph) -> set[str]:
    """Every road here is two-way, so the components are the undirected ones."""
    seen: set[str] = set()
    best: set[str] = set()

    for start in sorted(graph.nodes):
        if start in seen:
            continue
        component = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for edge in graph.neighbours(node):
                if edge.target not in component:
                    component.add(edge.target)
                    stack.append(edge.target)
        seen |= component
        if len(component) > len(best):
            best = component
    return best


def main() -> int:
    graph = build()
    added = repair(graph)

    directory = Path(__file__).resolve().parent.parent / "data" / "city"
    graph.save(directory)
    stats = graph.stats()
    print(f"{stats['nodes']:,} intersections, {stats['edges']:,} directed edges, "
          f"average out-degree {stats['average_degree']}")
    print(f"{added} road(s) added to reconnect intersections the thinning cut off")
    print(f"every intersection reaches every other: {len(largest_component(graph)) == graph.size}")
    print(f"written to {directory.relative_to(directory.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
