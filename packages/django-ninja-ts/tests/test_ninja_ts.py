import re
import shutil
import subprocess
from pathlib import Path

import ninja_ts
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from ninja_ts import TypeScriptGenerator
from ninja_ts.generator import GENERATED_MARKER, detect_ts_import_extension

from .sample_api import api


@pytest.fixture(scope="module")
def sdk() -> dict[str, str]:
    return ninja_ts.generate_sdk(api)


@pytest.fixture(scope="module")
def sdk_text(sdk: dict[str, str]) -> str:
    return "\n".join(sdk.values())


def endpoint_block(ts: str, key: str) -> str:
    match = re.search(rf'  "{re.escape(key)}": \{{\n(.*?)\n  \}};', ts, re.DOTALL)
    assert match, f"endpoint {key!r} not found"
    return match.group(1)


# --------------------------------------------------------------------------- schemas


def test_request_schema_follows_pydantic_optionality(sdk_text):
    assert "export interface TodoIn {" in sdk_text
    assert "  title: string;\n" in sdk_text
    assert '  priority?: "low" | "normal" | "high";\n' in sdk_text
    assert "  notes?: string | null;\n" in sdk_text


def test_response_only_schema_marks_all_fields_present(sdk_text):
    todo_out = sdk_text[sdk_text.index("export interface TodoOut {") :]
    todo_out = todo_out[: todo_out.index("}\n")]
    assert "  done: boolean;" in todo_out
    assert "  notes: string | null;" in todo_out


def test_jsdoc_from_field_metadata(sdk_text):
    assert '   * Task title\n   * @example "Review pull requests"\n' in sdk_text
    assert '   * @default "normal"\n' in sdk_text


def test_response_exclusions_disable_all_fields_present():
    from ninja import NinjaAPI

    from .sample_api import TodoOut

    local = NinjaAPI(urls_namespace="exclusions")

    @local.get("/todo", response=TodoOut, exclude_none=True)
    def todo(request):
        return {}

    ts = "\n".join(ninja_ts.generate_sdk(local, path_prefix="").values())
    assert "  notes?: string | null;" in ts
    assert "  done?: boolean;" in ts


# --------------------------------------------------------------------------- endpoints


def test_endpoint_without_inputs(sdk_text):
    block = endpoint_block(sdk_text, "GET /api/health")
    assert "response: unknown;" in block
    assert "error: NinjaHttpError;" in block
    assert "request: { params?: never; query?: never; body?: never };" in block


def test_path_params_and_response(sdk_text):
    block = endpoint_block(sdk_text, "GET /api/todos/{id}")
    assert "params: { id: string };" in block
    assert "response: TodoOut;" in block
    assert "error: NinjaHttpError | NinjaValidationError;" in block


def test_endpoint_with_explicit_error_schemas(sdk_text):
    block = endpoint_block(sdk_text, "GET /api/todos/{id}/strict")
    assert "params: { id: string };" in block
    assert "response: TodoOut;" in block
    assert "error: ErrorDetail | Message;" in block
    assert (
        'export type ResponseError<K extends EndpointKey> = NinjaEndpoints[K]["error"];'
        in sdk_text
    )


def test_nextjs_caching_and_duplex_types(sdk):
    runtime_ts = sdk["runtime.ts"]
    assert "export interface NextFetchRequestConfig {" in runtime_ts
    assert "revalidate?: number | false;" in runtime_ts
    assert "tags?: string[];" in runtime_ts
    assert "next?: NextFetchRequestConfig;" in runtime_ts
    assert 'duplex?: "half";' in runtime_ts
    assert (
        'options.duplex ?? (isReadableStream(init.body) ? "half" : undefined)'
        in runtime_ts
    )
    assert "if (duplex) {\n      init.duplex = duplex;\n    }" in runtime_ts


def test_path_param_types_come_from_annotations(sdk_text):
    block = endpoint_block(sdk_text, "DELETE /api/todos/{id}")
    assert "params: { id: number };" in block
    assert "response: void;" in block  # 204


def test_wildcard_catch_all_path_param(sdk_text):
    block = endpoint_block(sdk_text, "GET /api/todos/files/{filepath}")
    assert "params: { filepath: string | string[] };" in block
    assert "response: Message;" in block


def test_client_lifecycle_hooks(sdk):
    runtime_ts = sdk["runtime.ts"]
    assert "export interface NinjaRequestInit extends RequestInit {" in runtime_ts
    assert "export interface NinjaRequestConfig {" in runtime_ts
    assert "headers: Headers;" in runtime_ts
    assert (
        "onRequest?: (config: NinjaRequestConfig) => Promise<void> | void;"
        in runtime_ts
    )
    assert (
        "onResponse?: (response: Response, context: RequestContext) => Promise<void> | void;"
        in runtime_ts
    )
    assert (
        "onError?: (error: NinjaApiError | Error, context: RequestContext) => Promise<void> | void;"
        in runtime_ts
    )
    assert "if (clientOptions.onRequest) {" in runtime_ts
    assert "await clientOptions.onRequest({ endpoint, url, init });" in runtime_ts
    assert "if (options.onRequest) {" in runtime_ts
    assert "await options.onRequest({ endpoint, url, init });" in runtime_ts
    assert "if (clientOptions.onResponse) {" in runtime_ts
    assert "await clientOptions.onResponse(response, context);" in runtime_ts
    assert "if (options.onResponse) {" in runtime_ts
    assert "await options.onResponse(response, context);" in runtime_ts
    assert "if (clientOptions.onError) {" in runtime_ts
    assert "await clientOptions.onError(errObj, context);" in runtime_ts
    assert "if (options.onError) {" in runtime_ts
    assert "await options.onError(errObj, context);" in runtime_ts


def test_deprecated_and_summary_jsdoc(sdk_text):
    assert "   * Delete todo\n   * @deprecated\n" in sdk_text


def test_query_schema_is_flattened_and_optional(sdk, sdk_text):
    block = endpoint_block(sdk_text, "GET /api/todos")
    assert "query: { limit?: number; q?: string };" in block
    assert "query?: { limit?: number; q?: string }" in block
    assert "response: TodoOut[];" in block
    assert "types/_shared.ts" not in sdk
    assert "TodoFilters" not in sdk_text


