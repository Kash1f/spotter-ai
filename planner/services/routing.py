"""Driving route from OSRM: one HTTP call per route.

OSRM's public demo server is free and needs no key. The geometry is requested
as an encoded polyline, which is about a third the size of GeoJSON on the wire.
"""

from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

from ..exceptions import RouteNotFound, RoutingProviderError

METERS_PER_MILE = 1609.344

# One session per process keeps the connection to OSRM open between requests.
session = requests.Session()
session.headers['User-Agent'] = 'fuel-route-planner/1.0'


@dataclass(frozen=True, eq=False)
class Route:
    coordinates: np.ndarray  # shape (N, 2), rows of [lon, lat]
    distance_miles: float
    duration_seconds: float


def decode_polyline(text, precision=5):
    """Decode an encoded polyline into an (N, 2) float array of [lon, lat] rows.

    Each number is packed 5 bits per character, low bits first, with bit 6 set
    on every character but the last of a number. Done on whole arrays, so a
    cross-country route decodes in about a millisecond.
    """
    if not text:
        return np.empty((0, 2))
    chunks = np.frombuffer(text.encode('ascii'), dtype=np.uint8).astype(np.int64) - 63
    starts = np.concatenate(([0], np.flatnonzero(chunks < 0x20)[:-1] + 1))
    lengths = np.diff(np.concatenate((starts, [len(chunks)])))
    position = np.arange(len(chunks)) - np.repeat(starts, lengths)
    numbers = np.add.reduceat((chunks & 0x1F) << (5 * position), starts)
    steps = np.where(numbers & 1, ~(numbers >> 1), numbers >> 1).reshape(-1, 2)  # zigzag -> signed
    lat_lon = np.cumsum(steps, axis=0) / 10 ** precision
    return lat_lon[:, ::-1]


def get_route(start, finish):
    """Return the driving Route between two Locations, using a single OSRM call."""
    url = (
        f'{settings.OSRM_BASE_URL}/route/v1/driving/'
        f'{start.lon:.6f},{start.lat:.6f};{finish.lon:.6f},{finish.lat:.6f}'
    )
    try:
        response = session.get(
            url,
            params={'overview': 'full', 'geometries': 'polyline', 'steps': 'false', 'alternatives': 'false'},
            timeout=settings.ROUTING_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise RoutingProviderError('OSRM did not respond in time.')
    except requests.RequestException as exc:
        raise RoutingProviderError(f'Could not reach OSRM: {exc.__class__.__name__}.')

    try:
        body = response.json()
    except ValueError:
        raise RoutingProviderError(f'OSRM returned HTTP {response.status_code} with a non-JSON body.')

    code = body.get('code')
    if code in ('NoRoute', 'NoSegment'):
        raise RouteNotFound(f'No driving route between {start.name} and {finish.name}.')
    if response.status_code != 200 or code != 'Ok' or not body.get('routes'):
        raise RoutingProviderError(
            f'OSRM returned HTTP {response.status_code}: {body.get("message") or code or "no route"}.'
        )

    best = body['routes'][0]
    return Route(
        coordinates=decode_polyline(best['geometry']),
        distance_miles=best['distance'] / METERS_PER_MILE,
        duration_seconds=best['duration'],
    )
