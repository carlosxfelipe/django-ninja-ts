// @ts-check

/**
 * @typedef {import("../sdk/api").TodoOut} TodoResponse
 * @typedef {import("../sdk/api").TodoIn} CreateTodoRequest
 * @typedef {import("../sdk/api").NinjaClient} NinjaClient
 */

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
  setTimeout(() => controller.abort(), timeoutMs);
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
  const onAbort = () => controller.abort();
  if (signalA.aborted || signalB.aborted) {
    controller.abort();
  } else {
    signalA.addEventListener("abort", onAbort, { once: true });
    signalB.addEventListener("abort", onAbort, { once: true });
  }
  return controller.signal;
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

      // Replace path parameters (supports regular, wildcard {+path}, and {path:name})
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
            return value
              .map((seg) => encodeURIComponent(String(seg)))
              .join("/");
          }
          const str = String(value);
          if (isCatchAll || str.includes("/")) {
            return str
              .split("/")
              .map((seg) => encodeURIComponent(seg))
              .join("/");
          }
          return encodeURIComponent(str);
        });

      if (path.includes(":") || path.includes("*")) {
        const keys = Object.keys(params).sort((a, b) => b.length - a.length);
        for (const k of keys) {
          const v = params[k];
          path = path.replace(":" + k, encodeURIComponent(String(v)));
          path = path.replace("*" + k, String(v));
        }
      }

      let url = root + path;
      if (options.query) {
        const q = new URLSearchParams();
        for (const [k, v] of Object.entries(options.query)) {
          if (v !== undefined && v !== null) {
            q.set(k, String(v));
          }
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

      let body = undefined;
      if (options.body !== undefined) {
        if (
          typeof FormData !== "undefined" &&
          options.body instanceof FormData
        ) {
          body = options.body;
        } else {
          if (!headers.has("Content-Type")) {
            headers.set("Content-Type", "application/json");
          }
          body = JSON.stringify(options.body);
        }
      }

      const timeoutMs = options.timeoutMs ?? clientOptions.timeoutMs;
      const timeoutSignal = createTimeoutSignal(timeoutMs);
      const signal = combineSignals(options.signal, timeoutSignal);

      /** @type {RequestInit} */
      const init = {
        method,
        headers,
        body,
        credentials: options.credentials ?? clientOptions.credentials,
        signal,
      };

      if (clientOptions.next || options.next) {
        // @ts-ignore
        init.next = { ...clientOptions.next, ...options.next };
      }

      if (options.duplex) {
        // @ts-ignore
        init.duplex = options.duplex;
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
        } catch (err) {
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
              err instanceof Error ? err : new Error(String(err)),
            );
          }
          throw err;
        }
      }

      const res = /** @type {Response} */ (lastRes);

      if (clientOptions.onResponse) {
        await clientOptions.onResponse(res);
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({ message: res.statusText }));
        const message =
          (err && (err.message || err.error || err.detail)) || res.statusText;
        const apiError = Object.assign(
          new Error(typeof message === "string" ? message : res.statusText),
          { status: res.status, data: err, headers: res.headers },
        );
        if (clientOptions.onError) {
          await clientOptions.onError(apiError);
        }
        throw apiError;
      }

      if (res.status === 204) return /** @type {any} */ (undefined);
      const ctype = res.headers.get("content-type") || "";
      if (ctype.includes("application/json")) {
        return res.json();
      }
      if (ctype.includes("text/event-stream") && res.body) {
        return /** @type {any} */ (
          typeof TextDecoderStream !== "undefined"
            ? res.body.pipeThrough(new TextDecoderStream())
            : res.body
        );
      }
      return /** @type {any} */ (res.text());
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
