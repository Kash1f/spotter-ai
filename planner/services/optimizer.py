"""Choose where to buy fuel along a fixed route so the fuel bill is as low as possible.

Along a fixed path, an optimal plan at every stop either

    - buys just enough to reach the next stop empty (the next stop is cheaper), or
    - fills the tank (the next stop is dearer).

So the greedy rule below is exact, not a heuristic: at each station, look one
tank's worth of road ahead. If a cheaper station is in reach, buy only enough
to get there. Otherwise this is the cheapest fuel for the whole stretch, so
fill up and drive to the cheapest station in reach.

The starting fuel is a free fill-up at a virtual station placed before mile 0,
far enough back that the vehicle reaches mile 0 with exactly the fuel it
started with. The destination is a station priced below everything, so the
vehicle always arrives empty and never buys fuel it will not use.
"""

from dataclasses import dataclass
from typing import Any

from ..exceptions import NoFeasiblePlan

EPSILON = 1e-9


@dataclass(frozen=True)
class Candidate:
    mile: float
    price: float
    ref: Any = None


@dataclass(frozen=True)
class Purchase:
    candidate: Candidate
    gallons: float
    arrival_range_miles: float


def plan_fuel_stops(candidates, trip_miles, range_miles, mpg, start_range_miles):
    """Return the Purchases, in route order, that minimise the fuel bill."""
    start_range_miles = min(start_range_miles, range_miles)
    stations = sorted(
        (c for c in candidates if 0 <= c.mile <= trip_miles), key=lambda c: (c.mile, c.price)
    )
    if trip_miles <= start_range_miles + EPSILON:
        return []
    _check_reachable(stations, trip_miles, range_miles, start_range_miles)

    miles = [start_range_miles - range_miles] + [c.mile for c in stations] + [trip_miles]
    prices = [0.0] + [c.price for c in stations] + [float('-inf')]
    destination = len(miles) - 1

    purchases = []
    here, fuel = 0, 0.0  # fuel is held as miles of range
    while here != destination:
        reach = miles[here] + range_miles + EPSILON
        cheaper = cheapest = None
        for ahead in range(here + 1, destination + 1):
            if miles[ahead] > reach:
                break
            if prices[ahead] < prices[here]:
                cheaper = ahead
                break
            if cheapest is None or prices[ahead] <= prices[cheapest]:
                cheapest = ahead

        if cheaper is not None:
            target = cheaper
            bought = max(0.0, miles[target] - miles[here] - fuel)
        else:
            target = cheapest
            bought = range_miles - fuel

        if 0 < here and bought > EPSILON:
            purchases.append(Purchase(stations[here - 1], bought / mpg, fuel))
        fuel += bought - (miles[target] - miles[here])
        here = target
    return purchases


def _check_reachable(stations, trip_miles, range_miles, start_range_miles):
    """Raise NoFeasiblePlan if some stretch of the route has no station in reach."""
    position, reach = 0.0, start_range_miles
    for mile in [c.mile for c in stations] + [trip_miles]:
        if mile > reach + EPSILON:
            target = 'the destination' if mile == trip_miles else 'the next one'
            raise NoFeasiblePlan(
                f'No fuel station on the route between mile {position:.0f} and mile {reach:.0f}, '
                f'the furthest the vehicle can get; {target} is at mile {mile:.0f}.'
            )
        position, reach = mile, mile + range_miles
