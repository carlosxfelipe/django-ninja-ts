# django-ninja-ts

Generate a **zero-dependency, end-to-end type-safe TypeScript SDK** from your
[Django Ninja](https://django-ninja.dev) API — no Node.js, npm or OpenAPI codegen toolchain required.

- Pydantic schemas → TypeScript interfaces (with JSDoc from `description`, `examples`, `default`).
- `Literal[...]` / enums → string literal unions; `Optional[T]` → `T | null`.
- Every route → a typed entry in `NinjaEndpoints` (`params`, `query`, `body`, `response`, `error`).
- `createNinjaClient()` runtime built on native `fetch` (browser, Node 18+, Deno, Bun).
- Works with `django-ninja-extra` controllers (e.g. `django-ninja-jwt`).

## Install

```bash
uv add django-ninja-ts
```

```python
# settings.py
INSTALLED_APPS = [..., "ninja_ts"]
NINJA_TS_API = "config.api.api"  # optional: dotted path to your NinjaAPI
```

## Generate the SDK

At build time / in CI (recommended):

```bash
python manage.py generate_ts_sdk -o ../frontend/src/api.ts
python manage.py generate_ts_sdk --types-only -o ../frontend/src/api.d.ts
```

Or from Python:

```python
import ninja_ts

ninja_ts.export_sdk(api, "frontend/src/api.ts")
ninja_ts.export_types(api, "frontend/src/api.d.ts")
code = ninja_ts.generate_sdk(api)  # str
code = ninja_ts.generate_sdk(openapi_dict)  # any OpenAPI 3.x document
```

Or serve it during development (hidden from the OpenAPI schema, enabled only when `DEBUG=True`):

```python
# config/api.py — after registering routers, before urls.py reads api.urls
ninja_ts.install(api)  # GET /api/sdk.ts and /api/types.d.ts
```

## Use it in the frontend

```typescript
import { createNinjaClient, NinjaApiError } from "./api";

const api = createNinjaClient("http://localhost:8000", {
  headers: async () => ({ Authorization: `Bearer ${await getToken()}` }),
});

const todos = await api.fetch("GET /api/todos");                        // TodoOut[]
const todo = await api.fetch("GET /api/todos/{id}", { params: { id: "todo_1" } });
const created = await api.fetch("POST /api/todos", {
  body: { title: "Ship it", priority: "high" },                         // "low" | "normal" | "high"
});

try {
  await api.fetch("GET /api/todos/{id}", { params: { id: "nope" } });
} catch (err) {
  if (err instanceof NinjaApiError) console.log(err.status, err.data);
}
```

Endpoints without inputs don't need a second argument; endpoints with path params or a required
body refuse to compile without them.

## Optionality rules

- **Inputs** follow Pydantic: a field is required unless it has a default.
- **Outputs**: for schemas used only in responses, fields with a default are always serialized,
  so they're typed as present (`done: boolean`, not `done?: boolean`).
- Nullable fields (`T | None`) become `T | null`.

## License

MIT
