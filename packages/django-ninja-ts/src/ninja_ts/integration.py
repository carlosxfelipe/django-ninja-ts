"""Django Ninja integration: schema extraction and modular TypeScript SDK export/check."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ninja_ts.compat import ensure_ninja_extra_compat
from ninja_ts.generator import (
    GENERATED_MARKER,
    TypeScriptGenerator,
    resolve_import_ext,
)

if TYPE_CHECKING:
    from ninja import NinjaAPI

    ApiOrSchema = NinjaAPI | dict[str, Any]


def get_openapi_schema(
    api: NinjaAPI, *, path_prefix: str | None = None
) -> dict[str, Any]:
    """Return the API's OpenAPI document as plain JSON-compatible data.

    ``path_prefix=None`` lets Ninja resolve the mount point from the URLconf (e.g. ``/api/``);
    pass ``""`` to generate paths relative to the API root without touching the URLconf.
    """
    from django.core.serializers.json import DjangoJSONEncoder

    ensure_ninja_extra_compat()
    schema = api.get_openapi_schema(path_prefix=path_prefix)
    # Round-trip through JSON: normalizes int status codes, Decimals, enums, lazy strings...
    return json.loads(json.dumps(schema, cls=DjangoJSONEncoder))


def _uses_response_exclusions(api: NinjaAPI) -> bool:
    """True if any operation may omit response fields (exclude_none/unset/defaults)."""
    for bound_router in api._get_bound_routers():
        for path_view in bound_router.path_operations.values():
            for operation in getattr(path_view, "operations", []):
                if any(
                    getattr(operation, f, False)
                    for f in ("exclude_none", "exclude_unset", "exclude_defaults")
                ):
                    return True
    return False


def _generator(api: ApiOrSchema, path_prefix: str | None) -> TypeScriptGenerator:
    if isinstance(api, dict):
        return TypeScriptGenerator(api)
    openapi = get_openapi_schema(api, path_prefix=path_prefix)
    return TypeScriptGenerator(
        openapi, responses_include_all_fields=not _uses_response_exclusions(api)
    )


@dataclass(frozen=True)
class SdkSyncResult:
    """Outcome of syncing a modular TypeScript SDK directory."""

    directory: Path
    written: tuple[str, ...]
    unchanged: tuple[str, ...]
    removed: tuple[str, ...]
    import_ext: str


class SdkDriftError(ValueError):
    """Raised by ``check_sdk`` when generated SDK files are out of date."""

    def __init__(
        self,
        message: str,
        *,
        missing: tuple[str, ...] = (),
        changed: tuple[str, ...] = (),
        stale: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.missing = missing
        self.changed = changed
        self.stale = stale


def generate_sdk(
    api: ApiOrSchema,
    *,
    path_prefix: str | None = None,
    import_ext: str = "",
) -> dict[str, str]:
    """Generate the modular TypeScript SDK mapping relative file paths to TypeScript contents."""
    return _generator(api, path_prefix).generate_sdk(import_ext=import_ext)


def _write(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _scan_managed_ts_files(directory: Path) -> dict[str, str]:
    """Return {posix_rel_path: content} for existing generated .ts files inside directory."""
    managed: dict[str, str] = {}
    if not directory.exists():
        return managed
    for path in sorted(directory.rglob("*.ts")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if GENERATED_MARKER in text:
            managed[path.relative_to(directory).as_posix()] = text
    return managed


def sync_sdk(
    api: ApiOrSchema,
    directory: str | Path,
    *,
    path_prefix: str | None = None,
    import_ext: str = "auto",
) -> SdkSyncResult:
    """Sync modular SDK files into ``directory``, skipping unchanged and pruning stale files."""
    target = Path(directory)
    if target.exists() and not target.is_dir():
        raise ValueError(f"{target} is not a directory.")

    resolved_ext = resolve_import_ext(import_ext, target)
    expected = generate_sdk(api, path_prefix=path_prefix, import_ext=resolved_ext)

    for rel in expected:
        dest = target / rel
        if dest.exists():
            if dest.is_dir():
                raise ValueError(f"Expected file at {dest}, found directory.")
            existing = dest.read_text(encoding="utf-8")
            if GENERATED_MARKER not in existing:
                raise ValueError(f"Refusing to overwrite unmanaged file: {dest}")

    written: list[str] = []
    unchanged: list[str] = []
    for rel, content in sorted(expected.items()):
        dest = target / rel
        if dest.exists() and dest.read_text(encoding="utf-8") == content:
            unchanged.append(rel)
            continue
        _write(dest, content)
        written.append(rel)

    removed: list[str] = []
    for rel in sorted(_scan_managed_ts_files(target)):
        if rel not in expected:
            (target / rel).unlink()
            removed.append(rel)

    for subdir in ("types", "endpoints"):
        subpath = target / subdir
        if subpath.is_dir() and not any(subpath.iterdir()):
            subpath.rmdir()

    return SdkSyncResult(
        directory=target,
        written=tuple(written),
        unchanged=tuple(unchanged),
        removed=tuple(removed),
        import_ext=resolved_ext,
    )


def export_sdk(
    api: ApiOrSchema,
    directory: str | Path,
    *,
    path_prefix: str | None = None,
    import_ext: str = "auto",
) -> Path:
    """Write modular TypeScript SDK files into ``directory`` and prune stale generated files."""
    return sync_sdk(
        api, directory, path_prefix=path_prefix, import_ext=import_ext
    ).directory


def check_sdk(
    api: ApiOrSchema,
    directory: str | Path,
    *,
    path_prefix: str | None = None,
    import_ext: str = "auto",
) -> SdkSyncResult:
    """Verify ``directory`` matches the generated SDK; raise ``SdkDriftError`` on drift."""
    target = Path(directory)
    resolved_ext = resolve_import_ext(import_ext, target)
    expected = generate_sdk(api, path_prefix=path_prefix, import_ext=resolved_ext)

    if not target.exists():
        missing = tuple(sorted(expected))
        raise SdkDriftError(
            f"SDK directory {target} does not exist (missing {len(missing)} file(s)).",
            missing=missing,
        )
    if not target.is_dir():
        raise SdkDriftError(f"{target} is not a directory.")

    missing: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for rel, content in sorted(expected.items()):
        dest = target / rel
        if not dest.exists():
            missing.append(rel)
        elif dest.is_dir() or dest.read_text(encoding="utf-8") != content:
            changed.append(rel)
        else:
            unchanged.append(rel)

    stale = tuple(
        rel for rel in sorted(_scan_managed_ts_files(target)) if rel not in expected
    )

    if missing or changed or stale:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if changed:
            parts.append(f"changed: {', '.join(changed)}")
        if stale:
            parts.append(f"stale: {', '.join(stale)}")
        raise SdkDriftError(
            f"TypeScript SDK in {target} is out of date ({'; '.join(parts)}).",
            missing=tuple(missing),
            changed=tuple(changed),
            stale=stale,
        )

    return SdkSyncResult(
        directory=target,
        written=(),
        unchanged=tuple(unchanged),
        removed=(),
        import_ext=resolved_ext,
    )
