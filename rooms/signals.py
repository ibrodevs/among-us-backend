from django.dispatch import Signal


# Receivers can refresh the public lobby state after a membership change commits.
lobby_changed = Signal()
