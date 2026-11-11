// @ts-check

/**
 * @typedef {import("../sdk/api").TodoOut} TodoResponse
 * @typedef {import("../sdk/api").TodoIn} CreateTodoRequest
 * @typedef {import("../sdk/api").NinjaClient} NinjaClient
 * @typedef {import("../sdk/api").NinjaRequestInit} NinjaRequestInit
 * @typedef {import("../sdk/api").RequestContext} RequestContext
 */

const DEFAULT_RETRY_METHODS = ["GET", "HEAD", "OPTIONS", "PUT", "DELETE"];

/**
 * Custom error class for API errors.
 * @template [T=unknown]
 * @extends {Error}
 */
class NinjaApiError extends Error {
  /**
   * @param {Response} response
   * @param {T} data
   * @param {string} [message]
   */
  constructor(response, data, message) {
    super(message ?? `Request failed with status ${response.status}`);
    Object.setPrototypeOf(this, NinjaApiError.prototype);
    this.name = "NinjaApiError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.data = data;
    this.response = response;
    this.headers = response.headers;
  }
}

/**
 * Type guard for NinjaApiError.
 * @template [T=unknown]
 * @param {unknown} error
 * @returns {error is NinjaApiError<T>}
 */
function isNinjaApiError(error) {
  return error instanceof NinjaApiError;
}

/**
 * @param {unknown} value
 * @param {Set<unknown>} [seen]
 * @returns {boolean}
 */
function hasBlobValue(value, seen = new Set()) {
  if (typeof Blob !== "undefined" && value instanceof Blob) return true;
  if (typeof File !== "undefined" && value instanceof File) return true;
  if (!value || typeof value !== "object" || seen.has(value)) return false;
  seen.add(value);
  if (Array.isArray(value)) {
    return value.some((/** @type {unknown} */ item) =>
      hasBlobValue(item, seen),
    );
  }
  for (const v of Object.values(value)) {
    if (hasBlobValue(v, seen)) return true;
  }
  return false;
}

/**
 * Creates an AbortSignal that aborts after a timeout in milliseconds.
 * @param {number} [timeoutMs]
 * @returns {AbortSignal | undefined}
 */
function createTimeoutSignal(timeoutMs) {
  if (timeoutMs === undefined || timeoutMs <= 0) return undefined;
  if (
    typeof AbortSignal !== "undefined" &&
    typeof AbortSignal.timeout === "function"
  ) {
    return AbortSignal.timeout(timeoutMs);
  }
  if (typeof AbortController === "undefined") return undefined;
  const controller = new AbortController();
  const timeoutReason =
    typeof DOMException !== "undefined"
      ? new DOMException("The operation timed out.", "TimeoutError")
      : new Error("The operation timed out.");
  const timer = setTimeout(() => controller.abort(timeoutReason), timeoutMs);
  const maybeNodeTimer = /** @type {any} */ (timer);
  if (maybeNodeTimer && typeof maybeNodeTimer.unref === "function") {
    maybeNodeTimer.unref();
  }
  return controller.signal;
}

/**
 * Combines two AbortSignals into one.
 * @param {AbortSignal} [signalA]
 * @param {AbortSignal} [signalB]
 * @returns {AbortSignal | undefined}
 */
function combineSignals(signalA, signalB) {
  if (!signalA) return signalB;
  if (!signalB) return signalA;
  if (
    typeof AbortSignal !== "undefined" &&
    typeof AbortSignal.any === "function"
  ) {
    return AbortSignal.any([signalA, signalB]);
  }
  if (typeof AbortController === "undefined") return signalA;
  const controller = new AbortController();
  const cleanup = () => {
    signalA.removeEventListener("abort", handleA);
    signalB.removeEventListener("abort", handleB);
  };
  const handleA = () => {
    cleanup();
    controller.abort(signalA.reason);
  };
  const handleB = () => {
    cleanup();
    controller.abort(signalB.reason);
  };
  if (signalA.aborted) {
    controller.abort(signalA.reason);
  } else if (signalB.aborted) {
    controller.abort(signalB.reason);
  } else {
    signalA.addEventListener("abort", handleA, { once: true });
    signalB.addEventListener("abort", handleB, { once: true });
  }
  return controller.signal;
}

/**
 * Appends a query parameter value to URLSearchParams.
 * @param {URLSearchParams} search
 * @param {string} key
 * @param {unknown} value
 */
function appendQueryParam(search, key, value) {
  if (value === undefined || value === null) return;
  if (Array.isArray(value)) {
    for (const item of value) appendQueryParam(search, key, item);
  } else if (value instanceof Date) {
    search.append(key, value.toISOString());
  } else if (typeof value === "object") {
    search.append(key, JSON.stringify(value));
  } else {
    search.append(key, String(value));
  }
}

