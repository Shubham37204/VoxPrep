from celery import Celery
from celery.schedules import crontab

from app.config.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "voxprep",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


celery_app.conf.beat_schedule = {
    "expire-abandoned-sessions": {
        "task": "app.workers.tasks.expire_abandoned_sessions",
        "schedule": crontab(minute="*/5"),
    },
}