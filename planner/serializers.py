from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text='"City, ST" or "lat,lon"')
    finish = serializers.CharField(max_length=200, help_text='"City, ST" or "lat,lon"')
