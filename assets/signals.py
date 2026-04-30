from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Instrument

SYMBOLS_CHANGED_KEY = "finnhub_symbols_changed"


@receiver(post_save, sender=Instrument)
def mark_symbols_changed(sender, **kwargs):
    """Flag that tracked symbols have changed so the Celery task picks up new ones."""
    cache.set(SYMBOLS_CHANGED_KEY, True, timeout=None)
