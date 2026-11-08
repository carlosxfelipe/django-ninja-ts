from django.apps import AppConfig


class NinjaTsConfig(AppConfig):
    name = "ninja_ts"
    verbose_name = "Django Ninja TypeScript SDK"

    def ready(self) -> None:
        from ninja_ts.compat import ensure_ninja_extra_compat

        ensure_ninja_extra_compat()
