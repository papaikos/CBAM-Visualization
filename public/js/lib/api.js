/** Small fetch helpers shared by every page. */

export function createApiUrl(path, params = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

export async function responseError(response, fallback = "The request could not be completed.") {
  try {
    const payload = await response.json();
    return payload.message || fallback;
  } catch {
    return fallback;
  }
}

export async function fetchJson(path, params = {}) {
  const response = await fetch(createApiUrl(path, params));
  if (!response.ok) {
    throw new Error(await responseError(response, `Request failed: ${response.status}`));
  }
  return response.json();
}

export async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response;
}

export function filenameFromResponse(response, fallback) {
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  return match ? match[1] : fallback;
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
