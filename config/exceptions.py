import logging
from django.db import DatabaseError
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    if isinstance(exc, DatabaseError):
        logging.getLogger(__name__).exception("Database request failed")
        return Response({"detail": "Service temporarily unavailable"}, status=503)
    return exception_handler(exc, context)