def test_required_query_makes_query_required(sdk_text):
    block = endpoint_block(sdk_text, "GET /api/todos/search/required")
    assert (
        "request: { params?: never; query: { term: string }; body?: never };" in block
    )


def test_json_body_and_created_status(sdk_text):
    block = endpoint_block(sdk_text, "POST /api/todos")
    assert "body: TodoIn;" in block
    assert "response: TodoOut;" in block  # 201 is the lowest 2xx


def test_multipart_body_accepts_object_or_formdata(sdk, sdk_text):
    block = endpoint_block(sdk_text, "POST /api/todos/{id}/attachments")
    assert "body: { file: Blob; caption: string } | FormData;" in block
    assert '  "POST /api/todos/{id}/attachments": "multipart",\n' in sdk["index.ts"]


# --------------------------------------------------------------------------- output modes


def test_sdk_contains_modular_runtime(sdk):
    assert "export function createNinjaClient(" in sdk["index.ts"]
    assert "export function isEndpointError" in sdk["index.ts"]
    assert "export function createNinjaClientFor" in sdk["runtime.ts"]
    assert "export class NinjaApiError" in sdk["runtime.ts"]
    assert "declare " not in sdk["index.ts"]
    assert "declare " not in sdk["runtime.ts"]


def test_output_is_deterministic():
    assert ninja_ts.generate_sdk(api) == ninja_ts.generate_sdk(api)


# --------------------------------------------------------------------------- raw OpenAPI


def test_raw_openapi_names_refs_unions_and_reserved_names():
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "Raw", "version": "1"},
        "paths": {
            "/items/{item-id}": {
                "parameters": [
                    {
                        "name": "item-id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "put": {
                    "requestBody": {"$ref": "#/components/requestBodies/ItemBody"},
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Promise"}
                                }
                            }
                        }
                    },
                },
            }
        },
        "components": {
            "requestBodies": {
                "ItemBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/my.Item"}
                        }
                    },
                }
            },
            "schemas": {
                "my.Item": {
                    "type": "object",
                    "properties": {
                        "kind": {"const": "item"},
                        "tags": {
                            "type": "array",
                            "items": {
                                "anyOf": [{"type": "string"}, {"type": "integer"}]
                            },
                        },
                        "meta": {
                            "type": "object",
                            "additionalProperties": {"type": "number"},
                        },
                        "weird-key": {"type": ["string", "null"]},
                    },
                    "required": ["kind"],
                },
                "Promise": {"enum": ["a", "b"]},
            },
        },
    }
    ts = "\n".join(TypeScriptGenerator(openapi).generate_sdk().values())
    assert "export interface my_Item {" in ts
    assert '  kind: "item";' in ts
    assert "  tags?: (string | number)[];" in ts
    assert "  meta?: Record<string, number>;" in ts
    assert '  "weird-key"?: string | null;' in ts
    assert 'export type Promise_2 = "a" | "b";' in ts  # never shadow TS built-ins
    block = endpoint_block(ts, "PUT /items/{item-id}")
    assert '"item-id": number' in block
    assert "body?: my_Item" in block  # requestBody.required = false
    assert "response: Promise_2;" in block


def test_generate_from_raw_dict_via_public_api():
    openapi = {"openapi": "3.1.0", "info": {"title": "Empty"}, "paths": {}}
    files = ninja_ts.generate_sdk(openapi)
    assert "export interface NinjaEndpoints {}" in files["index.ts"]


def test_schema_jsdoc_and_date_time_inference():
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "DocTest"},
        "paths": {
            "/events": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/EventItem"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "EventItem": {
                    "type": "object",
                    "title": "A single event item in the audit log",
                    "properties": {
                        "created_at": {"type": "string", "title": "created_at"},
                        "updated_at": {"type": "string", "title": "updated_at"},
                        "timestamp": {"type": "string"},
                        "scheduled_time": {"type": "string", "format": "date-time"},
                    },
                }
            }
        },
    }
    ts = "\n".join(TypeScriptGenerator(openapi).generate_sdk().values())
    assert "A single event item in the audit log" in ts
    assert "@format date-time" in ts


# --------------------------------------------------------------------------- runtime & types


def test_ninja_api_error_headers_and_timeout_types(sdk):
    runtime_ts = sdk["runtime.ts"]
    assert "readonly headers: Headers;" in runtime_ts
    assert "readonly statusText: string;" in runtime_ts
    assert "this.headers = response.headers;" in runtime_ts
    assert "this.statusText = response.statusText;" in runtime_ts
    assert "Object.setPrototypeOf(this, NinjaApiError.prototype);" in runtime_ts
    assert "export function isNinjaApiError<T = unknown>" in runtime_ts
    assert (
        "async function readErrorBody(response: Response): Promise<unknown>"
        in runtime_ts
    )
    assert "timeoutMs?: number;" in runtime_ts
    assert "createTimeoutSignal(timeoutMs)" in runtime_ts
    assert "combineSignals(options.signal, timeoutSignal)" in runtime_ts
    assert "const cleanup = () => {" in runtime_ts
    assert 'signalA.removeEventListener("abort", handleA);' in runtime_ts
    assert 'signalB.removeEventListener("abort", handleB);' in runtime_ts


def test_retry_config_types_and_runtime(sdk):
    runtime_ts = sdk["runtime.ts"]
    assert "export interface NinjaRetryConfig {" in runtime_ts
    assert "attempts?: number;" in runtime_ts
    assert "delayMs?: number;" in runtime_ts
    assert "statusCodes?: number[];" in runtime_ts
    assert "methods?: string[];" in runtime_ts
    assert "retry?: boolean | number | NinjaRetryConfig;" in runtime_ts
    assert (
        'export const DEFAULT_RETRY_METHODS: readonly string[] = ["GET", "HEAD", "OPTIONS", "PUT", "DELETE"];'
        in runtime_ts
    )
    assert "!retryMethods.includes(method.toUpperCase())" in runtime_ts
    assert (
        "function retryDelay(attempt: number, baseDelay: number, res?: Response)"
        in runtime_ts
    )
    assert 'res.headers.get("Retry-After")' in runtime_ts
    assert "/^\\d+$/.test(retryAfter)" in runtime_ts
    assert "Math.random()" in runtime_ts
    assert "0.5 + Math.random() * 0.5" in runtime_ts
    assert "Date.parse(retryAfter)" in runtime_ts