/**
 * @param {unknown} data
 * @param {string} fallback
 * @returns {string}
 */
function errorMessage(data, fallback) {
  if (typeof data === "string" && data) return data;
  if (data && typeof data === "object") {
    const record = /** @type {Record<string, unknown>} */ (data);
    if (typeof record["detail"] === "string" && record["detail"])
      return record["detail"];
    if (Array.isArray(record["detail"])) {
      const messages = /** @type {unknown[]} */ (record["detail"])
        .map((/** @type {unknown} */ item) => {
          if (item && typeof item === "object") {
            const err = /** @type {Record<string, unknown>} */ (item);
            const loc = Array.isArray(err["loc"]) ? err["loc"].join(".") : "";
            const msg = typeof err["msg"] === "string" ? err["msg"] : "";
            return loc && msg ? `${loc}: ${msg}` : msg || JSON.stringify(item);
          }
          return String(item);
        })
        .filter(Boolean);
      return messages.length > 0
        ? `Validation error: ${messages.join("; ")}`
        : "Validation error";
    }
    if (typeof record["message"] === "string" && record["message"])
      return record["message"];
    if (typeof record["error"] === "string" && record["error"])
      return record["error"];
    if (typeof record["title"] === "string" && record["title"])
      return record["title"];
    if (Array.isArray(record["errors"])) {
      return `Errors: ${/** @type {unknown[]} */ (record["errors"]).map((/** @type {unknown} */ e) => (typeof e === "string" ? e : JSON.stringify(e))).join("; ")}`;
    }
  }
  return fallback;
}

const BINARY_CONTENT_TYPE =
  /^(image|audio|video)\/|application\/(octet-stream|pdf|zip|gzip|vnd\.|x-)/;

/**
 * @param {Response} response
 * @returns {Promise<unknown>}
 */
async function readBody(response) {
  const contentType = response.headers.get("content-type") ?? "";
  if (
    contentType.includes("application/json") ||
    contentType.includes("+json")
  ) {
    const text = await response.text();
    return text ? JSON.parse(text) : undefined;
  }
  if (contentType.includes("text/event-stream") && response.body) {
    return typeof TextDecoderStream !== "undefined"
      ? response.body.pipeThrough(new TextDecoderStream())
      : response.body;
  }
  if (BINARY_CONTENT_TYPE.test(contentType)) {
    return response.blob();
  }
  if (contentType === "" || contentType.startsWith("text/"))
    return response.text();
  return response.blob();
}

/**
 * @param {Response} response
 * @returns {Promise<unknown>}
 */
async function readErrorBody(response) {
  const contentType = response.headers.get("content-type") ?? "";
  const fallback = {
    message: response.statusText || `HTTP ${response.status}`,
  };
  try {
    if (typeof response.text === "function") {
      const text = await response.text();
      if (!text) {
        return fallback;
      }
      if (
        contentType.includes("application/json") ||
        contentType.includes("+json") ||
        (text.startsWith("{") && text.endsWith("}")) ||
        (text.startsWith("[") && text.endsWith("]"))
      ) {
        try {
          return JSON.parse(text);
        } catch {
          // Fallback to text message
        }
      }
      return { message: text };
    }
    if (typeof response.json === "function") {
      return await response.json();
    }
    return fallback;
  } catch {
    return fallback;
  }
}

/**
 * @param {number} attempt
 * @param {number} baseDelay
 * @param {Response} [res]
 * @returns {number}
 */
function retryDelay(attempt, baseDelay, res) {
  const retryAfter = res ? res.headers.get("Retry-After") : null;
  if (retryAfter) {
    const seconds = parseInt(retryAfter, 10);
    if (!isNaN(seconds)) return Math.max(0, seconds * 1000);
    const dateMs = Date.parse(retryAfter);
    if (!isNaN(dateMs)) return Math.max(0, dateMs - Date.now());
  }
  return baseDelay * Math.pow(2, attempt - 1) * (0.5 + Math.random() * 0.5);
}

/**
 * Runtime implementation of createNinjaClient() matching packages/django-ninja-ts
 * @param {string} [baseUrl=""]
 * @param {import("../sdk/api").NinjaClientOptions} [clientOptions={}]
 * @returns {NinjaClient}
 */
