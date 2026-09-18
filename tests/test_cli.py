"""The command line."""

from __future__ import annotations

import pytest

from routeplanner.cli import main

NETWORK = ["-n", "data/city"]


def invoke(capsys, *args) -> tuple[int, str, str]:
    code = main([*NETWORK, *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_stats(capsys):
    code, out, _ = invoke(capsys, "stats")
    assert code == 0
    assert "1,600 intersections" in out
    assert "100 km/h" in out


def test_route(capsys):
    code, out, _ = invoke(capsys, "route", "n0000", "n1010")
    assert code == 0
    assert "km," in out and "minutes" in out
    assert "expanded" in out


def test_route_names_the_roads(capsys):
    _, out, _ = invoke(capsys, "route", "n0000", "n0010")
    assert "Avenue" in out or "Street" in out or "Lane" in out or "Boulevard" in out


def test_the_fastest_route_uses_the_motorway(capsys):
    """The whole reason the network has three road classes."""
    _, shortest, _ = invoke(capsys, "route", "n0202", "n3737")
    _, fastest, _ = invoke(capsys, "route", "n0202", "n3737", "--fastest")
    assert "Ring Motorway" in fastest
    assert "Ring Motorway" not in shortest
    assert "of that is motorway" in fastest


def test_route_algorithms_agree_on_the_cost_they_optimise(capsys):
    """On the distance, which is what they were asked to minimise — not
    necessarily on the route. See the next test."""
    distances = []
    for algorithm in ("dijkstra", "astar", "bidirectional"):
        _, out, _ = invoke(capsys, "route", "n0101", "n2020", "-a", algorithm)
        line = next(line for line in out.splitlines() if "km," in line)
        distances.append(line.strip().split(" km,")[0])
    assert len(set(distances)) == 1


def test_the_shortest_route_is_not_unique(capsys):
    """A grid has many paths of exactly the same length, so "the shortest
    route" is a set, and which member comes back depends on the order the
    algorithm settles ties. Here dijkstra and bidirectional both return 25.28 km
    routes that take different amounts of time.

    Worth pinning, because it is the kind of difference that looks like a bug in
    one of the algorithms and is not one.
    """
    times = set()
    for algorithm in ("dijkstra", "astar", "bidirectional"):
        _, out, _ = invoke(capsys, "route", "n0101", "n2020", "-a", algorithm)
        line = next(line for line in out.splitlines() if "km," in line)
        times.add(line.strip())
    assert len(times) > 1, "expected the tie to be broken differently somewhere"
    assert {t.split(" km,")[0] for t in times} == {"25.28"}


def test_compare(capsys):
    code, out, _ = invoke(capsys, "compare", "n0505", "n3030")
    assert code == 0
    assert "all three agree on the cost: True" in out
    assert "fewer nodes than dijkstra" in out


def test_compare_on_travel_time(capsys):
    code, out, _ = invoke(capsys, "compare", "n0505", "n3030", "--fastest")
    assert code == 0
    assert "(fastest)" in out
    assert "cost (min)" in out


def test_weights(capsys):
    code, out, _ = invoke(capsys, "weights", "-p", "10")
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip().startswith(("1.", "2.", "3."))]
    assert len(lines) == 7
    assert "no longer admissible" in out


def test_bench(capsys):
    code, out, _ = invoke(capsys, "bench", "-p", "10")
    assert code == 0
    for name in ("dijkstra", "a*", "bidirectional"):
        assert name in out


def test_nearest(capsys):
    code, out, _ = invoke(capsys, "nearest", "31.45", "74.25")
    assert code == 0
    assert "m away" in out


def test_an_unknown_node_is_reported(capsys):
    code, _, err = invoke(capsys, "route", "nowhere", "n0000")
    assert code == 2
    assert "routeplanner:" in err


def test_a_missing_network_is_reported(capsys):
    code = main(["-n", "no-such-directory", "stats"])
    assert code == 2
    assert "make_network.py" in capsys.readouterr().err


def test_no_reopen_is_available(capsys):
    """It exists to demonstrate the failure, so it has to be reachable."""
    code, out, _ = invoke(capsys, "route", "n0000", "n1010", "--no-reopen")
    assert code == 0
    assert "km," in out


def test_the_weight_is_shown_when_it_is_not_one(capsys):
    _, out, _ = invoke(capsys, "route", "n0000", "n1010", "-w", "2")
    assert "heuristic x2" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["--version"])
    assert exit_.value.code == 0
