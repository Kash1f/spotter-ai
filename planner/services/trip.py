"""Plan a trip: resolve the endpoints, fetch the route, pick the fuel stops."""

import time
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from django.conf import settings

from .optimizer import Candidate, plan_fuel_stops
from .places import resolve_location
from .routing import get_route
from .stations import stations_along

CENT = Decimal('0.01')
# The full geometry runs to tens of thousands of points on a cross-country
# route. Matching uses all of it; the response carries a thinned copy that
# still draws cleanly.
MAX_GEOMETRY_POINTS = 3000


def _money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _thin(coordinates):
    """At most MAX_GEOMETRY_POINTS points, rounded to 5 decimals (about a metre)."""
    step = max(1, -(-len(coordinates) // MAX_GEOMETRY_POINTS))
    keep = np.arange(0, len(coordinates), step)
    if keep[-1] != len(coordinates) - 1:
        keep = np.append(keep, len(coordinates) - 1)
    return np.round(coordinates[keep], 5).tolist()


def plan_trip(start_text, finish_text):
    started = time.perf_counter()
    range_miles, mpg = settings.VEHICLE_RANGE_MILES, settings.VEHICLE_MPG

    start = resolve_location(start_text)
    finish = resolve_location(finish_text)
    route = get_route(start, finish)  # the only external call

    on_route = stations_along(route.coordinates, route.distance_miles, settings.STATION_CORRIDOR_MILES)
    purchases = plan_fuel_stops(
        [Candidate(mile=s.mile, price=s.station['price'], ref=s) for s in on_route],
        trip_miles=route.distance_miles,
        range_miles=range_miles,
        mpg=mpg,
        start_range_miles=range_miles,  # the vehicle leaves with a full tank
    )

    stops, total_cost, total_gallons = [], Decimal('0'), 0.0
    for order, purchase in enumerate(purchases, start=1):
        found = purchase.candidate.ref
        station = found.station
        cost = _money(purchase.gallons * station['price'])
        total_cost += cost
        total_gallons += purchase.gallons
        stops.append({
            'order': order,
            'station_id': station['opis_id'],
            'name': station['name'],
            'address': station['address'],
            'city': station['city'],
            'state': station['state'],
            'lat': station['lat'],
            'lon': station['lon'],
            'mile_marker': round(found.mile, 1),
            'miles_off_route': round(found.off_route_miles, 1),
            'price_per_gallon': round(station['price'], 3),
            'gallons_on_arrival': round(purchase.arrival_range_miles / mpg, 2),
            'gallons_purchased': round(purchase.gallons, 2),
            'cost': float(cost),
        })

    return {
        'start': {'query': start.query, 'name': start.name, 'lat': start.lat, 'lon': start.lon},
        'finish': {'query': finish.query, 'name': finish.name, 'lat': finish.lat, 'lon': finish.lon},
        'summary': {
            'distance_miles': round(route.distance_miles, 1),
            'duration_hours': round(route.duration_seconds / 3600, 2),
            'fuel_stops': len(stops),
            'total_fuel_cost': float(total_cost),
            'gallons_purchased': round(total_gallons, 2),
            'gallons_used': round(route.distance_miles / mpg, 2),
            'currency': 'USD',
        },
        'vehicle': {'max_range_miles': range_miles, 'miles_per_gallon': mpg},
        'fuel_stops': stops,
        'route': {
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': _thin(route.coordinates)},
        },
        'meta': {
            'routing_api_calls': 1,
            'stations_considered': len(on_route),
            'elapsed_ms': round((time.perf_counter() - started) * 1000, 1),
        },
    }