function createNinjaClient(baseUrl = "", clientOptions = {}) {
  const root = baseUrl.replace(/\/+$/, "");

  return {
    baseUrl: root,
    async fetch(endpoint, ...args) {
      const options = /** @type {any} */ (args[0] || {});
      const separator = endpoint.indexOf(" ");
      const method = endpoint.slice(0, separator);
      const params = options.params ?? {};

      let path = endpoint
        .slice(separator + 1)
        .replace(/\{([^}]+)\}/g, (_match, rawName) => {
          const isCatchAll =
            rawName.startsWith("+") ||
            rawName.endsWith("*") ||
            rawName.startsWith("path:");
          const name = rawName.replace(/^(\+|path:)/, "").replace(/\*$/, "");
          const value =
            params[name] ?? (name !== rawName ? params[rawName] : undefined);
          if (value === undefined || value === null) {
            throw new Error(`Missing path parameter "${name}" for ${endpoint}`);
          }
          if (Array.isArray(value)) {
            return /** @type {unknown[]} */ (value)
              .map((/** @type {unknown} */ seg) =>
                encodeURIComponent(String(seg)),
              )
              .join("/");
          }
          const str = String(value);
          if (isCatchAll || str.includes("/")) {
            return str
              .split("/")
              .map((/** @type {string} */ seg) => encodeURIComponent(seg))
              .join("/");
          }
          return encodeURIComponent(str);
        });

      let url = root + path;
      if (options.query) {
        const q = new URLSearchParams();
        for (const [k, v] of Object.entries(options.query)) {
          appendQueryParam(q, k, v);
        }
        const qs = q.toString();
        if (qs) url += (url.includes("?") ? "&" : "?") + qs;
      }

      const baseHeaders =
        typeof clientOptions.headers === "function"
          ? await clientOptions.headers()
          : clientOptions.headers;
      const headers = new Headers(baseHeaders);
      if (options.headers) {
        for (const [k, v] of Object.entries(options.headers)) {
          headers.set(k, String(v));
        }
      }

      /** @type {NinjaRequestInit} */
      const init = { method, headers };

      if (options.body !== undefined) {
        const isFormData =
          typeof FormData !== "undefined" && options.body instanceof FormData;
        if (isFormData || hasBlobValue(options.body)) {
          if (isFormData) {
            init.body = options.body;
          } else {
            const form = new FormData();
            for (const [key, val] of Object.entries(options.body)) {
              form.append(key, /** @type {any} */ (val));
            }
            init.body = form;
          }
          headers.delete("Content-Type");
        } else {
          if (!headers.has("Content-Type")) {
            headers.set("Content-Type", "application/json");
          }
          init.body = JSON.stringify(options.body);
        }
      }

      const timeoutMs = options.timeoutMs ?? clientOptions.timeoutMs;
      const timeoutSignal = createTimeoutSignal(timeoutMs);
      const signal = combineSignals(options.signal, timeoutSignal);
      if (signal) init.signal = signal;

      if (options.credentials ?? clientOptions.credentials) {
        init.credentials = options.credentials ?? clientOptions.credentials;
      }

      if (clientOptions.next || options.next) {
        // @ts-ignore
        init.next = { ...clientOptions.next, ...options.next };
      }

      if (options.duplex) {
        // @ts-ignore
        init.duplex = options.duplex;
      }

      /** @type {RequestContext} */
      const context = { endpoint, url };

      if (clientOptions.onRequest) {
        await clientOptions.onRequest(endpoint, init, context);
      }
      if (options.onRequest) {
        await options.onRequest(endpoint, init, context);
      }

      /** @type {number | import("../sdk/api").NinjaRetryConfig | undefined} */
      const retryOpt = options.retry ?? clientOptions.retry;
      let maxAttempts = 1;
      let baseDelay = 300;
      let retryStatuses = [408, 429, 500, 502, 503, 504];
      let retryMethods = DEFAULT_RETRY_METHODS;

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
        if (Array.isArray(retryOpt.methods)) {
          retryMethods = retryOpt.methods.map((/** @type {string} */ m) =>
            m.toUpperCase(),
          );
        }
      }

      if (!retryMethods.includes(method.toUpperCase())) {
        maxAttempts = 1;
      }

      const fetchFn = clientOptions.fetch || fetch;
      /** @type {Response | undefined} */
      let lastRes;
      let attempt = 0;

      while (true) {
        try {
          const res = await fetchFn(url, init);
          lastRes = res;
          if (
            !res.ok &&
            attempt < maxAttempts - 1 &&
            retryStatuses.includes(res.status) &&
            (!init.signal || !init.signal.aborted)
          ) {
            attempt++;
            const delay = retryDelay(attempt, baseDelay, res);
            await new Promise((resolve) => setTimeout(resolve, delay));
            continue;
          }
          break;
        } catch (err) {
          if (
            attempt < maxAttempts - 1 &&
            (!init.signal || !init.signal.aborted)
          ) {
            attempt++;
            const delay = retryDelay(attempt, baseDelay);
            await new Promise((resolve) => setTimeout(resolve, delay));
            continue;
          }
          const errorObj = err instanceof Error ? err : new Error(String(err));
          if (options.onError) {
            await options.onError(errorObj, context);
          }
          if (clientOptions.onError) {
            await clientOptions.onError(errorObj, context);
          }
          throw err;
        }
      }

      const res = /** @type {Response} */ (lastRes);

      if (options.onResponse) {
        await options.onResponse(res, context);
      }
      if (clientOptions.onResponse) {
        await clientOptions.onResponse(res, context);
      }

      if (!res.ok) {
        const errData = await readErrorBody(res);
        const apiError = new NinjaApiError(
          res,
          errData,
          errorMessage(errData, res.statusText || `HTTP ${res.status}`),
        );
        if (options.onError) {
          await options.onError(apiError, context);
        }
        if (clientOptions.onError) {
          await clientOptions.onError(apiError, context);
        }
        throw apiError;
      }

      if (
        res.status === 204 ||
        res.status === 205 ||
        res.headers.get("content-length") === "0"
      ) {
        return /** @type {any} */ (undefined);
      }
      return /** @type {any} */ (await readBody(res));
    },
  };
}