def test_upload_detection_and_form_data_cleanup(sdk):
    runtime_ts = sdk["runtime.ts"]
    assert "function hasBlobValue(value: unknown" in runtime_ts
    assert 'headers.delete("Content-Type");' in runtime_ts
    assert "BINARY_CONTENT_TYPE = /^(image|audio|video)\\/" in runtime_ts


def test_validation_error_and_context_types(sdk):
    runtime_ts = sdk["runtime.ts"]
    assert "export interface NinjaHttpError {" in runtime_ts
    assert "export interface NinjaValidationErrorItem {" in runtime_ts
    assert "export interface NinjaValidationError {" in runtime_ts
    assert "export interface RequestContext {" in runtime_ts
    assert "endpoint: string;\n  url: string;" in runtime_ts


def test_query_param_serialization_and_return_cast(sdk):
    runtime_ts = sdk["runtime.ts"]
    index_ts = sdk["index.ts"]
    assert "function appendQueryParam(search: URLSearchParams" in runtime_ts
    assert "appendQueryParam(search, key, value);" in runtime_ts
    assert 'as Promise<Endpoints[typeof endpoint]["response"]>;' in runtime_ts
    assert "ResponseData<any>" not in index_ts
    assert "{} extends" not in runtime_ts
    assert "{} extends" not in index_ts


def test_audit_schemas_detects_sensitive_response_fields():
    from ninja import Field, NinjaAPI, Schema
    from ninja_ts import audit_schemas

    local = NinjaAPI(urls_namespace="security_test")

    class SensitiveUserOut(Schema):
        id: int
        username: str
        password_hash: str
        secret_key: str
        salt_field: str = Field(description="safe for public display, nowarn")

    class UserInput(Schema):
        username: str
        password: str  # Allowed in request payload!

    @local.post("/register", response=SensitiveUserOut)
    def register(request, payload: UserInput):
        return {}

    warnings = audit_schemas(local)
    assert len(warnings) == 2
    assert any("password_hash" in w and "password hash" in w for w in warnings)
    assert any("secret_key" in w and "secret key" in w for w in warnings)
    # nowarn field and request-only password field should not trigger warnings
    assert not any("salt_field" in w for w in warnings)
    assert not any("UserInput" in w for w in warnings)


def test_audit_ninja_schemas_management_command():
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("audit_ninja_schemas", stdout=out)
    output = out.getvalue()
    assert "No sensitive fields detected" in output


def test_management_command_writes_files(tmp_path: Path):
    sdk_dir = tmp_path / "nested" / "sdk"
    call_command("generate_ts_sdk", out=str(sdk_dir), import_ext="none")
    assert (sdk_dir / "index.ts").read_text() == ninja_ts.generate_sdk(api)["index.ts"]


# --------------------------------------------------------------------------- TypeScript compiler


CONSUMER = """
import {
  createNinjaClient,
  NinjaApiError,
  isAbortError,
  isNinjaApiError,
  parseNinjaError,
  DEFAULT_RETRY_METHODS,
  type ResponseData,
  type ResponseError,
  type NextFetchRequestConfig,
  type NinjaErrorDetails,
  type NinjaQueryOptions,
  type NinjaRetryConfig,
  type NinjaRequestInit,
  type NinjaRequestConfig,
  type RequestContext,
  type NinjaValidationError,
} from "./api";

const retryPolicy: NinjaRetryConfig = {
  attempts: 2,
  delayMs: 150,
  methods: [...DEFAULT_RETRY_METHODS, "PATCH"],
  statusCodes: [503],
};
const nextConfig: NextFetchRequestConfig = { revalidate: 60, tags: ["global"] };
const api = createNinjaClient("http://localhost:8000", {
  headers: async () => ({ Authorization: "Bearer x" }),
  cache: "no-store",
  next: nextConfig,
  timeoutMs: 5000,
  retry: retryPolicy,
  onRequest(config: NinjaRequestConfig) {
    config.init.headers.set("X-Client-Hook", "active");
    console.log("Sending", config.url);
  },
  onResponse(res, context) {
    if (!res.ok) console.warn("Request failed with status", res.status, context.endpoint);
  },
  onError(err, context) {
    console.error("Client hook error:", err.message, context.endpoint);
  },
  async onUnauthorized(context) {
    console.warn("Unauthorized:", context.endpoint);
    return false;
  },
});

async function main(): Promise<void> {
  const list: ResponseData<"GET /api/todos"> = await api.fetch("GET /api/todos", {
    next: { revalidate: 30, tags: ["todos"] },
    timeoutMs: 2000,
    retry: 3,
    onRequest(config) {
      console.log("Per request hook for", config.endpoint, config.url);
    },
    onResponse(res, ctx) {
      console.log("Per request response for", ctx.endpoint, res.status);
    },
    onError(err, ctx) {
      console.log("Per request error for", ctx.endpoint, err.message);
    },
  });
  const filtered = await api.fetch("GET /api/todos", { query: { limit: 5, q: "milk" }, retry: false });
  const retriedBool = await api.fetch("GET /api/todos", { retry: true });
  const retriedPartial = await api.fetch("GET /api/todos", { retry: { delayMs: 100 } });
  const one = await api.fetch("GET /api/todos/{id}", { params: { id: "todo_1" } });
  const done: boolean = one.done;
  const created = await api.fetch("POST /api/todos", { body: { title: "Ship", priority: "high" } });
  const removed: void = await api.fetch("DELETE /api/todos/{id}", { params: { id: 1 } });
  await api.fetch("POST /api/todos/{id}/attachments", {
    params: { id: "todo_1" },
    body: { file: new Blob(["x"]), caption: "c" },
    duplex: "half",
  });

  // Wildcard / catch-all path params as string and string[]
  const file1 = await api.fetch("GET /api/todos/files/{filepath}", {
    params: { filepath: "docs/readme.md" },
  });
  const file2 = await api.fetch("GET /api/todos/files/{filepath}", {
    params: { filepath: ["nested", "deep", "file.txt"] },
  });

  // Strict route error response typing
  type StrictError = ResponseError<"GET /api/todos/{id}/strict">;
  type DefaultError = ResponseError<"GET /api/todos">;

  const qOpts: NinjaQueryOptions<"GET /api/todos", ResponseData<"GET /api/todos">> =
    api.queryOptions("GET /api/todos", { query: { limit: 5 } });
  const qList = await qOpts.queryFn();
  // @ts-expect-error queryOptions requires params when path param is present
  api.queryOptions("GET /api/todos/{id}");

  // @ts-expect-error path params are required
  await api.fetch("GET /api/todos/{id}");
  // @ts-expect-error priority must be a known literal
  await api.fetch("POST /api/todos", { body: { title: "Ship", priority: "urgent" } });
  // @ts-expect-error unknown endpoint
  await api.fetch("GET /api/nope");
  // @ts-expect-error required query
  await api.fetch("GET /api/todos/search/required");
  // @ts-expect-error nullable query param omits null
  await api.fetch("GET /api/todos", { query: { q: null } });
  // @ts-expect-error endpoint takes no body
  await api.fetch("GET /api/health", { body: { x: 1 } });

  try {
    await api.fetch("GET /api/todos/{id}/strict", { params: { id: "todo_1" } });
  } catch (err) {
    const parsed: NinjaErrorDetails = parseNinjaError(err);
    if (isAbortError(err)) {
      console.log(parsed.kind);
    }
    if (isNinjaApiError<StrictError>(err)) {
      const errData: StrictError = err.data;
      const statusText: string = err.statusText;
      const contentType: string | null = err.headers.get("content-type");
      console.log(err.status, statusText, errData, contentType);
    }
  }
  console.log(list, qList, filtered, retriedBool, retriedPartial, done, created, removed, file1, file2);
}

void main();
"""


