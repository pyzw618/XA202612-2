const API_BASE = process.env.NEXT_PUBLIC_MEMORYHUB_API || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, public status = 0) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError("MemoryHub 后端未连接");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})`;
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const memoryApi = {
  step: (body: unknown) => api<Record<string, unknown>>("/api/agent/step", { method: "POST", body: JSON.stringify(body) }),
  replay: (body: unknown) => api<Record<string, unknown>>("/api/agent/replay", { method: "POST", body: JSON.stringify(body) }),
  decide: (id: string, body: unknown) => api<Record<string, unknown>>(`/api/agent/actions/${id}/decision`, { method: "POST", body: JSON.stringify(body) }),
  search: (query: string) => api<Record<string, unknown>>("/api/memory/search", { method: "POST", body: JSON.stringify({ user_id: "default", query, context: {}, top_k: 8, memory_types: ["preference", "knowledge"] }) }),
  preferences: () => api<unknown[]>("/api/memory/preferences?user_id=default"),
  facts: () => api<unknown[]>("/api/memory/facts"),
  knowledge: (type: "workflow" | "template") => api<unknown[]>(`/api/memory/knowledge?user_id=default&knowledge_type=${type}`),
  conflicts: () => api<unknown[]>("/api/memory/conflicts?status=pending"),
  forgetPreview: (instruction: string) => api<Record<string, unknown>>("/api/memory/forget/preview", { method: "POST", body: JSON.stringify({ user_id: "default", instruction }) }),
  forgetHistory: () => api<unknown[]>("/api/memory/forget/history?user_id=default"),
};
