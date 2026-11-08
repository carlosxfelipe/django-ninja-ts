import django
from django.conf import settings


def pytest_configure():
    settings.configure(
        DEBUG=True,
        SECRET_KEY="ninja-ts-tests",
        ALLOWED_HOSTS=["testserver"],
        ROOT_URLCONF="tests.urls",
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "ninja_ts",
        ],
        DATABASES={},
        NINJA_TS_API="tests.sample_api.api",
    )
    django.setup()
