"""Celery worker configuration.

Placeholder for Phase 1+. The worker container will fail gracefully
until this is properly configured — that's fine for Phase 0.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "courtbook",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/London",
    enable_utc=True,
)