tsc_path = shutil.which("tsc")
npx_path = shutil.which("npx")
TSC_CMD: list[str] | None = (
    [tsc_path]
    if tsc_path
    else ([npx_path, "--yes", "-p", "typescript", "tsc"] if npx_path else None)
)


@pytest.mark.skipif(not TSC_CMD, reason="TypeScript compiler (tsc/npx) not on PATH")
def test_generated_code_type_checks_with_tsc(tmp_path: Path):
    assert TSC_CMD is not None
    ninja_ts.export_sdk(api, tmp_path / "sdk", import_ext="")
    (tmp_path / "consumer.ts").write_text(
        CONSUMER.replace('from "./api"', 'from "./sdk/index"')
    )
    flags = [
        "--noEmit",
        "--strict",
        "--exactOptionalPropertyTypes",
        "--noUncheckedIndexedAccess",
        "--noPropertyAccessFromIndexSignature",
        "--isolatedModules",
        "--target",
        "es2022",
        "--module",
        "esnext",
        "--moduleResolution",
        "bundler",
        "--lib",
        "es2022,dom,dom.iterable",
        "--skipLibCheck",
    ]
    result = subprocess.run(
        [*TSC_CMD, *flags, "consumer.ts"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


node_path = shutil.which("node")


@pytest.mark.skipif(not node_path, reason="Node.js not on PATH")
def test_runtime_hooks_cache_and_read_body(tmp_path: Path):
    assert node_path is not None
    ninja_ts.export_sdk(api, tmp_path / "sdk", import_ext=".ts")
    runner = """
import assert from "node:assert/strict";
import { createNinjaClient, isEndpointError } from "./sdk/index.ts";

const order = [];
let seenCache;

const client = createNinjaClient("https://example.test", {
  cache: "no-store",
  onRequest({ endpoint, url, init }) {
    order.push("client:req");
    assert.equal(endpoint, "GET /api/todos");
    assert.equal(url, "https://example.test/api/todos");
    init.headers.set("X-Test", "1");
  },
  onResponse() {
    order.push("client:res");
  },
  onError() {
    order.push("client:err");
  },
  async fetch(_url, init) {
    seenCache = init.cache;
    if (init.headers.get("X-Fail") === "1") {
      return {
        ok: false,
        status: 500,
        statusText: "Server Error",
        headers: new Headers({ "content-type": "application/json" }),
        async text() {
          return JSON.stringify({ detail: "boom" });
        },
      };
    }
    if (init.headers.get("X-Xml") === "1") {
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "application/xml" }),
        async text() {
          return "<ok/>";
        },
      };
    }
    if (init.headers.get("X-Partial-Json") === "1") {
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers({ "content-type": "application/json" }),
        async json() {
          return [{ id: "1" }];
        },
      };
    }
    return {
      ok: true,
      status: 204,
      statusText: "No Content",
      headers: new Headers(),
    };
  },
});

const res204 = await client.fetch("GET /api/todos", {
  onRequest() {
    order.push("req:req");
  },
  onResponse() {
    order.push("req:res");
  },
});
assert.equal(res204, undefined);
assert.equal(seenCache, "no-store");
assert.deepEqual(order, ["client:req", "req:req", "client:res", "req:res"]);

order.length = 0;
await assert.rejects(
  () =>
    client.fetch("GET /api/todos", {
      cache: "reload",
      headers: { "X-Fail": "1" },
      onResponse() {
        order.push("req:res");
      },
      onError() {
        order.push("req:err");
      },
    }),
  (err) => isEndpointError(err, "GET /api/todos") && /boom/.test(err.message),
);
assert.equal(seenCache, "reload");
assert.deepEqual(order, ["client:req", "client:res", "req:res", "client:err", "req:err"]);

const xml = await client.fetch("GET /api/todos", { headers: { "X-Xml": "1" } });
assert.equal(xml, "<ok/>");

const partialJson = await client.fetch("GET /api/todos", { headers: { "X-Partial-Json": "1" } });
assert.deepEqual(partialJson, [{ id: "1" }]);
"""
    (tmp_path / "runner.mts").write_text(runner)
    result = subprocess.run(
        [node_path, "--experimental-strip-types", "runner.mts"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not node_path, reason="Node.js not on PATH")
def test_query_options_parse_error_abort_and_retry_cancellation(tmp_path: Path):
    assert node_path is not None
    ninja_ts.export_sdk(api, tmp_path / "sdk", import_ext=".ts")
    runner = """
import assert from "node:assert/strict";
import {
  createNinjaClient,
  isAbortError,
  isNinjaApiError,
  parseNinjaError,
} from "./sdk/index.ts";

let onErrorCount = 0;
let cancelledRetryBody = false;

const client = createNinjaClient("https://example.test", {
  onError() {
    onErrorCount++;
  },
  async fetch(url, init) {
    const mode = init.headers.get("X-Mode");
    if (mode === "ok") {
      return new Response(JSON.stringify([{ id: "1", title: "A", priority: "low", done: false }]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (mode === "422") {
      return new Response(
        JSON.stringify({
          detail: [{ loc: ["body", "title"], msg: "Too short", type: "string_too_short" }],
        }),
        {
          status: 422,
          headers: { "content-type": "application/json", "X-Request-Id": "req-422" },
        },
      );
    }
    if (mode === "500") {
      return new Response(JSON.stringify({ detail: "boom" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });
    }
    if (mode === "network") {
      throw new TypeError("fetch failed");
    }
    if (mode === "slow") {
      return await new Promise((_resolve, reject) => {
        const timer = setTimeout(() => {}, 10_000);
        init.signal?.addEventListener(
          "abort",
          () => {
            clearTimeout(timer);
            reject(init.signal?.reason);
          },
          { once: true },
        );
      });
    }
    if (mode === "retry-503") {
      return {
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        headers: new Headers({ "Retry-After": "10", "content-type": "application/json" }),
        body: {
          async cancel() {
            cancelledRetryBody = true;
          },
        },
        async text() {
          return JSON.stringify({ detail: "busy" });
        },
      };
    }
    throw new Error(`unexpected mode: ${mode} (${url})`);
  },
});

// 1. queryOptions builds stable queryKey and forwards AbortSignal
const qOpts = client.queryOptions("GET /api/todos", {
  query: { limit: 5 },
  headers: { "X-Mode": "ok" },
});
assert.deepEqual(qOpts.queryKey, ["GET /api/todos", { query: { limit: 5 } }]);
const qData = await qOpts.queryFn();
assert.equal(qData[0].id, "1");

const qCtrl = new AbortController();
setTimeout(() => qCtrl.abort(), 20);
const qSlow = client.queryOptions("GET /api/todos", { headers: { "X-Mode": "slow" } });
await assert.rejects(
  () => qSlow.queryFn({ signal: qCtrl.signal }),
  (err) => isAbortError(err) && parseNinjaError(err).kind === "abort",
);

// 2. parseNinjaError normalizes 422 validation errors + X-Request-Id
await assert.rejects(
  () => client.fetch("POST /api/todos", { body: { title: "ab" }, headers: { "X-Mode": "422" } }),
  (err) => {
    const parsed = parseNinjaError(err);
    return (
      parsed.kind === "validation" &&
      parsed.status === 422 &&
      parsed.requestId === "req-422" &&
      parsed.endpoint === "POST /api/todos" &&
      parsed.fieldErrors["body.title"]?.[0] === "Too short"
    );
  },
);

// 3. parseNinjaError handles 500 HTTP error and cross-realm brand
await assert.rejects(
  () => client.fetch("GET /api/todos", { headers: { "X-Mode": "500" } }),
  (err) => {
    const parsed = parseNinjaError(err);
    return parsed.kind === "http" && parsed.status === 500 && parsed.message === "boom";
  },
);
const branded = { [Symbol.for("ninja_ts.apiError")]: true };
assert.equal(isNinjaApiError(branded), true);

// 4. parseNinjaError distinguishes network errors and timeouts
await assert.rejects(
  () => client.fetch("GET /api/todos", { headers: { "X-Mode": "network" } }),
  (err) => parseNinjaError(err).kind === "network",
);
await assert.rejects(
  () => client.fetch("GET /api/todos", { timeoutMs: 25, headers: { "X-Mode": "slow" } }),
  (err) => !isAbortError(err) && parseNinjaError(err).kind === "timeout",
);

// 5. Caller abort skips onError hooks AND cancels retry backoff early + releases body
onErrorCount = 0;
const retryCtrl = new AbortController();
setTimeout(() => retryCtrl.abort(), 40);
const started = Date.now();
await assert.rejects(
  () =>
    client.fetch("GET /api/todos", {
      headers: { "X-Mode": "retry-503" },
      retry: { attempts: 3, methods: ["GET"] },
      signal: retryCtrl.signal,
    }),
  (err) => isAbortError(err) && parseNinjaError(err).kind === "abort",
);
assert.equal(cancelledRetryBody, true);
assert.equal(onErrorCount, 0);
assert.ok(Date.now() - started < 1000, "retry sleep should abort promptly");
"""
    (tmp_path / "runner.mts").write_text(runner)
    result = subprocess.run(
        [node_path, "--experimental-strip-types", "runner.mts"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --------------------------------------------------------------------------- modular SDK


def test_modular_sdk_schema_placement_and_transitive_shared():
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "Modular API", "version": "1.0.0"},
        "paths": {
            "/api/v1/todos": {
                "get": {
                    "tags": ["todos"],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TodoItem"}
                                }
                            }
                        }
                    },
                }
            },
            "/api/v1/users/me": {
                "get": {
                    "tags": ["Usuários & Perfis"],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/UserProfile"
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/api/v2/orders/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "string"}}
                            }
                        }
                    }
                }
            },
            "/": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "string"}}
                            }
                        }
                    }
                }
            },
        },
        "components": {
            "schemas": {
                "TodoItem": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "meta": {"$ref": "#/components/schemas/AuditMeta"},
                    },
                    "required": ["id", "meta"],
                },
                "UserProfile": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "meta": {"$ref": "#/components/schemas/AuditMeta"},
                    },
                    "required": ["name", "meta"],
                },
                "AuditMeta": {
                    "type": "object",
                    "properties": {
                        "tag": {"$ref": "#/components/schemas/SharedTag"},
                    },
                    "required": ["tag"],
                },
                "SharedTag": {"type": "string"},
                "OrphanSchema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            }
        },
    }

    files = TypeScriptGenerator(doc).generate_sdk(import_ext=".js")
    assert set(files) == {
        "index.ts",
        "runtime.ts",
        "types/_shared.ts",
        "types/todos.ts",
        "types/usuarios-perfis.ts",
        "endpoints/default.ts",
        "endpoints/orders.ts",
        "endpoints/todos.ts",
        "endpoints/usuarios-perfis.ts",
    }

    assert "export interface AuditMeta" in files["types/_shared.ts"]
    assert "export type SharedTag = string;" in files["types/_shared.ts"]
    assert "OrphanSchema" not in files["types/_shared.ts"]
    assert "OrphanSchema" not in files["index.ts"]

    assert 'import type { AuditMeta } from "./_shared.js";' in files["types/todos.ts"]
    assert "export interface TodoItem" in files["types/todos.ts"]
    assert "SharedTag" not in files["types/todos.ts"]

    assert (
        'import type { TodoItem } from "../types/todos.js";'
        in files["endpoints/todos.ts"]
    )
    assert "export interface TodosEndpoints" in files["endpoints/todos.ts"]
    assert (
        "export interface UsuariosPerfisEndpoints"
        in files["endpoints/usuarios-perfis.ts"]
    )
    assert "export interface OrdersEndpoints" in files["endpoints/orders.ts"]
    assert "export interface DefaultEndpoints" in files["endpoints/default.ts"]

    assert (
        "export interface NinjaEndpoints extends DefaultEndpoints, OrdersEndpoints, TodosEndpoints, UsuariosPerfisEndpoints {}"
        in files["index.ts"]
    )
    assert 'export type * from "./types/_shared.js";' in files["index.ts"]


