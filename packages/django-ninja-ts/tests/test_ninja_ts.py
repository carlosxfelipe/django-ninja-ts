import re
import shutil
import subprocess
from pathlib import Path

import ninja_ts
import pytest
from django.core.management import call_command
from django.test import Client
from ninja_ts import TypeScriptGenerator

from tests.sample_api import api


@pytest.fixture(scope="module")
def types() -> str:
    return ninja_ts.generate_types(api)


@pytest.fixture(scope="module")
def sdk() -> str:
    return ninja_ts.generate_sdk(api)


def endpoint_block(ts: str, key: str) -> str:
    match = re.search(rf'  "{re.escape(key)}": \{{\n(.*?)\n  \}};', ts, re.DOTALL)
    assert match, f"endpoint {key!r} not found"
    return match.group(1)


# --------------------------------------------------------------------------- schemas


def test_request_schema_follows_pydantic_optionality(types):
    assert "export interface TodoIn {" in types
    assert "  title: string;\n" in types
    assert '  priority?: "low" | "normal" | "high";\n' in types
    assert "  notes?: string | null;\n" in types


def test_response_only_schema_marks_all_fields_present(types):
    todo_out = types[types.index("export interface TodoOut {") :]
    todo_out = todo_out[: todo_out.index("}\n")]
    assert "  done: boolean;" in todo_out
    assert "  notes: string | null;" in todo_out


def test_jsdoc_from_field_metadata(types):
    assert '   * Task title\n   * @example "Review pull requests"\n' in types
    assert '   * @default "normal"\n' in types


def test_response_exclusions_disable_all_fields_present():
    from ninja import NinjaAPI

    from tests.sample_api import TodoOut

    local = NinjaAPI(urls_namespace="exclusions")

    @local.get("/todo", response=TodoOut, exclude_none=True)
    def todo(request):
        return {}

    ts = ninja_ts.generate_types(local, path_prefix="")
    assert "  notes?: string | null;" in ts
    assert "  done?: boolean;" in ts


# --------------------------------------------------------------------------- endpoints


def test_endpoint_without_inputs(types):
    block = endpoint_block(types, "GET /api/health")
    assert "response: unknown;" in block
    assert "request: { params?: never; query?: never; body?: never };" in block


def test_path_params_and_response(types):
    block = endpoint_block(types, "GET /api/todos/{id}")
    assert "params: { id: string };" in block
    assert "response: TodoOut;" in block


def test_path_param_types_come_from_annotations(types):
    block = endpoint_block(types, "DELETE /api/todos/{id}")
    assert "params: { id: number };" in block
    assert "response: void;" in block  # 204


def test_deprecated_and_summary_jsdoc(types):
    assert "   * Delete todo\n   * @deprecated\n" in types


def test_query_schema_is_flattened_and_optional(types):
    block = endpoint_block(types, "GET /api/todos")
    assert "query: { limit?: number; q?: string | null };" in block
    assert "query?: { limit?: number; q?: string | null }" in block
    assert "response: TodoOut[];" in block


def test_required_query_makes_query_required(types):
    block = endpoint_block(types, "GET /api/todos/search/required")
    assert (
        "request: { params?: never; query: { term: string }; body?: never };" in block
    )


def test_json_body_and_created_status(types):
    block = endpoint_block(types, "POST /api/todos")
    assert "body: TodoIn;" in block
    assert "response: TodoOut;" in block  # 201 is the lowest 2xx


def test_multipart_body_accepts_object_or_formdata(types, sdk):
    block = endpoint_block(types, "POST /api/todos/{id}/attachments")
    assert "body: { file: Blob; caption: string } | FormData;" in block
    assert '  "POST /api/todos/{id}/attachments": "multipart",\n' in sdk


def test_install_routes_are_hidden_from_schema(types):
    assert "sdk.ts" not in types
    assert "types.d.ts" not in types


# --------------------------------------------------------------------------- output modes


def test_types_only_declares_runtime(types):
    assert "export declare function createNinjaClient(" in types
    assert "export declare class NinjaApiError" in types
    assert "BODY_ENCODINGS" not in types


