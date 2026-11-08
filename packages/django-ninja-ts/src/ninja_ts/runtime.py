"""TypeScript runtime templates emitted into the generated SDK / declarations.

Constraints for the TypeScript below (so the output works everywhere):
- zero dependencies: only ``fetch``, ``Headers``, ``URLSearchParams``, ``FormData``;
- "erasable" syntax only (no enums, namespaces or parameter properties), so the SDK runs
  directly with ``node file.ts`` (type stripping), Deno, Bun and any bundler;
- compiles under ``strict`` and ``exactOptionalPropertyTypes``.
"""

EXPORTED_NAMES = (
    "NinjaEndpoints",
    "EndpointKey",
    "RequestParams",
    "RequestQuery",
    "RequestBody",
    "ResponseData",
    "RequestOptions",
    "BaseRequestOptions",
    "BodyEncoding",
    "NinjaClientOptions",
    "NinjaClient",
    "NinjaApiError",
    "createNinjaClient",
)

TYPES = r"""export type EndpointKey = keyof NinjaEndpoints;

export type RequestParams<K extends EndpointKey> = NinjaEndpoints[K]["params"];
export type RequestQuery<K extends EndpointKey> = NinjaEndpoints[K]["query"];
export type RequestBody<K extends EndpointKey> = NinjaEndpoints[K]["body"];
export type ResponseData<K extends EndpointKey> = NinjaEndpoints[K]["response"];

export interface BaseRequestOptions {
  headers?: Record<string, string>;
  credentials?: RequestCredentials;
  signal?: AbortSignal;
  cache?: RequestCache;
}

export type RequestOptions<K extends EndpointKey> = NinjaEndpoints[K]["request"] & BaseRequestOptions;

export type BodyEncoding = "json" | "form" | "multipart" | "raw";

export interface NinjaClientOptions {
  /** Static headers, or a (sync/async) callback evaluated on every request (e.g. JWT). */
  headers?: Record<string, string> | (() => Record<string, string> | Promise<Record<string, string>>);
  credentials?: RequestCredentials;
  /** Custom fetch implementation (defaults to the global fetch). */
  fetch?: typeof fetch;
}

export interface NinjaClient {
  readonly baseUrl: string;
  fetch<K extends EndpointKey>(
    endpoint: K,
    ...args: {} extends NinjaEndpoints[K]["request"]
      ? [options?: RequestOptions<K>]
      : [options: RequestOptions<K>]
  ): Promise<ResponseData<K>>;
}
"""

DECLARATIONS = r"""
export declare class NinjaApiError<T = unknown> extends Error {
  readonly status: number;
  readonly data: T;
  readonly response: Response;
  constructor(response: Response, data: T, message?: string);
}

export declare function createNinjaClient(baseUrl?: string, clientOptions?: NinjaClientOptions): NinjaClient;
"""

