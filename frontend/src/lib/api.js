const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const API_KEY = import.meta.env.VITE_API_KEY || "";

function authHeaders(extra = {}) {
  return API_KEY ? { "X-API-Key": API_KEY, ...extra } : extra;
}

// FastAPI returns `detail` as a string, or as a list of validation problems.
function formatDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && d.msg ? `${(d.loc || []).slice(1).join(".")}: ${d.msg}` : String(d))).join("; ");
  }
  return typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : "";
}

async function asJson(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = formatDetail(body.detail) || detail;
    } catch {
      /* non-json error body */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function uploadDocument(file, sessionId) {
  const form = new FormData();
  form.append("file", file);
  form.append("session_id", sessionId);
  const res = await fetch(`${API_URL}/upload`, {
    method: "POST",
    body: form,
    headers: authHeaders(),
  });
  return asJson(res);
}

export async function fetchDocuments(sessionId) {
  const res = await fetch(`${API_URL}/documents?session_id=${encodeURIComponent(sessionId)}`, { headers: authHeaders() });
  return asJson(res);
}

export async function deleteDocument(filename, sessionId) {
  const res = await fetch(
    `${API_URL}/documents/${encodeURIComponent(filename)}?session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE", headers: authHeaders() }
  );
  return asJson(res);
}

const AGENT_TIMEOUT_MS = 100000;

export async function sendAgentMessage({ message, filename, sessionId, mode = "", history = [], resetQuiz = false }) {
  let res;
  try {
    res = await fetch(`${API_URL}/agent`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    signal: AbortSignal.timeout(AGENT_TIMEOUT_MS),
    body: JSON.stringify({
      message,
      filename,
      session_id: sessionId,
      mode,
      history,
      reset_quiz: resetQuiz,
    }),
    });
  } catch (err) {
    if (err && (err.name === "TimeoutError" || err.name === "AbortError")) {
      throw new Error("The tutor took too long to answer. Please try again.");
    }
    throw new Error("Could not reach the tutor. Check that the backend is running.");
  }
  return asJson(res);
}

export async function fetchChatHistory(filename, sessionId) {
  const res = await fetch(
    `${API_URL}/chat/history?session_id=${encodeURIComponent(sessionId)}&filename=${encodeURIComponent(filename)}`,
    { headers: authHeaders() }
  );
  return asJson(res);
}

export async function fetchDashboard(filename, sessionId) {
  const res = await fetch(
    `${API_URL}/dashboard?session_id=${encodeURIComponent(sessionId)}&filename=${encodeURIComponent(filename)}`,
    { headers: authHeaders() }
  );
  return asJson(res);
}

export async function resetQuiz(filename, sessionId) {
  const res = await fetch(
    `${API_URL}/quiz/reset?session_id=${encodeURIComponent(sessionId)}&filename=${encodeURIComponent(filename)}`,
    { method: "POST", headers: authHeaders() }
  );
  return asJson(res);
}

export async function fetchEvaluation(password) {
  const res = await fetch(`${API_URL}/evaluation`, { headers: authHeaders({ "X-Benchmark-Password": password }) });
  return asJson(res);
}

export { API_URL };
