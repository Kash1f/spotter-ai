# Fuel route planning api

A Django API that takes a start and a finish in the USA and returns the driving
route, the cheapest places to refuel along it, and the total fuel cost, for a
vehicle with a 500 mile range that does 10 miles per gallon.

- One call to a free routing API (OSRM) per request.
- Fuel stops are chosen by an exact optimizer, not a heuristic.
- The 6,626 US stations in the supplied price file are held in memory, so apart
  from the routing call everything is local and fast.

## Run it

Needs Python 3.12 or newer (Django 6.1).

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py import_places    # US towns from the Census Gazetteer
python manage.py import_stations  # fuel stations from the price file
python manage.py runserver
```

## The API

`POST /api/v1/route/` with a JSON body, or `GET` with the same fields in the query string.

| Field | Required | Meaning |
| --- | --- | --- |
| `start`, `finish` | yes | `"City, ST"` (also `"City, State name"`) or `"lat,lon"` |

```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Chicago, IL", "finish": "Houston, TX"}'
```

The response contains:

- `summary`: `distance_miles`, `duration_hours`, `fuel_stops`, `total_fuel_cost`, `gallons_purchased`, `gallons_used`.
- `fuel_stops`: each stop's name, town, coordinates, `mile_marker`, `price_per_gallon`, `gallons_purchased` and `cost`.
- `route`: the route as a GeoJSON `Feature` (a `LineString`), which any map client can draw.
- `meta`: `routing_api_calls` (always 1) and `elapsed_ms`.

`total_fuel_cost` is the fuel bought on the way. The vehicle starts with a full
tank and arrives empty, so a trip under 500 miles needs no stop and costs $0.

Errors share one shape, `{"error": {"code": "...", "message": "..."}}`:

| Status | `code` | When |
| --- | --- | --- |
| 400 | `invalid_request` | A field is missing or malformed |
| 400 | `location_not_found` | A place cannot be found, or its name is ambiguous without a state |
| 422 | `route_not_found` | No driving route exists between the two points |
| 422 | `no_feasible_fuel_plan` | A stretch of the route has no station within range |
| 502 | `routing_provider_error` | OSRM failed or timed out |

A Postman collection is in [docs/postman_collection.json](docs/postman_collection.json).

## How it works

1. **Resolve the endpoints offline.** "City, ST" is looked up in a table of
   32,058 US places from the Census Gazetteer. No network call.
2. **Fetch the route.** One OSRM call returns the road geometry and distance.
3. **Find the stations on the route.** Stations sit in memory as numpy arrays. A
   coarse grid narrows them to a few hundred near the route, then one matrix
   product gives each its distance from the route and its mile marker. Stations
   within 5 miles count.
4. **Choose the stops.** A look-ahead greedy: at each station, if a cheaper one
   is within a tank's reach buy just enough to get there, otherwise fill up. This
   provably minimises the fuel bill. See `planner/services/optimizer.py`.

The price file has no coordinates, so each station is placed at the centre of
its town using the Census file. Stations whose town the Census does not list
(313 of 6,626) are not used.

## Tests

```bash
python manage.py test
```

The optimizer is checked against brute force on random routes. OSRM is mocked,
so the suite makes no network calls.

## Limitations

- Stations are positioned at their town centre, not their exact exit, and the
  detour to reach one is not added to the trip.
- The cheapest plan can include very small top-ups, because chasing every
  slightly cheaper pump costs nothing in the model.
- Canadian stations in the price file are ignored.
- The public OSRM demo server has no uptime guarantee.

## Data sources

- **Fuel prices:** the file supplied with the assignment.
- **US places:** the U.S. Census Bureau 2025 Gazetteer (public domain).
- **Routing:** the public [OSRM](https://project-osrm.org/) demo server, built on OpenStreetMap data.
