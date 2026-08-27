const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
}

// Mirrors the {"code": ..., "message": ...} detail shape every module's
// router raises via HTTPException (see modules/crm/api/router.py).
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    if (response.status === 401) {
      // Told AuthProvider directly rather than importing it here — api.ts
      // has no business knowing about session state, only HTTP.
      window.dispatchEvent(new Event("auth:unauthorized"));
    }
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const code = typeof detail === "object" && detail !== null ? detail.code : "UNKNOWN";
    const message =
      typeof detail === "object" && detail !== null
        ? detail.message
        : typeof detail === "string"
          ? detail
          : response.statusText;
    throw new ApiError(response.status, code, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
