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
    "ResponseError",
    "RequestOptions",
    "BaseRequestOptions",
    "NextFetchRequestConfig",
    "NinjaRetryConfig",
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
export type ResponseError<K extends EndpointKey> = NinjaEndpoints[K]["error"];

export interface NextFetchRequestConfig {
  revalidate?: number | false;
  tags?: string[];
}

export interface NinjaRetryConfig {
  /** Maximum number of retry attempts (in addition to the initial request). */
  attempts: number;
  /** Base delay in milliseconds before the first retry (default: 300ms). */
  delayMs?: number;
  /** HTTP status codes that trigger a retry (default: [408, 429, 500, 502, 503, 504]). */
  statusCodes?: number[];
}

export interface BaseRequestOptions {
  headers?: Record<string, string>;
  credentials?: RequestCredentials;
  signal?: AbortSignal;
  cache?: RequestCache;
  next?: NextFetchRequestConfig;
  duplex?: "half";
  timeoutMs?: number;
  retry?: number | NinjaRetryConfig;
}

export type RequestOptions<K extends EndpointKey> = NinjaEndpoints[K]["request"] & BaseRequestOptions;

export type BodyEncoding = "json" | "form" | "multipart" | "raw";

export interface NinjaClientOptions {
  /** Static headers, or a (sync/async) callback evaluated on every request (e.g. JWT). */
  headers?: Record<string, string> | (() => Record<string, string> | Promise<Record<string, string>>);
  credentials?: RequestCredentials;
  /** Custom fetch implementation (defaults to the global fetch). */
  fetch?: typeof fetch;
  /** Default Next.js App Router cache configuration (revalidate / tags). */
  next?: NextFetchRequestConfig;
  /** Default request timeout in milliseconds. */
  timeoutMs?: number;
  /** Default retry policy for failed requests (network errors or retryable status codes). */
  retry?: number | NinjaRetryConfig;
  /** Hook invoked before each request is sent. Can mutate `init` (e.g. inject headers) or perform logging. */
  onRequest?: (endpoint: string, init: RequestInit) => Promise<void> | void;
  /** Hook invoked after a response is received, before error handling or body parsing. */
  onResponse?: (response: Response) => Promise<void> | void;
  /** Hook invoked when an error occurs (network failure or non-2xx HTTP response). */
  onError?: (error: NinjaApiError | Error) => Promise<void> | void;
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
  readonly headers: Headers;
  constructor(response: Response, data: T, message?: string);
}

export declare function createNinjaClient(baseUrl?: string, clientOptions?: NinjaClientOptions): NinjaClient;
"""

IMPLEMENTATION = r"""
export class NinjaApiError<T = unknown> extends Error {
  readonly status: number;
  readonly data: T;
  readonly response: Response;
  readonly headers: Headers;

