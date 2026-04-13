export function getBase(): string {
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

export async function parseResponse<T>(res: Response, endpoint: string): Promise<T> {
  const json: unknown = await res.json();
  if (
    json !== null &&
    typeof json === "object" &&
    "status" in json &&
    (json as { status: unknown }).status === "error"
  ) {
    const msg =
      "message" in json
        ? String((json as { message: unknown }).message)
        : `FT API ${endpoint} error`;
    throw new Error(msg);
  }
  const data =
    json !== null && typeof json === "object" && "data" in json
      ? (json as { data: unknown }).data
      : json;
  return data as T;
}

export async function post<T>(endpoint: string, body: object = {}): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

export async function get<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

export async function put<T>(endpoint: string, body: object = {}): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}

export async function del<T>(endpoint: string): Promise<T> {
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`FT API ${endpoint}: HTTP ${resp.status}`);
  return parseResponse<T>(resp, endpoint);
}
