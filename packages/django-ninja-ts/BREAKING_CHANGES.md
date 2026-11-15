# Breaking Changes — `django-ninja-ts`

A record of backwards-incompatible changes introduced before the initial release of the package.

## 1. `onRequest` Hook Signature (`NinjaRequestConfig`)

The `onRequest` hook in `NinjaClientOptions` and `BaseRequestOptions` now receives a single `NinjaRequestConfig` object (`{ endpoint, url, init }`) instead of 3 positional arguments `(endpoint, init, context)`.

### Rationale
Enables future extensibility without breaking existing callback signatures and aligns with the convention used by the Gota TypeScript SDK.

### Before
```ts
const api = createNinjaClient("http://localhost:8000", {
  onRequest(endpoint, init, context) {
    init.headers.set("X-Trace", "1");
    console.log(endpoint, context.url);
  },
});
```

### After
```ts
import { createNinjaClient, type NinjaRequestConfig } from "./api";

const api = createNinjaClient("http://localhost:8000", {
  onRequest({ endpoint, url, init }: NinjaRequestConfig) {
    init.headers.set("X-Trace", "1");
    console.log(endpoint, url);
  },
});
```

---

## 2. Hook Execution Order for `onResponse` and `onError`

The `onResponse` and `onError` hooks now always execute in `clientOptions -> options` order (global client hook first, per-request hook second), consistent with `onRequest`.

### Before
- `onRequest`: `clientOptions -> options`
- `onResponse`: `options -> clientOptions`
- `onError`: `options -> clientOptions`

### After
- `onRequest`: `clientOptions -> options`
- `onResponse`: `clientOptions -> options`
- `onError`: `clientOptions -> options`

---

## 3. Modular Directory SDK Only (Removed Monolithic `api.ts`)

`generate_sdk()` and `export_sdk()` now exclusively emit the modular multi-file SDK directory (`index.ts`, `runtime.ts`, `types/*.ts`, `endpoints/*.ts`), matching `gota`'s layout.

- `generate_sdk(...)` returns `dict[str, str]` (relative file paths to TypeScript contents) instead of a single `str`.
- `export_sdk(api, directory)` / `sync_sdk(api, directory)` / `check_sdk(api, directory)` and `manage.py generate_ts_sdk -o <dir>` target an output directory instead of a single `.ts` file (no `--modular` flag needed).
- Removed the monolithic `/api/sdk.ts` view (`create_sdk_view`, `sdk_url` in `ninja_ts.install()`), as well as all standalone `.d.ts` generation and serving (`generate_types()`, `export_types()`, `check_types()`, `install()`, `create_types_view()`, `--types-only`, and `/api/types.d.ts`), matching `gota`. Use `import type { ... } from "./sdk"` against the modular SDK when only types are needed.
