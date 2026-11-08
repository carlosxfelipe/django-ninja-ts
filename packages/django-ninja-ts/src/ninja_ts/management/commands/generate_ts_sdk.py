"""``manage.py generate_ts_sdk``: export the TypeScript SDK / declarations (ideal for CI)."""

from __future__ import annotations

import gc
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.module_loading import import_string

from ninja_ts.integration import export_sdk, export_types, generate_sdk, generate_types


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
    help = "Generate a zero-dependency TypeScript SDK (or .d.ts declarations) from a Django Ninja API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--api",
            help="Dotted path to the NinjaAPI instance (e.g. config.api.api). "
            "Defaults to settings.NINJA_TS_API or the only NinjaAPI in the URLconf.",
        )
        parser.add_argument(
            "-o",
            "--out",
            help="Output file (parent directories are created). Prints to stdout when omitted.",
        )
        parser.add_argument(
            "--types-only",
            action="store_true",
            help="Emit TypeScript declarations (.d.ts) instead of the full SDK.",
        )
        parser.add_argument(
            "--path-prefix",
            default=None,
            help="Override the URL prefix of generated paths (default: resolved from the URLconf).",
        )

    def handle(self, *args, **options):
        api = resolve_api(options["api"])
        prefix = options["path_prefix"]
        types_only = options["types_only"]

        if options["out"]:
            exporter = export_types if types_only else export_sdk
            target = exporter(api, options["out"], path_prefix=prefix)
            kind = "TypeScript declarations" if types_only else "TypeScript SDK"
            self.stdout.write(self.style.SUCCESS(f"✅ {kind} written to {target}"))
        else:
            generate = generate_types if types_only else generate_sdk
            self.stdout.write(generate(api, path_prefix=prefix), ending="")
