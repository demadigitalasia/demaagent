// Klien API untuk aplikasi mandiri Mission Control.
// Fetch same-origin (cookie sesi HttpOnly dikirim otomatis).
// 401 -> AuthError (root menampilkan halaman login).

export class AuthError extends Error {
  constructor() {
    super("unauthorized");
    this.name = "AuthError";
  }
}

async function toError(res) {
  let msg = `HTTP ${res.status}`;
  try {
    const j = await res.json();
    if (j && j.error) msg = j.error;
    else if (j && j.message) msg = j.message;
  } catch {
    /* body bukan JSON — pakai pesan HTTP */
  }
  return new Error(msg);
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCsrfToken() {
  if (typeof document === "undefined" || !document.cookie) return "";
  const prefix = "mc_csrf=";
  const row = document.cookie.split(";").map((item) => item.trim())
    .find((item) => item.startsWith(prefix));
  if (!row) return "";
  try {
    return decodeURIComponent(row.slice(prefix.length));
  } catch {
    return row.slice(prefix.length);
  }
}

function withCsrf(init = {}) {
  const method = String(init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers || {});
  if (UNSAFE_METHODS.has(method) && !headers.has("X-CSRF-Token")) {
    const token = readCsrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  return { credentials: "same-origin", ...init, headers };
}

export async function apiFetch(url, init = {}) {
  const res = await fetch(url, withCsrf(init));
  if (res.status === 401) throw new AuthError();
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function apiLogin(username, password) {
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    credentials: "same-origin",
  });
  if (res.status === 401) throw new Error("Kredensial salah.");
  if (!res.ok) throw await toError(res);
  return res.json();
}

export async function apiLogout() {
  try {
    await fetch("/auth/logout", withCsrf({ method: "POST" }));
  } catch {
    /* abaikan — cookie sisi server dihapus saat request sampai */
  }
}