IMPLEMENTATION = r"""
export class NinjaApiError<T = unknown> extends Error {
  readonly status: number;
  readonly data: T;
  readonly response: Response;

  constructor(response: Response, data: T, message?: string) {
    super(message ?? `Request failed with status ${response.status}`);
    this.name = "NinjaApiError";
    this.status = response.status;
    this.data = data;
    this.response = response;
  }
}

type FormEntry = [string, string | Blob];

interface RawRequestOptions extends BaseRequestOptions {
  params?: Record<string, unknown>;
  query?: Record<string, unknown>;
  body?: unknown;
}

function collectEntries(key: string, value: unknown, out: FormEntry[]): void {
  if (value === undefined || value === null) return;
  if (Array.isArray(value)) {
    for (const item of value) collectEntries(key, item, out);
  } else if (typeof Blob !== "undefined" && value instanceof Blob) {
    out.push([key, value]);
  } else if (value instanceof Date) {
    out.push([key, value.toISOString()]);
  } else if (typeof value === "object") {
    out.push([key, JSON.stringify(value)]);
  } else {
    out.push([key, String(value)]);
  }
}

function toEntries(source: unknown): FormEntry[] {
  const out: FormEntry[] = [];
  if (source && typeof source === "object") {
    for (const [key, value] of Object.entries(source)) collectEntries(key, value, out);
  }
  return out;
}

function isBodyInit(body: unknown): body is BodyInit {
  return (
    (typeof FormData !== "undefined" && body instanceof FormData) ||
    (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams) ||
    (typeof Blob !== "undefined" && body instanceof Blob) ||
    (typeof ReadableStream !== "undefined" && body instanceof ReadableStream) ||
    body instanceof ArrayBuffer ||
    ArrayBuffer.isView(body)
  );
}

function errorMessage(data: unknown, fallback: string): string {
  if (typeof data === "string" && data) return data;
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (typeof record["detail"] === "string") return record["detail"];
    if (Array.isArray(record["detail"])) return "Validation error";
    if (typeof record["message"] === "string") return record["message"];
    if (typeof record["error"] === "string") return record["error"];
  }
  return fallback;
}

async function readBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json") || contentType.includes("+json")) {
    const text = await response.text();
    return text ? JSON.parse(text) : undefined;
  }
  if (contentType.includes("text/event-stream") && response.body) {
    return typeof TextDecoderStream !== "undefined"
      ? response.body.pipeThrough(new TextDecoderStream())
      : response.body;
  }
  if (contentType === "" || contentType.startsWith("text/")) return response.text();
  return response.blob();
}

export function createNinjaClient(baseUrl = "", clientOptions: NinjaClientOptions = {}): NinjaClient {
  const root = baseUrl.replace(/\/+$/, "");

  async function request(endpoint: string, options: RawRequestOptions): Promise<unknown> {
    const separator = endpoint.indexOf(" ");
    const method = endpoint.slice(0, separator);
    const params = options.params ?? {};
    const path = endpoint.slice(separator + 1).replace(/\{([^}]+)\}/g, (_match, name: string) => {
      const value = params[name];
      if (value === undefined || value === null) {
        throw new Error(`Missing path parameter "${name}" for ${endpoint}`);
      }
      return encodeURIComponent(String(value));
    });

    let url = root + path;
    if (options.query) {
      const search = new URLSearchParams();
      for (const [key, value] of toEntries(options.query)) {
        if (typeof value === "string") search.append(key, value);
      }
      const qs = search.toString();
      if (qs) url += (url.includes("?") ? "&" : "?") + qs;
    }

    const baseHeaders =
      typeof clientOptions.headers === "function" ? await clientOptions.headers() : clientOptions.headers;
    const headers = new Headers(baseHeaders);
    if (options.headers) {
      for (const [key, value] of Object.entries(options.headers)) headers.set(key, String(value));
    }

    const init: RequestInit = { method, headers };
    if (options.body !== undefined) {
      const encoding = BODY_ENCODINGS[endpoint] ?? "json";
      if (isBodyInit(options.body)) {
        init.body = options.body;
      } else if (encoding === "raw" && typeof options.body === "string") {
        init.body = options.body;
      } else if (encoding === "multipart") {
        const form = new FormData();
        for (const [key, value] of toEntries(options.body)) form.append(key, value);
        init.body = form;
      } else if (encoding === "form") {
        const form = new URLSearchParams();
        for (const [key, value] of toEntries(options.body)) {
          if (typeof value === "string") form.append(key, value);
        }
        init.body = form;
      } else {
        if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
        init.body = JSON.stringify(options.body);
      }
    }
    const credentials = options.credentials ?? clientOptions.credentials;
    if (credentials) init.credentials = credentials;
    if (options.signal) init.signal = options.signal;
    if (options.cache) init.cache = options.cache;

    const fetchFn = clientOptions.fetch ?? globalThis.fetch.bind(globalThis);
    const response = await fetchFn(url, init);

    if (!response.ok) {
      const data = await readBody(response).catch(() => undefined);
      throw new NinjaApiError(response, data, errorMessage(data, response.statusText || `HTTP ${response.status}`));
    }
    if (response.status === 204 || response.status === 205 || response.headers.get("content-length") === "0") {
      return undefined;
    }
    return readBody(response);
  }

  return {
    baseUrl: root,
    fetch(endpoint, ...args) {
      const [options] = args as unknown as [RawRequestOptions?];
      return request(String(endpoint), options ?? {}) as Promise<never>;
    },
  };
}
"""
