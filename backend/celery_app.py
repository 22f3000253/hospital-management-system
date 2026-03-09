from celery import Celery
from celery.schedules import crontab

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL'],
        include=['tasks'],
    )
    celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='Asia/Kolkata',
        enable_utc=True,
        result_expires=3600,
        beat_schedule={
            'daily-appointment-reminders': {
                'task': 'tasks.send_daily_reminders',
                'schedule': crontab(hour=8, minute=0),
            },
            'monthly-activity-reports': {
                'task': 'tasks.send_monthly_reports',
                'schedule': crontab(hour=7, minute=0, day_of_month=1),
            },
        },
    )
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask
    return celery
