"""``manage.py generate_ts_sdk``: export or verify the modular TypeScript SDK (ideal for CI)."""

from __future__ import annotations

import gc
from importlib import import_module
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from ninja_ts.integration import (
    SdkDriftError,
    check_sdk,
    sync_sdk,
)


def resolve_api(dotted_path: str | None):
    """Find the NinjaAPI: ``--api`` > ``settings.NINJA_TS_API`` > the only instance in the URLconf."""
    from ninja import NinjaAPI

    dotted_path = dotted_path or getattr(settings, "NINJA_TS_API", None)
    if dotted_path:
        try:
            api = import_string(dotted_path)
        except ImportError as exc:
            raise CommandError(f"Could not import {dotted_path!r}: {exc}") from exc
        if not isinstance(api, NinjaAPI):
            raise CommandError(f"{dotted_path!r} is not a NinjaAPI instance")
        return api

    import_module(settings.ROOT_URLCONF)
    apis = [obj for obj in gc.get_objects() if isinstance(obj, NinjaAPI)]
    if len(apis) == 1:
        return apis[0]
    if not apis:
        raise CommandError(
            "No NinjaAPI found. Use --api path.to.api or set settings.NINJA_TS_API."
        )
    names = ", ".join(
        sorted(f"{a.title!r} (namespace {a.urls_namespace!r})" for a in apis)
    )
    raise CommandError(
        f"Multiple NinjaAPI instances found: {names}. Use --api or settings.NINJA_TS_API."
    )


class Command(BaseCommand):
    help = "Generate a zero-dependency modular TypeScript SDK directory from a Django Ninja API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--api",
            help="Dotted path to the NinjaAPI instance (e.g. config.api.api). "
            "Defaults to settings.NINJA_TS_API or the only NinjaAPI in the URLconf.",
        )
        parser.add_argument(
            "-o",
            "--out",
            help="Output directory for the modular SDK (e.g. ./sdk).",
        )
        parser.add_argument(
            "--import-ext",
            default="auto",
            help="Relative import extension: 'auto' (default), 'none' / '', '.js', or '.ts'.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Verify that existing output matches the generated SDK without modifying files.",
        )
        parser.add_argument(
            "--path-prefix",
            default=None,
            help="Override the URL prefix of generated paths (default: resolved from the URLconf).",
        )

    def handle(self, *args, **options):
        out = options["out"]
        check = bool(options["check"])
        import_ext = options["import_ext"]

        if check and not out:
            raise CommandError("--check requires -o/--out.")
        if not out:
            raise CommandError(
                "-o/--out <directory> is required when generating the TypeScript SDK."
            )
        if Path(out).suffix.lower() in (".ts", ".mts", ".cts"):
            raise CommandError(
                f"-o/--out expects a directory for the modular SDK, not a file path ({out})."
            )

        api = resolve_api(options["api"])
        prefix = options["path_prefix"]

        try:
            if check:
                result = check_sdk(api, out, path_prefix=prefix, import_ext=import_ext)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ TypeScript SDK in {result.directory} is up to date "
                        f"({len(result.unchanged)} file(s))."
                    )
                )
            else:
                result = sync_sdk(api, out, path_prefix=prefix, import_ext=import_ext)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✅ TypeScript SDK synced to {result.directory} "
                        f"({len(result.written)} written, {len(result.unchanged)} unchanged, "
                        f"{len(result.removed)} removed)"
                    )
                )
        except (SdkDriftError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