def test_detect_ts_import_extension(tmp_path: Path):
    deno_dir = tmp_path / "deno_app" / "src" / "sdk"
    deno_dir.mkdir(parents=True)
    (tmp_path / "deno_app" / "deno.jsonc").write_text("{}")
    assert detect_ts_import_extension(deno_dir) == ".ts"

    tsconfig_nodenext = tmp_path / "nodenext_app" / "sdk"
    tsconfig_nodenext.mkdir(parents=True)
    (tmp_path / "nodenext_app" / "tsconfig.json").write_text(
        """{
  // JSONC comment with "NodeNext" inside a string
  "compilerOptions": {
    /* block comment */
    "moduleResolution": "NodeNext",
  },
}"""
    )
    assert detect_ts_import_extension(tsconfig_nodenext) == ".js"

    tsconfig_ts = tmp_path / "strip_app" / "sdk"
    tsconfig_ts.mkdir(parents=True)
    (tmp_path / "strip_app" / "tsconfig.json").write_text(
        '{"compilerOptions": {"noEmit": true, "allowImportingTsExtensions": true}}'
    )
    assert detect_ts_import_extension(tsconfig_ts) == ".ts"

    tsconfig_bundler = tmp_path / "next_app" / "sdk"
    tsconfig_bundler.mkdir(parents=True)
    (tmp_path / "next_app" / "tsconfig.json").write_text(
        '{"compilerOptions": {"moduleResolution": "bundler"}}'
    )
    (tmp_path / "next_app" / "package.json").write_text('{"type": "module"}')
    assert detect_ts_import_extension(tsconfig_bundler) == ""

    esm_pkg = tmp_path / "esm_pkg" / "sdk"
    esm_pkg.mkdir(parents=True)
    (tmp_path / "esm_pkg" / "package.json").write_text('{"type": "module"}')
    assert detect_ts_import_extension(esm_pkg) == ".js"

    cjs_pkg = tmp_path / "cjs_pkg" / "sdk"
    cjs_pkg.mkdir(parents=True)
    (tmp_path / "cjs_pkg" / "package.json").write_text('{"name": "app"}')
    assert detect_ts_import_extension(cjs_pkg) == ""


