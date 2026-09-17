export const API_BASE = "/api/v1/dashboard";

export class ApiError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(status: number, path: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, params?: Params): string {
  const url = `${API_BASE}${path}`;
  if (!params) return url;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `${url}?${text}` : url;
}

/** GET a JSON payload; throws ApiError with the server's message on a non-2xx. */
export async function fetchJson<T>(path: string, params?: Params, signal?: AbortSignal): Promise<T> {
  const url = buildUrl(path, params);
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { message?: string; detail?: string };
      message = body.message ?? body.detail ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, url, message);
  }
  return (await response.json()) as T;
}
