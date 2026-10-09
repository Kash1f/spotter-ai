"""One JSON shape for every API error: {"error": {"code": ..., "message": ...}}."""

import logging

from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .exceptions import PlannerError

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    if isinstance(exc, PlannerError):
        return Response({'error': {'code': exc.code, 'message': exc.message}}, status=exc.status_code)

    if isinstance(exc, drf_exceptions.ValidationError):
        return Response(
            {'error': {'code': 'invalid_request', 'message': 'The request is not valid.', 'fields': exc.detail}},
            status=400,
        )

    response = exception_handler(exc, context)
    if response is not None:
        response.data = {'error': {'code': 'error', 'message': str(exc.detail) if hasattr(exc, 'detail') else str(exc)}}
        return response

    # Anything unexpected: details go to the log, not to the client.
    logger.exception('Unhandled error in %s', context['view'].__class__.__name__, exc_info=exc)
    return Response({'error': {'code': 'internal_error', 'message': 'Something went wrong.'}}, status=500)