def test_sdk_contains_runtime(sdk):
    assert "export function createNinjaClient(" in sdk
    assert "export class NinjaApiError" in sdk
    assert "declare " not in sdk


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
    ts = TypeScriptGenerator(openapi).generate_types()
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
    assert "export interface NinjaEndpoints {\n}" in ninja_ts.generate_sdk(openapi)


# --------------------------------------------------------------------------- Django integration


def test_install_serves_sdk_and_types():
    client = Client()
    sdk_response = client.get("/api/sdk.ts")
    assert sdk_response.status_code == 200
    assert sdk_response["Content-Type"].startswith("application/typescript")
    assert sdk_response["Cache-Control"].startswith("no-store")
    assert b"export function createNinjaClient(" in sdk_response.content

    types_response = client.get("/api/types.d.ts")
    assert types_response.status_code == 200
    assert b"export declare function createNinjaClient(" in types_response.content


def test_management_command_writes_files(tmp_path: Path):
    sdk_path = tmp_path / "nested" / "api.ts"
    call_command("generate_ts_sdk", out=str(sdk_path))
    assert sdk_path.read_text() == ninja_ts.generate_sdk(api)

    types_path = tmp_path / "api.d.ts"
    call_command("generate_ts_sdk", out=str(types_path), types_only=True)
    assert types_path.read_text() == ninja_ts.generate_types(api)


# --------------------------------------------------------------------------- TypeScript compiler


CONSUMER = """
import { createNinjaClient, NinjaApiError, type ResponseData } from "./api";

const api = createNinjaClient("http://localhost:8000", { headers: async () => ({ Authorization: "Bearer x" }) });

async function main(): Promise<void> {
  const list: ResponseData<"GET /api/todos"> = await api.fetch("GET /api/todos");
  const filtered = await api.fetch("GET /api/todos", { query: { limit: 5 } });
  const one = await api.fetch("GET /api/todos/{id}", { params: { id: "todo_1" } });
  const done: boolean = one.done;
  const created = await api.fetch("POST /api/todos", { body: { title: "Ship", priority: "high" } });
  const removed: void = await api.fetch("DELETE /api/todos/{id}", { params: { id: 1 } });
  await api.fetch("POST /api/todos/{id}/attachments", {
    params: { id: "todo_1" },
    body: { file: new Blob(["x"]), caption: "c" },
  });

  // @ts-expect-error path params are required
  await api.fetch("GET /api/todos/{id}");
  // @ts-expect-error priority must be a known literal
  await api.fetch("POST /api/todos", { body: { title: "Ship", priority: "urgent" } });
  // @ts-expect-error unknown endpoint
  await api.fetch("GET /api/nope");
  // @ts-expect-error required query
  await api.fetch("GET /api/todos/search/required");
  // @ts-expect-error endpoint takes no body
  await api.fetch("GET /api/health", { body: { x: 1 } });

  try {
    await api.fetch("GET /api/health");
  } catch (err) {
    if (err instanceof NinjaApiError) console.log(err.status, err.data);
  }
  console.log(list, filtered, done, created, removed);
}

void main();
"""


TSC_CMD = (
    [shutil.which("tsc")]
    if shutil.which("tsc")
    else (
        [shutil.which("npx"), "--yes", "-p", "typescript", "tsc"]
        if shutil.which("npx")
        else None
    )
)


@pytest.mark.skipif(not TSC_CMD, reason="TypeScript compiler (tsc/npx) not on PATH")
def test_generated_code_type_checks_with_tsc(tmp_path: Path, sdk: str, types: str):
    (tmp_path / "api.ts").write_text(sdk)
    (tmp_path / "consumer.ts").write_text(CONSUMER)
    flags = [
        "--noEmit",
        "--strict",
        "--exactOptionalPropertyTypes",
        "--noUncheckedIndexedAccess",
        "--noPropertyAccessFromIndexSignature",
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

    (tmp_path / "types.d.ts").write_text(types)
    result = subprocess.run(
        [*TSC_CMD, *flags, "types.d.ts"],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
