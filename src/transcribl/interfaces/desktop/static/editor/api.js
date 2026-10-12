
export function getCookie(name) {
  const prefix = `${name}=`;
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (!cookie) {
    return "";
  }
  try {
    return decodeURIComponent(cookie.slice(prefix.length));
  } catch {
    return cookie.slice(prefix.length);
  }
}

export function errorMessageFromPayload(payload, status) {
  const detail = payload?.detail ?? payload?.error ?? payload?.message;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (typeof entry?.msg === "string" ? entry.msg : null))
      .filter(Boolean);
    if (messages.length) {
      return messages.join(" ");
    }
  }
  if (status === 409) {
    return "This document changed since it was loaded. Refresh the review and try again.";
  }
  if (status === 413) {
    return "This PDF is larger than the configured upload limit.";
  }
  return `The request could not be completed (HTTP ${status}).`;
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-CSRF-Token", getCookie("at_csrf"));
  }

  let response;
  try {
    response = await fetch(`/backend${path}`, {
      ...options,
      method,
      headers,
      credentials: "same-origin",
    });
  } catch {
    throw new Error("Transcribl could not reach the local server.");
  }

  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json")) {
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    throw new Error(errorMessageFromPayload(payload, response.status));
  }
  return payload;
}