// @ts-ignore - Vue is loaded globally via CDN
const { createApp, ref, reactive, onMounted } = Vue;

createApp({
  setup() {
    /** @type {{ value: string }} */
    const baseUrl = ref("http://localhost:8000");
    /** @type {{ value: TodoResponse[] }} */
    const todos = ref([]);
    const loading = ref(false);
    const creating = ref(false);
    const connectionError = ref(false);
    /** @type {{ value: { message: string; fields?: Record<string, string> | null } | null }} */
    const createError = ref(null);
    /** @type {{ value: string | null }} */
    const lookupError = ref(null);
    /** @type {{ value: string }} */
    const searchId = ref("todo_1");
    /** @type {{ value: TodoResponse | null }} */
    const selectedTodo = ref(null);

    /** @type {CreateTodoRequest} */
    const form = reactive({
      title: "",
      priority: "normal",
    });

    const client = () =>
      createNinjaClient(baseUrl.value, {
        timeoutMs: 8000,
        onError(err) {
          console.warn("[DjangoNinjaClient]", err.message);
        },
      });

    async function loadTodos() {
      loading.value = true;
      connectionError.value = false;
      try {
        todos.value = await client().fetch("GET /api/todos");
      } catch {
        connectionError.value = true;
      } finally {
        loading.value = false;
      }
    }

    async function createTodo() {
      creating.value = true;
      createError.value = null;
      try {
        const created = await client().fetch("POST /api/todos", {
          body: {
            title: form.title,
            priority: form.priority,
          },
        });
        todos.value.push(created);
        selectedTodo.value = created;
        searchId.value = created.id;
        form.title = "";
        form.priority = "normal";
      } catch (/** @type {any} */ err) {
        /** @type {Record<string, string> | null} */
        let fields = null;
        if (Array.isArray(err.data?.detail)) {
          /** @type {Record<string, string>} */
          const fieldMap = {};
          for (const item of err.data.detail) {
            const field = String(item.loc?.[item.loc.length - 1] || "error");
            fieldMap[field] = String(item.msg);
          }
          fields = fieldMap;
        } else if (err.data?.errors) {
          fields = err.data.errors;
        }

        createError.value = {
          message:
            typeof err.message === "string"
              ? err.message
              : "Validation error (422)",
          fields,
        };
      } finally {
        creating.value = false;
      }
    }

    /**
     * @param {string} id
     */
    async function fetchTodoById(id) {
      if (!id) return;
      lookupError.value = null;
      selectedTodo.value = null;
      try {
        selectedTodo.value = await client().fetch("GET /api/todos/{id}", {
          params: { id: id.trim() },
        });
      } catch (/** @type {any} */ err) {
        lookupError.value = `${err.status || "Error"}: ${err.message}`;
      }
    }

    /**
     * @param {string} id
     */
    function selectFromList(id) {
      searchId.value = id;
      fetchTodoById(id);
    }

    /**
     * @param {string} priority
     */
    function priorityBadgeClass(priority) {
      switch (priority) {
        case "high":
          return "bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/25";
        case "low":
          return "bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/25";
        default:
          return "bg-sky-500/10 text-sky-600 dark:text-sky-400 border-sky-500/25";
      }
    }

    onMounted(loadTodos);

    return {
      baseUrl,
      todos,
      loading,
      creating,
      connectionError,
      createError,
      lookupError,
      searchId,
      selectedTodo,
      form,
      loadTodos,
      createTodo,
      fetchTodoById,
      selectFromList,
      priorityBadgeClass,
    };
  },
}).mount("#app");