def test_sync_and_check_sdk_lifecycle(tmp_path: Path):
    sdk_dir = tmp_path / "sdk"
    stale_generated = sdk_dir / "endpoints" / "old.ts"
    stale_generated.parent.mkdir(parents=True)
    stale_generated.write_text(f"// {GENERATED_MARKER}\nexport interface Old {{}}\n")

    user_custom = sdk_dir / "helpers.ts"
    user_custom.write_text("export const custom = 1;\n")

    res1 = ninja_ts.sync_sdk(api, sdk_dir, import_ext="")
    assert "index.ts" in res1.written
    assert "runtime.ts" in res1.written
    assert res1.removed == ("endpoints/old.ts",)
    assert not stale_generated.exists()
    assert user_custom.exists()

    res2 = ninja_ts.sync_sdk(api, sdk_dir, import_ext="")
    assert res2.written == ()
    assert set(res2.unchanged) >= {"index.ts", "runtime.ts"}
    assert res2.removed == ()

    checked = ninja_ts.check_sdk(api, sdk_dir, import_ext="")
    assert set(checked.unchanged) == set(res2.unchanged)

    (sdk_dir / "runtime.ts").write_text("// tampered")
    with pytest.raises(ninja_ts.SdkDriftError) as exc_info:
        ninja_ts.check_sdk(api, sdk_dir, import_ext="")
    assert "runtime.ts" in exc_info.value.changed

    (sdk_dir / "runtime.ts").unlink()
    with pytest.raises(ninja_ts.SdkDriftError) as exc_info:
        ninja_ts.check_sdk(api, sdk_dir, import_ext="")
    assert "runtime.ts" in exc_info.value.missing

    ninja_ts.sync_sdk(api, sdk_dir, import_ext="")
    (sdk_dir / "types" / "stale.ts").write_text(f"// {GENERATED_MARKER}\n")
    with pytest.raises(ninja_ts.SdkDriftError) as exc_info:
        ninja_ts.check_sdk(api, sdk_dir, import_ext="")
    assert "types/stale.ts" in exc_info.value.stale

    # Refusing to overwrite an unmanaged file colliding with generated path
    unmanaged_dir = tmp_path / "unmanaged"
    unmanaged_dir.mkdir()
    (unmanaged_dir / "index.ts").write_text("export const handWritten = true;\n")
    with pytest.raises(ValueError, match="unmanaged"):
        ninja_ts.sync_sdk(api, unmanaged_dir, import_ext="")