  constructor(response: Response, data: T, message?: string) {
    super(message ?? `Request failed with status ${response.status}`);
    this.name = "NinjaApiError";
    this.status = response.status;
    this.data = data;
    this.response = response;
    this.headers = response.headers;
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

function isReadableStream(value: unknown): value is ReadableStream {
  return (
    (typeof ReadableStream !== "undefined" && value instanceof ReadableStream) ||
    (value !== null && typeof value === "object" && typeof (value as { getReader?: unknown }).getReader === "function")
  );
}

function isBodyInit(body: unknown): body is BodyInit {
  return (
    (typeof FormData !== "undefined" && body instanceof FormData) ||
    (typeof URLSearchParams !== "undefined" && body instanceof URLSearchParams) ||
    (typeof Blob !== "undefined" && body instanceof Blob) ||
    isReadableStream(body) ||
    body instanceof ArrayBuffer ||
    ArrayBuffer.isView(body)
  );
}

function createTimeoutSignal(timeoutMs?: number): AbortSignal | undefined {
  if (timeoutMs === undefined || timeoutMs <= 0) return undefined;
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(timeoutMs);
  }
  if (typeof AbortController === "undefined") return undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (
    typeof timer === "object" &&
    timer &&
    "unref" in timer &&
    typeof (timer as { unref: () => void }).unref === "function"
  ) {
    (timer as { unref: () => void }).unref();
  }
  return controller.signal;
}

function combineSignals(signalA?: AbortSignal, signalB?: AbortSignal): AbortSignal | undefined {
  if (!signalA) return signalB;
  if (!signalB) return signalA;
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function") {
    return AbortSignal.any([signalA, signalB]);
  }
  if (typeof AbortController === "undefined") return signalA;
  const controller = new AbortController();
  const onAbort = () => {
    controller.abort();
    signalA.removeEventListener("abort", onAbort);
    signalB.removeEventListener("abort", onAbort);
  };
  if (signalA.aborted || signalB.aborted) {
    controller.abort();
  } else {
    signalA.addEventListener("abort", onAbort, { once: true });
    signalB.addEventListener("abort", onAbort, { once: true });
  }
  return controller.signal;
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
    const path = endpoint.slice(separator + 1).replace(/\{([^}]+)\}/g, (_match, rawName: string) => {
      const isCatchAll = rawName.startsWith("+") || rawName.endsWith("*");
      const name = rawName.replace(/^\+/, "").replace(/\*$/, "");
      const value = params[name] ?? (name !== rawName ? params[rawName] : undefined);
      if (value === undefined || value === null) {
        throw new Error(`Missing path parameter "${name}" for ${endpoint}`);
      }
      if (Array.isArray(value)) {
        return value.map((seg) => encodeURIComponent(String(seg))).join("/");
      }
      const str = String(value);
      if (isCatchAll || str.includes("/")) {
        return str.split("/").map((seg) => encodeURIComponent(seg)).join("/");
      }
      return encodeURIComponent(str);
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

    const timeoutMs = options.timeoutMs ?? clientOptions.timeoutMs;
    const timeoutSignal = createTimeoutSignal(timeoutMs);
    const signal = combineSignals(options.signal, timeoutSignal);
    if (signal) init.signal = signal;

    if (options.cache) init.cache = options.cache;

    const nextConfig =
      clientOptions.next || options.next
        ? { ...clientOptions.next, ...options.next }
        : undefined;
    if (nextConfig) {
      (init as Record<string, unknown>)["next"] = nextConfig;
    }

    const duplex =
      options.duplex ?? (isReadableStream(init.body) ? "half" : undefined);
    if (duplex) {
      (init as Record<string, unknown>)["duplex"] = duplex;
    }

    if (clientOptions.onRequest) {
      await clientOptions.onRequest(endpoint, init);
    }

    const retryOpt = options.retry ?? clientOptions.retry;
    let maxAttempts = 1;
    let baseDelay = 300;
    let retryStatuses = [408, 429, 500, 502, 503, 504];

    if (typeof retryOpt === "number" && retryOpt > 0) {
      maxAttempts = 1 + retryOpt;
    } else if (typeof retryOpt === "object" && retryOpt !== null) {
      if (typeof retryOpt.attempts === "number" && retryOpt.attempts > 0) {
        maxAttempts = 1 + retryOpt.attempts;
      }
      if (typeof retryOpt.delayMs === "number" && retryOpt.delayMs >= 0) {
        baseDelay = retryOpt.delayMs;
      }
      if (Array.isArray(retryOpt.statusCodes)) {
        retryStatuses = retryOpt.statusCodes;
      }
    }

    const fetchFn = clientOptions.fetch ?? globalThis.fetch.bind(globalThis);
    let lastResponse: Response | undefined;
    let attempt = 0;

    while (true) {
      try {
        const res = await fetchFn(url, init);
        lastResponse = res;
        if (
          !res.ok &&
          attempt < maxAttempts - 1 &&
          retryStatuses.includes(res.status) &&
          (!init.signal || !init.signal.aborted)
        ) {
          attempt++;
          let delay = baseDelay * Math.pow(2, attempt - 1);
          const retryAfter = res.headers.get("Retry-After");
          if (retryAfter) {
            const seconds = parseInt(retryAfter, 10);
            if (!isNaN(seconds)) delay = seconds * 1000;
          }
          await new Promise((resolve) => setTimeout(resolve, delay));
          continue;
        }
        break;
      } catch (networkError) {
        if (
          attempt < maxAttempts - 1 &&
          (!init.signal || !init.signal.aborted)
        ) {
          attempt++;
          const delay = baseDelay * Math.pow(2, attempt - 1);
          await new Promise((resolve) => setTimeout(resolve, delay));
          continue;
        }
        if (clientOptions.onError) {
          await clientOptions.onError(
            networkError instanceof Error ? networkError : new Error(String(networkError))
          );
        }
        throw networkError;
      }
    }

    const response = lastResponse!;

    if (clientOptions.onResponse) {
      await clientOptions.onResponse(response);
    }

    if (!response.ok) {
      const data = await readBody(response).catch(() => undefined);
      const apiError = new NinjaApiError(
        response,
        data,
        errorMessage(data, response.statusText || `HTTP ${response.status}`)
      );
      if (clientOptions.onError) {
        await clientOptions.onError(apiError);
      }
      throw apiError;
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
