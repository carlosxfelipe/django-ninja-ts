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
