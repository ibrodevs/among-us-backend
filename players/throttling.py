from rest_framework.throttling import SimpleRateThrottle


class GuestCreationThrottle(SimpleRateThrottle):
    scope = "guest_creation"
    rate = "10/minute"

    def get_cache_key(self, request, view):
        # Trust the peer address supplied by the server, not proxy headers.
        peer = request.META.get("REMOTE_ADDR")
        if not peer:
            return None
        return self.cache_format % {"scope": self.scope, "ident": peer}
