from __future__ import absolute_import
from arches.setup import get_version

try:
    from .celery import app as celery_app
except ModuleNotFoundError as e:
    print(e)

VERSION = (5, 0, 0, 'final', 0)

__version__ = get_version(VERSION)

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
__all__ = ('celery_app',)
