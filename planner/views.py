from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services.trip import plan_trip


class RouteView(APIView):
    """Plan the cheapest fuel stops between two places in the USA.

    POST a JSON body, or GET with the same fields in the query string.
    """

    def post(self, request):
        return self._plan(request.data)

    def get(self, request):
        return self._plan(request.query_params)

    def _plan(self, data):
        serializer = RouteRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(plan_trip(serializer.validated_data['start'], serializer.validated_data['finish']))
