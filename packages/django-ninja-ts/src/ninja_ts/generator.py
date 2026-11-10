"""OpenAPI 3.x -> TypeScript generator.

This module is framework-agnostic: it only consumes an OpenAPI document (a plain dict),
so it has no Django imports and can be unit-tested (or reused) in isolation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from ninja_ts import runtime

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

_SCHEMA_REF_PREFIX = "#/components/schemas/"
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_INVALID_IDENT_CHARS = re.compile(r"[^A-Za-z0-9_$]+")
_PATH_PARAM = re.compile(r"\{([^}]+)\}")

# Names that generated schema types must never shadow (TS built-ins + our runtime exports).
_RESERVED_TYPE_NAMES = frozenset(
    {
        "any",
        "unknown",
        "never",
        "void",
        "null",
        "undefined",
        "object",
        "string",
        "number",
        "boolean",
        "symbol",
        "bigint",
        "Array",
        "Record",
        "Partial",
        "Promise",
        "Date",
        "Blob",
        "File",
        "FormData",
        "Headers",
        "Response",
        "Request",
        "URLSearchParams",
        "ReadableStream",
        "Error",
        *runtime.EXPORTED_NAMES,
    }
)

# Request body media types, in order of preference, mapped to the runtime body encoding.
_BODY_MEDIA_TYPES = (
    ("application/json", "json"),
    ("multipart/form-data", "multipart"),
    ("application/x-www-form-urlencoded", "form"),
)


@dataclass
class _Route:
    key: str
    method: str
    path: str
    summary: str
    description: str
    deprecated: bool
    params_ts: str
    query_ts: str
    body_ts: str
    response_ts: str
    error_ts: str
    request_ts: str
    body_encoding: str


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _prop_name(name: str) -> str:
    return name if _IDENTIFIER.match(name) else _literal(name)


def _wrap(ts: str) -> str:
    """Parenthesize union/intersection types so they compose safely (e.g. in arrays)."""
    return f"({ts})" if (" | " in ts or " & " in ts) else ts


def _union(parts: list[str]) -> str:
    unique = list(dict.fromkeys(parts))
    if not unique:
        return "never"
    if "unknown" in unique:
        return "unknown"
    return " | ".join(_wrap(p) if " & " in p else p for p in unique)


def _doc_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [line.rstrip().replace("*/", "*\\/") for line in text.strip().splitlines()]


def _jsdoc(lines: list[str], indent: str) -> str:
    lines = [line for line in lines if line is not None]
    if not lines:
        return ""
    body = "".join(f"{indent} * {line}".rstrip() + "\n" for line in lines)
    return f"{indent}/**\n{body}{indent} */\n"


class TypeScriptGenerator:
    """Turns an OpenAPI document into TypeScript declarations and a zero-dependency SDK.

    ``responses_include_all_fields``: Pydantic serializes every field of a response model, so
    for schemas used *only* in responses all properties are typed as present (``field: T``).
    Disable it when routes use ``exclude_none`` / ``exclude_unset`` / ``exclude_defaults``
    (the Django Ninja integration detects this automatically).
    """

    def __init__(
        self, openapi: dict[str, Any], *, responses_include_all_fields: bool = True
    ) -> None:
        self.openapi = openapi
        self.responses_include_all_fields = responses_include_all_fields
        self.schemas: dict[str, Any] = (openapi.get("components") or {}).get(
            "schemas"
        ) or {}
        self._names = self._assign_names()
        self._response_only = self._response_only_schemas()

    # ------------------------------------------------------------------ public API

    def generate_types(self) -> str:
        """TypeScript declarations (``.d.ts``) for schemas, endpoints and the client."""
        return self._render(declarations_only=True)

    def generate_sdk(self) -> str:
        """Standalone TypeScript SDK (``.ts``) including the ``createNinjaClient`` runtime."""
        return self._render(declarations_only=False)

    # ------------------------------------------------------------------ naming

    def _assign_names(self) -> dict[str, str]:
        used = set(_RESERVED_TYPE_NAMES)
        names: dict[str, str] = {}
        for raw in sorted(self.schemas):
            base = _INVALID_IDENT_CHARS.sub("_", raw).strip("_") or "Model"
            if base[0].isdigit():
                base = f"_{base}"
            name, i = base, 2
            while name in used:
                name, i = f"{base}_{i}", i + 1
            used.add(name)
            names[raw] = name
        return names

    def _ref_name(self, ref: str) -> str:
        if ref.startswith(_SCHEMA_REF_PREFIX):
            raw = ref[len(_SCHEMA_REF_PREFIX) :]
            if raw in self._names:
                return self._names[raw]
        return "unknown"

    # ------------------------------------------------------------------ $ref helpers

    def _deref(self, node: Any) -> Any:
        """Follow non-schema ``$ref``s (parameters, requestBodies, responses)."""
        seen: set[str] = set()
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            if (
                ref.startswith(_SCHEMA_REF_PREFIX)
                or not ref.startswith("#/")
                or ref in seen
            ):
                break
            seen.add(ref)
            target: Any = self.openapi
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                target = target.get(part) if isinstance(target, dict) else None
            if target is None:
                break
            node = target
        return node

    def _collect_refs(self, node: Any, out: set[str]) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                if ref.startswith(_SCHEMA_REF_PREFIX):
                    out.add(ref[len(_SCHEMA_REF_PREFIX) :])
                else:
                    deref = self._deref(node)
                    if deref is not node:
                        self._collect_refs(deref, out)
            for value in node.values():
                self._collect_refs(value, out)
        elif isinstance(node, list):
            for value in node:
                self._collect_refs(value, out)

    def _closure(self, roots: set[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(roots)
        while stack:
            name = stack.pop()
            if name in seen or name not in self.schemas:
                continue
            seen.add(name)
            refs: set[str] = set()
            self._collect_refs(self.schemas[name], refs)
            stack.extend(refs - seen)
        return seen

    def _response_only_schemas(self) -> set[str]:
        """Schemas reachable only from responses (see ``responses_include_all_fields``).

        Pydantic's JSON schema follows validation semantics (defaulted fields are not
        ``required``), but its serializer always emits every field. For schemas never used as
        input we can therefore type every property as present.
        """
        request_roots: set[str] = set()
        response_roots: set[str] = set()
        for _path, _method, op, item in self._operations():
            self._collect_refs(item.get("parameters"), request_roots)
            self._collect_refs(op.get("parameters"), request_roots)
            self._collect_refs(op.get("requestBody"), request_roots)
            self._collect_refs(op.get("responses"), response_roots)
        return self._closure(response_roots) - self._closure(request_roots)

    def _operations(self):
        for path, item in (self.openapi.get("paths") or {}).items():
            item = self._deref(item) or {}
            for method in HTTP_METHODS:
                op = item.get(method)
                if isinstance(op, dict):
                    yield path, method, op, item

    # ------------------------------------------------------------------ schema -> TS

    def _ts(self, schema: Any, response: bool = False) -> str:
        if schema is True or schema is None or schema == {}:
            return "unknown"
        if schema is False:
            return "never"
        if not isinstance(schema, dict):
            return "unknown"
        if "$ref" in schema:
            return self._ref_name(schema["$ref"])
        if "const" in schema:
            return _literal(schema["const"])
        if "enum" in schema:
            ts = _union([_literal(v) for v in schema["enum"]])
            return _union([ts, "null"]) if schema.get("nullable") is True else ts
        for key in ("oneOf", "anyOf"):
            if key in schema:
                return _union([self._ts(s, response) for s in schema[key]])
        if "allOf" in schema:
            parts = [self._ts(s, response) for s in schema["allOf"]]
            rest = {k: v for k, v in schema.items() if k != "allOf"}
            if "properties" in rest:
                parts.append(self._object(rest, response))
            parts = list(dict.fromkeys(parts))
            return parts[0] if len(parts) == 1 else " & ".join(_wrap(p) for p in parts)

        type_ = schema.get("type")
        if isinstance(type_, list):
            return _union([self._ts({**schema, "type": t}, response) for t in type_])
        ts = self._ts_for_type(schema, type_, response)
        return _union([ts, "null"]) if schema.get("nullable") is True else ts

    def _ts_for_type(self, schema: dict[str, Any], type_: Any, response: bool) -> str:
        if type_ == "string":
            return "Blob" if schema.get("format") == "binary" else "string"
        if type_ in ("integer", "number"):
            return "number"
        if type_ == "boolean":
            return "boolean"
        if type_ == "null":
            return "null"
        if type_ == "array":
            if isinstance(schema.get("prefixItems"), list):
                items = ", ".join(self._ts(s, response) for s in schema["prefixItems"])
                return f"[{items}]"
            return f"{_wrap(self._ts(schema.get('items'), response))}[]"
        if (
            type_ == "object"
            or "properties" in schema
            or "additionalProperties" in schema
        ):
            return self._object(schema, response)
        return "unknown"

    def _fields(
        self, schema: dict[str, Any], response: bool
    ) -> list[tuple[str, str, bool, list[str]]]:
        """(name, ts_type, required, doc_lines) for each declared property."""
        required = set(schema.get("required") or [])
        all_present = response and self.responses_include_all_fields
        fields = []
        for name, prop in (schema.get("properties") or {}).items():
            prop = prop if isinstance(prop, dict) else {}
            is_required = all_present or name in required
            fields.append(
                (name, self._ts(prop, response), is_required, self._prop_doc(prop))
            )
        return fields

    def _object(self, schema: dict[str, Any], response: bool) -> str:
        fields = self._fields(schema, response)
        extra = schema.get("additionalProperties")
        if not fields:
            if isinstance(extra, dict) and extra:
                return f"Record<string, {self._ts(extra, response)}>"
            if "properties" in schema and extra is not True:
                return "Record<string, never>"  # explicitly empty object
            return "Record<string, unknown>"
        parts = [
            f"{_prop_name(n)}{'' if req else '?'}: {ts}" for n, ts, req, _ in fields
        ]
        if extra is True or (isinstance(extra, dict) and extra):
            parts.append("[key: string]: unknown")
        return "{ " + "; ".join(parts) + " }"

    @staticmethod
    def _prop_doc(prop: dict[str, Any]) -> list[str]:
        lines = _doc_lines(prop.get("description"))
        examples = prop.get("examples")
        if isinstance(examples, list) and examples:
            lines += [f"@example {_literal(e)}" for e in examples]
        elif "example" in prop:
            lines.append(f"@example {_literal(prop['example'])}")
        if "default" in prop:
            lines.append(f"@default {_literal(prop['default'])}")
        if prop.get("format") and prop.get("format") != "binary":
            lines.append(f"@format {prop['format']}")
        if prop.get("deprecated"):
            lines.append("@deprecated")
        return lines

    def _schema_declaration(self, raw: str) -> str:
        schema = self.schemas[raw]
        name = self._names[raw]
        response = raw in self._response_only
        doc = _jsdoc(
            _doc_lines(schema.get("description") if isinstance(schema, dict) else None),
            "",
        )

        is_plain_object = (
            isinstance(schema, dict)
            and bool(schema.get("properties"))
            and not any(
                k in schema for k in ("allOf", "oneOf", "anyOf", "enum", "const")
            )
            and not isinstance(schema.get("type"), list)
            and schema.get("nullable") is not True
        )
        if not is_plain_object:
            return f"{doc}export type {name} = {self._ts(schema, response)};\n"

        lines = [f"{doc}export interface {name} {{\n"]
        for field_name, ts, required, doc_lines in self._fields(schema, response):
            lines.append(_jsdoc(doc_lines, "  "))
            lines.append(
                f"  {_prop_name(field_name)}{'' if required else '?'}: {ts};\n"
            )
        extra = schema.get("additionalProperties")
        if extra is True or (isinstance(extra, dict) and extra):
            lines.append("  [key: string]: unknown;\n")
        lines.append("}\n")
        return "".join(lines)

    # ------------------------------------------------------------------ endpoints

    def _routes(self) -> list[_Route]:
        routes = [
            self._route(path, method, op, item)
            for path, method, op, item in self._operations()
        ]
        return sorted(routes, key=lambda r: r.key)

    def _route(
        self, path: str, method: str, op: dict[str, Any], item: dict[str, Any]
    ) -> _Route:
        # Path-level parameters, overridden by operation-level ones (same name + location).
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_param in [
            *(item.get("parameters") or []),
            *(op.get("parameters") or []),
        ]:
            param = self._deref(raw_param)
            if isinstance(param, dict) and "name" in param and "in" in param:
                merged[(param["in"], param["name"])] = param

        path_fields: dict[str, str] = {}
        query_fields: list[tuple[str, bool]] = []
        header_fields: list[tuple[str, bool]] = []
        for (location, name), param in merged.items():
            required = bool(param.get("required")) or location == "path"
            schema = param.get("schema")
            if schema is None and isinstance(param.get("content"), dict):
                schema = next(iter(param["content"].values()), {}).get("schema")
            ts = self._ts(schema)
            if location == "path":
                path_fields[name] = f"{_prop_name(name)}: {ts}"
            elif location == "query":
                query_fields.append(
                    (f"{_prop_name(name)}{'' if required else '?'}: {ts}", required)
                )
            elif location == "header":
                # Header values travel as strings; keep them compatible with Record<string, string>.
                header_fields.append(
                    (f"{_prop_name(name)}{'' if required else '?'}: string", required)
                )

        for raw_name in _PATH_PARAM.findall(path):
            clean_name = raw_name
            is_catch_all = False
            if raw_name.startswith("path:"):
                clean_name = raw_name[5:]
                is_catch_all = True
            elif raw_name.endswith(":path"):
                clean_name = raw_name[:-5]
                is_catch_all = True
            elif raw_name.startswith("+") or raw_name.endswith("*"):
                clean_name = raw_name.lstrip("+").rstrip("*")
                is_catch_all = True
            elif clean_name.lower() in (
                "path",
                "filepath",
                "file_path",
            ) or clean_name.lower().endswith(("_path", "filepath")):
                is_catch_all = True

            target_ts = "string | string[]" if is_catch_all else "string"

            if clean_name in path_fields:
                if is_catch_all and path_fields[clean_name].endswith(": string"):
                    path_fields[clean_name] = f"{_prop_name(clean_name)}: {target_ts}"
            elif raw_name in path_fields:
                val = path_fields.pop(raw_name)
                ts = (
                    target_ts
                    if (is_catch_all and val.endswith(": string"))
                    else val.split(": ", 1)[1]
                )
                path_fields[clean_name] = f"{_prop_name(clean_name)}: {ts}"
            else:
                path_fields[clean_name] = f"{_prop_name(clean_name)}: {target_ts}"

        params_ts = (
            "{ " + "; ".join(sorted(path_fields.values())) + " }"
            if path_fields
            else "void"
        )
        query_ts = (
            "{ " + "; ".join(f for f, _ in sorted(query_fields)) + " }"
            if query_fields
            else "void"
        )
        headers_ts = (
            "{ " + "; ".join(f for f, _ in sorted(header_fields)) + " }"
            if header_fields
            else ""
        )

        body_ts, body_required, body_encoding = self._request_body(op)
        response_ts = self._response(op)
        has_inputs = bool(
            path_fields or query_fields or header_fields or body_ts != "void"
        )
        error_ts = self._error_response(op, has_inputs=has_inputs)

        request = []
        request.append(f"params: {params_ts}" if path_fields else "params?: never")
        if query_fields:
            request.append(
                f"query{'' if any(r for _, r in query_fields) else '?'}: {query_ts}"
            )
        else:
            request.append("query?: never")
        if header_fields:
            request.append(
                f"headers{'' if any(r for _, r in header_fields) else '?'}: {headers_ts}"
            )
        if body_ts != "void":
            request.append(f"body{'' if body_required else '?'}: {body_ts}")
        else:
            request.append("body?: never")

        upper = method.upper()
        return _Route(
            key=f"{upper} {path}",
            method=upper,
            path=path,
            summary=str(op.get("summary") or ""),
            description=str(op.get("description") or ""),
            deprecated=bool(op.get("deprecated")),
            params_ts=params_ts,
            query_ts=query_ts,
            body_ts=body_ts,
            response_ts=response_ts,
            error_ts=error_ts,
            request_ts="{ " + "; ".join(request) + " }",
            body_encoding=body_encoding,
        )

    def _request_body(self, op: dict[str, Any]) -> tuple[str, bool, str]:
        body = self._deref(op.get("requestBody"))
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("content"), dict)
            or not body["content"]
        ):
            return "void", False, "json"
        content: dict[str, Any] = body["content"]
        required = bool(body.get("required"))

        for media_type, encoding in _BODY_MEDIA_TYPES:
            if media_type in content:
                ts = self._ts((content[media_type] or {}).get("schema"))
                if encoding == "multipart":
                    ts = f"{_wrap(ts)} | FormData"
                elif encoding == "form":
                    ts = f"{_wrap(ts)} | URLSearchParams"
                return ts, required, encoding
        for media_type, media in content.items():
            if media_type.endswith("+json"):
                return self._ts((media or {}).get("schema")), required, "json"
        return "Blob | ArrayBuffer | string", required, "raw"

    def _content_ts(self, response: Any, *, response_schema: bool = True) -> str:
        if not isinstance(response, dict):
            return "unknown"
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, dict) or not content:
            return "unknown"
        for media_type, media in content.items():
            if media_type == "application/json" or media_type.endswith("+json"):
                return self._ts((media or {}).get("schema"), response=response_schema)
        if "text/event-stream" in content:
            return "ReadableStream<string>"
        if any(mt.startswith("text/") for mt in content):
            return "string"
        return "Blob"

    def _response(self, op: dict[str, Any]) -> str:
        # Keys may be ints (raw Ninja schema) or strings (JSON-loaded schema).
        responses = {str(k): v for k, v in (op.get("responses") or {}).items()}
        codes = sorted(int(c) for c in responses if c.isdigit() and 200 <= int(c) < 300)
        if codes:
            code = codes[0]
            response = self._deref(responses[str(code)])
        elif "2XX" in responses:
            code, response = 200, self._deref(responses["2XX"])
        else:
            return "unknown"

        if code in (204, 205):
            return "void"
        return self._content_ts(response, response_schema=True)

    def _error_response(self, op: dict[str, Any], *, has_inputs: bool = False) -> str:
        responses = {str(k): v for k, v in (op.get("responses") or {}).items()}
        error_types: list[str] = []
        for k in sorted(
            responses, key=lambda x: (0, int(x)) if x.isdigit() else (1, x)
        ):
            if (k.isdigit() and int(k) >= 400) or k in ("4XX", "5XX", "default"):
                resp = self._deref(responses[k])
                error_types.append(self._content_ts(resp, response_schema=True))

        concrete = [t for t in error_types if t != "unknown"]
        if concrete:
            return _union(concrete)
        if has_inputs:
            return "NinjaHttpError | NinjaValidationError"
        return "NinjaHttpError"

    # ------------------------------------------------------------------ rendering

    def _render(self, *, declarations_only: bool) -> str:
        routes = self._routes()
        out: list[str] = [self._header(), "\n"]

        for raw in sorted(self.schemas, key=lambda r: self._names[r]):
            out.append(self._schema_declaration(raw))
            out.append("\n")

        out.append("export interface NinjaEndpoints {\n")
        for r in routes:
            doc = _doc_lines(r.summary)
            if r.description and r.description != r.summary:
                doc += _doc_lines(r.description)
            if r.deprecated:
                doc.append("@deprecated")
            out.append(_jsdoc(doc, "  "))
            out.append(f"  {_literal(r.key)}: {{\n")
            out.append(f"    method: {_literal(r.method)};\n")
            out.append(f"    path: {_literal(r.path)};\n")
            out.append(f"    params: {r.params_ts};\n")
            out.append(f"    query: {r.query_ts};\n")
            out.append(f"    body: {r.body_ts};\n")
            out.append(f"    response: {r.response_ts};\n")
            out.append(f"    error: {r.error_ts};\n")
            out.append(f"    request: {r.request_ts};\n")
            out.append("  };\n")
        out.append("}\n\n")

        out.append(runtime.TYPES)
        if declarations_only:
            out.append(runtime.DECLARATIONS)
        else:
            encodings = {
                r.key: r.body_encoding for r in routes if r.body_encoding != "json"
            }
            out.append(
                "\nconst BODY_ENCODINGS: Record<string, BodyEncoding | undefined> = {"
            )
            if encodings:
                out.append("\n")
                for key, encoding in encodings.items():
                    out.append(f"  {_literal(key)}: {_literal(encoding)},\n")
            out.append("};\n")
            out.append(runtime.IMPLEMENTATION)
        return "".join(out)

    def _header(self) -> str:
        info = self.openapi.get("info") or {}
        lines = ["Auto-generated by django-ninja-ts. Do not edit by hand."]
        if info.get("title"):
            version = f" ({info['version']})" if info.get("version") else ""
            lines.append(f"API: {info['title']}{version}")
        lines += _doc_lines(info.get("description"))
        return _jsdoc(lines, "")


def generate_types(openapi: dict[str, Any], **options: Any) -> str:
    """Generate TypeScript declarations (``.d.ts``) from an OpenAPI document."""
    return TypeScriptGenerator(openapi, **options).generate_types()


def generate_sdk(openapi: dict[str, Any], **options: Any) -> str:
    """Generate a standalone TypeScript SDK (``.ts``) from an OpenAPI document."""
    return TypeScriptGenerator(openapi, **options).generate_sdk()
