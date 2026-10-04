import { readStoredLanguage } from "./i18n";

export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    /** Shown to the user, in the language they picked. */
    message: string,
    /** The backend's English, for logs; equal to `message` for an English user. */
    public messageEn: string = message,
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

interface Bilingual {
  en: string;
  fr: string;
}

// Refusals the backend cannot word itself: FastAPI's own request validation (its detail is a
// list of field errors), a proxy refusing an oversized body, and a server that never answered.
const VALIDATION_FAILED: Bilingual = {
  en: "Some values sent are not valid.",
  fr: "Certaines valeurs envoyées ne sont pas valides.",
};
const TOO_LARGE: Bilingual = {
  en: "What was sent is too large for the server. Try again with a smaller file.",
  fr: "L'envoi est trop volumineux pour le serveur. Réessayez avec un fichier plus petit.",
};
const SERVER_UNREACHABLE: Bilingual = {
  en: "The server cannot be reached. Check the connection and try again.",
  fr: "Le serveur est injoignable. Vérifiez la connexion et réessayez.",
};

function fixedError(status: number, code: string, text: Bilingual): ApiError {
  return new ApiError(status, code, text[readStoredLanguage()], text.en);
}

// Mirrors the {"code", "message", "message_fr"} detail every router raises (core.domain.result.err_detail).
// A French user gets `message_fr`; a refusal nobody has translated yet falls back to the English.
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  // A proxy's 413 is an HTML page, so its only wording is the English status text.
  if (response.status === 413) {
    return fixedError(413, "PAYLOAD_TOO_LARGE", TOO_LARGE);
  }
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  if (Array.isArray(detail)) {
    return fixedError(response.status, "VALIDATION_ERROR", VALIDATION_FAILED);
  }
  if (typeof detail === "object" && detail !== null) {
    const english = typeof detail.message === "string" ? detail.message : response.statusText;
    const french = typeof detail.message_fr === "string" && detail.message_fr ? detail.message_fr : null;
    const shown = readStoredLanguage() === "fr" && french ? french : english;
    return new ApiError(response.status, typeof detail.code === "string" ? detail.code : "UNKNOWN", shown, english);
  }
  return new ApiError(response.status, "UNKNOWN", typeof detail === "string" ? detail : response.statusText);
}

// No response at all (server down or restarting, network lost). Status 0 is not a 401,
// so this never logs the user out.
export function networkError(): ApiError {
  return fixedError(0, "NETWORK_ERROR", SERVER_UNREACHABLE);
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  // A FormData body (maintenance's multipart endpoints: view/checkpoint images,
  // check-entry photos) must go through untouched — stringifying it would send
  // "[object FormData]", and setting our own Content-Type would drop the
  // multipart boundary the browser computes. JSON callers are unaffected.
  const isFormData = options.body instanceof FormData;
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      },
      body: options.body === undefined ? undefined : isFormData ? (options.body as FormData) : JSON.stringify(options.body),
    });
  } catch {
    throw networkError();
  }

  if (!response.ok) {
    if (response.status === 401) {
      // Told AuthProvider directly rather than importing it here — api.ts
      // has no business knowing about session state, only HTTP.
      window.dispatchEvent(new Event("auth:unauthorized"));
    }
    throw await apiErrorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