def test_query_and_path_params_strip_null_while_body_preserves_null():
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "NullableParams"},
        "paths": {
            "/items/{item_id}": {
                "post": {
                    "parameters": [
                        {
                            "name": "item_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": ["string", "null"]},
                        },
                        {
                            "name": "q",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "nullable": True},
                        },
                        {
                            "name": "color",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [
                                    {"$ref": "#/components/schemas/Color"},
                                    {"type": "null"},
                                ]
                            },
                        },
                        {
                            "name": "tags",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [
                                    {
                                        "type": "array",
                                        "items": {
                                            "anyOf": [
                                                {"type": "string"},
                                                {"type": "null"},
                                            ]
                                        },
                                    },
                                    {"type": "null"},
                                ]
                            },
                        },
                        {
                            "name": "only_null",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "null"},
                        },
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PatchItem"}
                            }
                        },
                    },
                    "responses": {"204": {"description": "No Content"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Color": {"enum": ["red", "blue"]},
                "PatchItem": {
                    "type": "object",
                    "properties": {
                        "notes": {"anyOf": [{"type": "string"}, {"type": "null"}]}
                    },
                },
            }
        },
    }
    ts = "\n".join(TypeScriptGenerator(openapi).generate_sdk().values())
    block = endpoint_block(ts, "POST /items/{item_id}")
    assert "params: { item_id: string };" in block
    assert (
        "query: { color?: Color; only_null?: null; q?: string; tags?: string[] };"
        in block
    )
    assert "  notes?: string | null;" in ts


@pytest.mark.skipif(not node_path, reason="Node.js not on PATH")
def test_client_on_unauthorized_refresh(tmp_path: Path):
    assert node_path is not None
    ninja_ts.export_sdk(api, tmp_path / "sdk", import_ext=".ts")
    runner = """
import assert from "node:assert/strict";
import { createNinjaClient, isNinjaApiError } from "./sdk/index.ts";

let token = "expired";
let refreshCalls = 0;
let onRequestCalls = 0;
let onErrorCalls = 0;
let seenBodies = [];

const client = createNinjaClient("https://example.test", {
  headers: () => ({ Authorization: `Bearer ${token}` }),
  onRequest() {
    onRequestCalls++;
  },
  onError() {
    onErrorCalls++;
  },
  async onUnauthorized(ctx) {
    refreshCalls++;
    if (ctx.endpoint === "GET /api/todos/always401" || token === "reject-refresh") {
      return false;
    }
    if (token === "throw-refresh") {
      throw new Error("Refresh failed");
    }
    token = "fresh";
    return true;
  },
  async fetch(_url, init) {
    const auth = init.headers.get("Authorization");
    if (init.body) {
      seenBodies.push(String(init.body));
    }
    const mode = init.headers.get("X-Case");
    if (mode === "still401" || auth === "Bearer expired") {
      return new Response(JSON.stringify({ detail: "Token expired" }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(
      JSON.stringify({ id: "todo_1", title: "Ship", priority: "high", done: false }),
      { status: 201, headers: { "content-type": "application/json" } },
    );
  },
});

// 1. 401 -> refresh -> rebuilt headers + preserved POST body -> 201
const created = await client.fetch("POST /api/todos", {
  body: { title: "Ship", priority: "high" },
});
assert.equal(created.id, "todo_1");
assert.equal(refreshCalls, 1);
assert.equal(onRequestCalls, 2);
assert.equal(seenBodies.length, 2);
assert.equal(seenBodies[0], seenBodies[1]);

// 2. Refresh returns true, but server still returns 401 -> does not loop
token = "fresh";
await assert.rejects(
  () => client.fetch("GET /api/todos", { headers: { "X-Case": "still401" } }),
  (err) => isNinjaApiError(err) && err.status === 401 && err.data.detail === "Token expired",
);
assert.equal(refreshCalls, 2);

// 3. Refresh returns false -> original 401 body is preserved
token = "reject-refresh";
await assert.rejects(
  () => client.fetch("GET /api/todos", { headers: { "X-Case": "still401" } }),
  (err) => isNinjaApiError(err) && err.status === 401 && err.data.detail === "Token expired",
);
assert.equal(refreshCalls, 3);

// 4. Refresh throws -> triggers onError and rejects with refresh error
token = "throw-refresh";
const beforeErrors = onErrorCalls;
await assert.rejects(
  () => client.fetch("GET /api/todos", { headers: { "X-Case": "still401" } }),
  (err) => err instanceof Error && err.message === "Refresh failed",
);
assert.equal(onErrorCalls, beforeErrors + 1);
"""
    (tmp_path / "runner.mts").write_text(runner)
    result = subprocess.run(
        [node_path, "--experimental-strip-types", "runner.mts"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_management_command_check_and_guards(tmp_path: Path):
    sdk_dir = tmp_path / "sdk"
    call_command("generate_ts_sdk", out=str(sdk_dir), import_ext="none")
    assert (sdk_dir / "index.ts").is_file()
    assert (sdk_dir / "runtime.ts").is_file()

    call_command("generate_ts_sdk", out=str(sdk_dir), check=True, import_ext="none")

    (sdk_dir / "index.ts").write_text("// stale")
    with pytest.raises(CommandError, match="out of date"):
        call_command("generate_ts_sdk", out=str(sdk_dir), check=True, import_ext="none")

    # Missing -o or passing a .ts file path for modular SDK fails clearly
    with pytest.raises(CommandError, match="is required"):
        call_command("generate_ts_sdk")
    with pytest.raises(CommandError, match="expects a directory"):
        call_command("generate_ts_sdk", out=str(tmp_path / "api.ts"))
    with pytest.raises(CommandError, match="requires -o/--out"):
        call_command("generate_ts_sdk", check=True)


def test_media_types_reserved_names_and_emit_declaration_only(tmp_path: Path):
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "MediaAndReserved"},
        "paths": {
            "/upper-json": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "Application/JSON; charset=utf-8": {
                                "schema": {"$ref": "#/components/schemas/Map"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "Application/JSON; charset=utf-8": {
                                    "schema": {
                                        "$ref": "#/components/schemas/RequestInit"
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/xml": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "Application/XML; charset=utf-8": {
                                    "schema": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            },
            "/binary-upload": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/octet-stream": {
                                "schema": {"type": "string", "format": "binary"}
                            }
                        },
                    },
                    "responses": {"204": {"description": "No Content"}},
                }
            },
        },
        "components": {
            "schemas": {
                "Map": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
                "RequestInit": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            }
        },
    }
    files = TypeScriptGenerator(openapi).generate_sdk()
    ts = "\n".join(files.values())
    assert "export interface Map_2 {" in ts
    assert "export interface RequestInit_2 {" in ts
    upper_block = endpoint_block(ts, "POST /upper-json")
    assert "body: Map_2;" in upper_block
    assert "response: RequestInit_2;" in upper_block
    xml_block = endpoint_block(ts, "GET /xml")
    assert "response: string;" in xml_block
    raw_block = endpoint_block(ts, "POST /binary-upload")
    assert (
        "body: Blob | ArrayBuffer | ArrayBufferView | ReadableStream | string;"
        in raw_block
    )
    assert '  "POST /binary-upload": "raw",\n' in files["index.ts"]

    emit_decl = tmp_path / "decl_only" / "sdk"
    emit_decl.mkdir(parents=True)
    (tmp_path / "decl_only" / "tsconfig.json").write_text(
        '{"compilerOptions": {"emitDeclarationOnly": true, "allowImportingTsExtensions": true}}'
    )
    assert detect_ts_import_extension(emit_decl) == ".ts"


