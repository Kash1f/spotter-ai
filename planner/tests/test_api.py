from unittest import mock

import numpy as np
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from planner.exceptions import RoutingProviderError
from planner.models import FuelStation, Place
from planner.services import stations as station_index
from planner.services.routing import Route, decode_polyline

URL = '/api/v1/route/'


class PolylineTests(SimpleTestCase):
    def test_decodes_the_documented_example(self):
        # The example from Google's polyline algorithm documentation.
        points = decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@')
        np.testing.assert_allclose(
            points, [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]], atol=1e-5
        )

    def test_empty_string(self):
        self.assertEqual(decode_polyline('').shape, (0, 2))


class RouteApiTests(TestCase):
    """A straight 800 mile line due east, with a few stations along it."""

    @classmethod
    def setUpTestData(cls):
        start = Place.objects.create(name='Startville', state='IL', key='startville', lat=40.0, lon=-100.0)
        Place.objects.create(name='Endtown', state='OH', key='endtown', lat=40.0, lon=-85.0)
        # Roughly 53 miles per degree of longitude at 40N.
        for opis_id, name, lon, price in [(1, 'DEAR', -95.0, '4.00'), (2, 'CHEAP', -91.0, '3.00')]:
            town = Place.objects.create(name=name.title(), state='IA', key=name.lower(), lat=40.0, lon=lon)
            FuelStation.objects.create(
                opis_id=opis_id, name=name, address='I-80', city=town.name, state='IA', price=price, place=town
            )
        cls.start = start

    def setUp(self):
        station_index.reset_index()
        self.addCleanup(station_index.reset_index)
        cache.clear()  # a plan cached by one test must not answer another

    @staticmethod
    def straight_route():
        lons = np.linspace(-100.0, -85.0, 600)
        coordinates = np.column_stack((lons, np.full_like(lons, 40.0)))
        return Route(coordinates=coordinates, distance_miles=800.0, duration_seconds=12 * 3600)

    def post(self, **body):
        return self.client.post(URL, body, content_type='application/json')

    def test_returns_route_stops_and_cost(self):
        with mock.patch('planner.services.trip.get_route', return_value=self.straight_route()) as route:
            response = self.post(start='Startville, IL', finish='Endtown, OH')
        self.assertEqual(response.status_code, 200)
        route.assert_called_once()  # a single routing call
        body = response.json()
        self.assertEqual(body['summary']['distance_miles'], 800.0)
        self.assertEqual(body['route']['geometry']['type'], 'LineString')
        self.assertEqual(body['meta']['routing_api_calls'], 1)
        self.assertGreaterEqual(body['summary']['fuel_stops'], 1)
        paid = sum(stop['cost'] for stop in body['fuel_stops'])
        self.assertAlmostEqual(body['summary']['total_fuel_cost'], paid, places=2)
        # Starts full and arrives empty: only the 300 miles beyond the first tank are bought.
        self.assertAlmostEqual(body['summary']['gallons_purchased'], 30.0, places=1)

    def test_unknown_place_is_a_400(self):
        response = self.post(start='Nowhere, ZZ', finish='Endtown, OH')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error']['code'], 'location_not_found')

    def test_missing_field_is_a_400(self):
        response = self.post(start='Startville, IL')
        self.assertEqual(response.status_code, 400)
        error = response.json()['error']
        self.assertEqual(error['code'], 'invalid_request')
        self.assertIn('finish', error['fields'])

    def test_routing_failure_is_a_502(self):
        with mock.patch('planner.services.trip.get_route', side_effect=RoutingProviderError('down')):
            response = self.post(start='Startville, IL', finish='Endtown, OH')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()['error']['code'], 'routing_provider_error')

    def test_get_with_query_string(self):
        with mock.patch('planner.services.trip.get_route', return_value=self.straight_route()):
            response = self.client.get(URL, {'start': 'Startville, IL', 'finish': 'Endtown, OH'})
        self.assertEqual(response.status_code, 200)

    def test_repeat_trip_is_served_from_cache_without_a_routing_call(self):
        with mock.patch('planner.services.trip.get_route', return_value=self.straight_route()) as route:
            first = self.post(start='Startville, IL', finish='Endtown, OH').json()
            # Typed differently, but the same trip.
            second = self.post(start='startville il', finish='ENDTOWN, OH').json()
        route.assert_called_once()
        self.assertEqual(first['meta']['served_from'], 'routing api')
        self.assertEqual(first['meta']['routing_api_calls'], 1)
        self.assertEqual(second['meta']['served_from'], 'cache')
        self.assertEqual(second['meta']['routing_api_calls'], 0)
        self.assertEqual(second['summary'], first['summary'])
        self.assertEqual(second['fuel_stops'], first['fuel_stops'])
        # What the caller typed is echoed back fresh, not taken from the cache.
        self.assertEqual(second['start']['query'], 'startville il')

    def test_a_cache_outage_does_not_fail_the_request(self):
        with mock.patch('planner.services.trip.get_route', return_value=self.straight_route()), \
                mock.patch('planner.services.trip.cache.get', side_effect=ConnectionError), \
                mock.patch('planner.services.trip.cache.set', side_effect=ConnectionError):
            response = self.post(start='Startville, IL', finish='Endtown, OH')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['meta']['served_from'], 'routing api')


class FuelPlannerPageTests(SimpleTestCase):
    def test_page_renders_and_points_at_the_api(self):
        response = self.client.get('/fuel-planner/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="map"')
        self.assertContains(response, URL)
