from rest_framework import serializers


class GuestCreateSerializer(serializers.Serializer):
    nickname = serializers.CharField(min_length=2, max_length=16, trim_whitespace=True)