@pytest.mark.skipif(not node_path, reason="Node.js not on PATH")
def test_runtime_retry_variants_content_type_and_parse_error_hooks(tmp_path: Path):
    assert node_path is not None
    openapi = {
        "openapi": "3.1.0",
        "info": {"title": "ParityAPI"},
        "paths": {
            "/form": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/x-www-form-urlencoded": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"username": {"type": "string"}},
                                    "required": ["username"],
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"ok": {"type": "boolean"}},
                                        "required": ["ok"],
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/files/{path:filepath}": {
                "get": {
                    "parameters": [
                        {
                            "name": "filepath",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "Application/JSON; charset=utf-8": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"path": {"type": "string"}},
                                        "required": ["path"],
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/items": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "string"}}
                            }
                        }
                    }
                }
            },
        },
    }
    ninja_ts.export_sdk(openapi, tmp_path / "sdk", import_ext=".ts")
    runner = """
import assert from "node:assert/strict";
import { createNinjaClient } from "./sdk/index.ts";

let retryBoolCalls = 0;
let retryObjCalls = 0;
let retryPastIsoCalls = 0;
let retryFalseCalls = 0;
let onErrorCalls = 0;

const client = createNinjaClient("https://example.test", {
  headers: { "Content-Type": "application/json" },
  retry: 2,
  onError() {
    onErrorCalls++;
  },
  async fetch(url, init) {
    const mode = init.headers.get("X-Mode");
    if (url.endsWith("/form")) {
      assert.equal(init.headers.get("Content-Type"), null);
      assert.ok(init.body instanceof URLSearchParams);
      assert.equal(init.body.get("username"), "alice");
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "Application/JSON; charset=utf-8" },
      });
    }
    if (url.includes("/files/")) {
      return new Response(JSON.stringify({ path: url }), {
        status: 200,
        headers: { "content-type": "Application/JSON; charset=utf-8" },
      });
    }
    if (mode === "bad-json") {
      return new Response("{broken", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (mode === "retry-bool") {
      retryBoolCalls++;
      if (retryBoolCalls < 3) {
        return new Response("busy", { status: 503 });
      }
      return new Response(JSON.stringify("ok-bool"), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (mode === "retry-obj") {
      retryObjCalls++;
      if (retryObjCalls < 3) {
        return new Response("busy", { status: 503 });
      }
      return new Response(JSON.stringify("ok-obj"), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (mode === "retry-past-iso") {
      retryPastIsoCalls++;
      if (retryPastIsoCalls === 1) {
        return new Response("busy", {
          status: 503,
          headers: { "Retry-After": "2020-01-01T00:00:00Z" },
        });
      }
      return new Response(JSON.stringify("ok-iso"), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (mode === "retry-false") {
      retryFalseCalls++;
      return new Response(JSON.stringify({ detail: "fail" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    }
    throw new Error("unexpected request: " + url);
  },
});

// 1. Default JSON Content-Type does not break form-urlencoded, and uppercase JSON Content-Type parses
const formRes = await client.fetch("POST /form", { body: { username: "alice" } });
assert.equal(formRes.ok, true);

// 2. {path:filepath} catch-all path param resolves cleanly
const fileRes = await client.fetch("GET /files/{path:filepath}", {
  params: { filepath: ["docs", "api guide.md"] },
});
assert.equal(fileRes.path, "https://example.test/files/docs/api%20guide.md");

// 3. Parse error in readBody triggers onError hook
const prevErrors = onErrorCalls;
await assert.rejects(
  () => client.fetch("GET /items", { headers: { "X-Mode": "bad-json" }, retry: false }),
  (err) => err instanceof SyntaxError,
);
assert.equal(onErrorCalls, prevErrors + 1);

// 4. retry: false disables client-level retry
await assert.rejects(
  () => client.fetch("GET /items", { headers: { "X-Mode": "retry-false" }, retry: false }),
);
assert.equal(retryFalseCalls, 1);

// 5. retry: true and retry: { delayMs } default to 2 retry attempts (3 total calls)
const boolClient = createNinjaClient("https://example.test", {
  fetch: async (url, init) => {
    retryBoolCalls++;
    if (retryBoolCalls < 3) return new Response("busy", { status: 503 });
    return new Response(JSON.stringify("ok-bool"), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  },
});
retryBoolCalls = 0;
assert.equal(await boolClient.fetch("GET /items", { retry: true }), "ok-bool");
assert.equal(retryBoolCalls, 3);

assert.equal(await client.fetch("GET /items", { headers: { "X-Mode": "retry-obj" }, retry: { delayMs: 1 } }), "ok-obj");
assert.equal(retryObjCalls, 3);

// 6. Retry-After ISO date in the past is not parsed as 2020 seconds
const started = Date.now();
assert.equal(
  await client.fetch("GET /items", { headers: { "X-Mode": "retry-past-iso" }, retry: { attempts: 1, delayMs: 1 } }),
  "ok-iso",
);
assert.ok(Date.now() - started < 1000);
"""
    (tmp_path / "runner.mts").write_text(runner)
    result = subprocess.run(
        [node_path, "--experimental-strip-types", "runner.mts"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
