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
# Modular TypeScript SDK directory (index.ts, runtime.ts, types/, endpoints/)
python manage.py generate_ts_sdk -o ../frontend/src/sdk

# Verify generated SDK is up to date in CI
python manage.py generate_ts_sdk -o ../frontend/src/sdk --check
```

Use `--import-ext auto|none|.js|.ts` to control relative import extensions (`auto` inspects `deno.json`, `tsconfig.json`, and `package.json`). Unchanged files are preserved and stale generated `.ts` files are pruned automatically.

Or from Python:

```python
import ninja_ts

ninja_ts.export_sdk(api, "frontend/src/sdk")
files = ninja_ts.generate_sdk(api)  # dict[str, str]
files = ninja_ts.generate_sdk(openapi_dict)  # any OpenAPI 3.x document
```

## Use it in the frontend

```typescript
import { createNinjaClient, isEndpointError } from "./sdk";

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
  if (isEndpointError(err, "GET /api/todos/{id}")) console.log(err.status, err.data);
}
```

Endpoints without inputs don't need a second argument; endpoints with path params or a required
body refuse to compile without them.

## Optionality rules

- **Inputs** follow Pydantic: a field is required unless it has a default.
- **Query / path parameters** strip `| null` (`q?: string`), since URL strings ignore `null`.
- **Outputs**: for schemas used only in responses, fields with a default are always serialized,
  so they're typed as present (`done: boolean`, not `done?: boolean`).
- Nullable JSON fields (`T | None`) become `T | null`.

## License

MIT
