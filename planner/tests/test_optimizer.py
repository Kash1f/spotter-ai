import itertools
import random

from django.test import SimpleTestCase

from planner.exceptions import NoFeasiblePlan
from planner.services.optimizer import Candidate, plan_fuel_stops

RANGE, MPG = 500.0, 10.0


def total_cost(purchases):
    return sum(p.gallons * p.candidate.price for p in purchases)


def brute_force(candidates, trip, start_range):
    """Cheapest bill over every subset of stations, filling just enough at each stop."""
    best = None
    stations = sorted(candidates, key=lambda c: c.mile)
    for size in range(len(stations) + 1):
        for chosen in itertools.combinations(stations, size):
            cost = _cost_of_stops(chosen, trip, start_range)
            if cost is not None and (best is None or cost < best):
                best = cost
    return best


def _cost_of_stops(stops, trip, start_range):
    """Fuel bill when stopping at exactly these stations, buying lazily (only what is needed)."""
    # With a fixed set of stops the cheapest way to fund each leg is to buy, at the
    # cheapest earlier stop still within a tank, so solve it as a small greedy.
    points = [(0.0, 0.0)] + [(s.mile, s.price) for s in stops] + [(trip, float('-inf'))]
    fuel, cost = start_range, 0.0
    for i in range(len(points) - 1):
        leg = points[i + 1][0] - points[i][0]
        if leg > RANGE:
            return None
        if i > 0:
            price = points[i][1]
            cheaper_ahead = next(
                (j for j in range(i + 1, len(points)) if points[j][1] < price and points[j][0] - points[i][0] <= RANGE),
                None,
            )
            target = (points[cheaper_ahead][0] - points[i][0]) if cheaper_ahead else RANGE
            buy = max(0.0, target - fuel)
            cost += buy / MPG * price
            fuel += buy
        if fuel < leg - 1e-9:
            return None
        fuel -= leg
    return cost


class OptimizerTests(SimpleTestCase):
    def test_trip_within_starting_fuel_needs_no_stops(self):
        self.assertEqual(plan_fuel_stops([Candidate(100, 3.0)], 400, RANGE, MPG, RANGE), [])

    def test_buys_only_what_is_needed_before_a_cheaper_station(self):
        # 800 mile trip. Dear station at mile 300, cheap one at mile 600.
        stations = [Candidate(300, 4.0), Candidate(600, 3.0)]
        purchases = plan_fuel_stops(stations, 800, RANGE, MPG, RANGE)
        self.assertEqual([p.candidate.mile for p in purchases], [300, 600])
        # Arrives at 300 with 200 miles left; needs 300 more to reach the cheap one.
        self.assertAlmostEqual(purchases[0].gallons, 10.0)
        # Then buys only the 200 miles still needed to finish.
        self.assertAlmostEqual(purchases[1].gallons, 20.0)

    def test_fills_up_when_the_next_stations_are_dearer(self):
        stations = [Candidate(200, 3.0), Candidate(600, 4.0)]
        purchases = plan_fuel_stops(stations, 900, RANGE, MPG, RANGE)
        self.assertEqual(purchases[0].candidate.mile, 200)
        self.assertAlmostEqual(purchases[0].gallons, 20.0)  # tops up 200 miles of the 500 range

    def test_gap_longer_than_range_is_not_feasible(self):
        with self.assertRaises(NoFeasiblePlan):
            plan_fuel_stops([Candidate(100, 3.0)], 1200, RANGE, MPG, RANGE)

    def test_starting_with_less_fuel(self):
        purchases = plan_fuel_stops([Candidate(100, 3.0)], 450, RANGE, MPG, 200.0)
        self.assertEqual(len(purchases), 1)
        # Arrives at mile 100 with 100 miles of fuel left and 350 miles to go: buys 250 miles' worth.
        self.assertAlmostEqual(purchases[0].gallons, 25.0)

    def test_matches_brute_force_on_random_routes(self):
        rng = random.Random(7)
        for _ in range(150):
            trip = rng.uniform(550, 1800)
            stations = [Candidate(rng.uniform(0, trip), round(rng.uniform(2.7, 4.5), 3)) for _ in range(rng.randint(3, 9))]
            expected = brute_force(stations, trip, RANGE)
            if expected is None:
                with self.assertRaises(NoFeasiblePlan):
                    plan_fuel_stops(stations, trip, RANGE, MPG, RANGE)
                continue
            actual = total_cost(plan_fuel_stops(stations, trip, RANGE, MPG, RANGE))
            self.assertAlmostEqual(actual, expected, places=6)
