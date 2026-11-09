"""``manage.py audit_ninja_schemas``: inspect response schemas for sensitive fields."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ninja_ts.management.commands.generate_ts_sdk import resolve_api
from ninja_ts.security import audit_schemas


class Command(BaseCommand):
    help = "Audit Django Ninja response schemas for sensitive fields (e.g. password hashes, secret keys)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--api",
            help="Dotted path to the NinjaAPI instance (e.g. config.api.api). "
            "Defaults to settings.NINJA_TS_API or the only NinjaAPI in the URLconf.",
        )
        parser.add_argument(
            "--fail-on-warnings",
            action="store_true",
            default=False,
            help="Exit with non-zero status code if sensitive fields are detected (ideal for CI pipelines).",
        )

    def handle(self, *args, **options):
        api = resolve_api(options.get("api"))
        warnings = audit_schemas(api)

        if not warnings:
            self.stdout.write(
                self.style.SUCCESS(
                    "✅ No sensitive fields detected in API response schemas."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"⚠️  Found {len(warnings)} potential security warning(s) in response schemas:"
            )
        )
        for warn in warnings:
            self.stdout.write(self.style.NOTICE(f"  • {warn}"))

        if options.get("fail_on_warnings"):
            raise CommandError(
                f"Security audit failed: {len(warnings)} sensitive field(s) exposed in API contracts."
            )
