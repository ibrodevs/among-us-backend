import unicodedata

from rest_framework import serializers


class NicknameField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        nickname = unicodedata.normalize("NFC", super().to_internal_value(data))
        if any(unicodedata.category(character) in {"Cc", "Cs"} for character in nickname):
            self.fail("invalid")
        return nickname


class GuestCreateSerializer(serializers.Serializer):
    nickname = NicknameField(min_length=2, max_length=16, trim_whitespace=True)
