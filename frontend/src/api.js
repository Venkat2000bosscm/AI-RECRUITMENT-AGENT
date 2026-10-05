const USER_KEY = "recruit.userId";

export const getUserId = () => localStorage.getItem(USER_KEY) || "1";
export const setUserId = (id) => localStorage.setItem(USER_KEY, String(id));

async function request(method, path, body, isForm = false) {
  const headers = { "X-User-Id": getUserId() };
  if (body && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail || res.statusText));
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b || {}),
  patch: (p, b) => request("PATCH", p, b),
  upload: (p, form) => request("POST", p, form, true),
};
