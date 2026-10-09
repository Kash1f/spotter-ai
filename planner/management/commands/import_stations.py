import csv
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import FuelStation, Place
from planner.services.places import STATES, key_variants


class Command(BaseCommand):
    help = 'Load fuel stations from the price CSV and link each one to the Census Place of its town.'

    def add_arguments(self, parser):
        parser.add_argument('--csv', default=str(settings.FUEL_PRICES_CSV))

    def handle(self, *args, **options):
        if not Place.objects.exists():
            raise CommandError('No places loaded. Run "python manage.py import_places" first.')
        try:
            with open(options['csv'], newline='', encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
        except OSError as exc:
            raise CommandError(f'Cannot read {options["csv"]}: {exc}')

        # One station per OPIS ID. Rows sharing an ID are the same truck stop
        # listed more than once, sometimes with different prices: take the mean.
        grouped, outside_us = defaultdict(list), 0
        for row in rows:
            if row['State'].strip() not in STATES:
                outside_us += 1
                continue
            grouped[int(row['OPIS Truckstop ID'])].append(row)

        stations = []
        for opis_id, group in grouped.items():
            first = group[0]
            prices = [Decimal(row['Retail Price']) for row in group]
            stations.append(FuelStation(
                opis_id=opis_id,
                name=first['Truckstop Name'].strip(),
                address=first['Address'].strip(),
                city=first['City'].strip(),
                state=first['State'].strip(),
                price=sum(prices) / len(prices),
            ))

        places = self._places()
        for station in stations:
            station.place_id = next(
                (places[(key, station.state)] for key in key_variants(station.city) if (key, station.state) in places),
                None,
            )

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=2000)

        located = sum(1 for station in stations if station.place_id)
        self.stdout.write(f'CSV rows read:              {len(rows)}')
        self.stdout.write(f'  outside the USA, dropped: {outside_us}')
        self.stdout.write(f'  duplicate rows merged:    {len(rows) - outside_us - len(stations)}')
        self.stdout.write(f'Stations stored:            {len(stations)}')
        self.stdout.write(f'  located:                  {located}')
        self.stdout.write(f'  not located (unused):     {len(stations) - located}')

    def _places(self):
        """Map (key, state) to a Place id, preferring real names and larger places."""
        places = {}
        rows = Place.objects.order_by('is_alias', '-land_sqmi')
        for key, state, pk in rows.values_list('key', 'state', 'pk'):
            places.setdefault((key, state), pk)
        return places
