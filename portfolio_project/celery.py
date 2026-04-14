import os

from celery import Celery
from celery.signals import worker_ready
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", ".env"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "portfolio_project.settings")

app = Celery("portfolio_project")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_ready.connect
def start_price_stream(sender, **kwargs):
    """Automatically start the Finnhub price stream when the Celery worker starts."""
    from assets.tasks import stream_prices

    stream_prices.delay()
