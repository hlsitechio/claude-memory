const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

export type Source = "claude_code" | "copilot" | "codex";

export const SOURCE_META: Record<Source, { label: string; color: string; icon: string }> = {
  claude_code: { label: "Claude Code", color: "#58a6ff", icon: "terminal" },
  copilot: { label: "Copilot CLI", color: "#3fb950", icon: "github" },
  codex: { label: "Codex CLI", color: "#d29922", icon: "bot" },
};

export interface Entry {
  id?: number;
  content: string;
  role: string;
  session_id: string;
  timestamp: string;
  source?: string;
  source_line?: number;
  similarity?: number;
}

export interface Session {
  id: string;
  status: string;
  started_at: string;
  ended_at: string;
  entries: number;
  source?: string;
}

export interface DetectResponse {
  python_path: string;
  python_found: boolean;
  mcp_server_path: string;
  mcp_server_found: boolean;
  jsonl_dir: string;
  jsonl_dir_found: boolean;
  jsonl_count: number;
  db_path: string;
  db_exists: boolean;
}

async function fetchJson<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v) url.searchParams.set(k, v);
    });
  }
  const res = await fetch(url.toString(), { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  // Stats — backend returns {entries, sessions, by_role}
  stats: async () => {
    const raw = await fetchJson<{ entries: number; sessions: number; by_role: Record<string, number> }>("/api/stats");
    return {
      entries: raw.entries || 0,
      sessions_done: raw.sessions || 0,
      sessions_total: raw.sessions || 0,
      knowledge: 0,
      by_role: raw.by_role || {},
    };
  },

  // Search — backend returns raw array of entries
  search: async (q: string, opts?: { source?: string; role?: string; limit?: number }) => {
    const results = await fetchJson<Entry[]>("/api/search", {
      q,
      source: opts?.source || "",
      role: opts?.role || "",
      limit: String(opts?.limit || 20),
    });
    return { results: Array.isArray(results) ? results : [], total: Array.isArray(results) ? results.length : 0 };
  },

  // Latest — backend returns raw array of entries
  latest: async (opts?: { source?: string; role?: string; limit?: number }) => {
    const entries = await fetchJson<Entry[]>("/api/latest", {
      source: opts?.source || "",
      role: opts?.role || "",
      limit: String(opts?.limit || 20),
    });
    return { entries: Array.isArray(entries) ? entries : [], total: Array.isArray(entries) ? entries.length : 0 };
  },

  // Sessions — backend returns {sessions: [...], total}
  sessions: async (opts?: { source?: string; limit?: number; query?: string }) => {
    const raw = await fetchJson<{ sessions: Session[]; total: number }>("/api/sessions", {
      source: opts?.source || "",
      limit: String(opts?.limit || 20),
      q: opts?.query || "",
    });
    return { sessions: raw.sessions || [], total: raw.total || 0 };
  },

  // Session detail — backend returns {entries: [...], total_entries, session_id}
  session: async (id: string) => {
    const raw = await fetchJson<{ entries: Entry[]; total_entries: number; session_id: string }>("/api/session", { id });
    return { entries: raw.entries || [], total: raw.total_entries || 0, session_id: raw.session_id || id };
  },

  // Semantic — backend returns {results: [...], count} or {error}
  semantic: async (q: string, opts?: { source?: string; n?: number; mode?: string }) => {
    try {
      const raw = await fetchJson<{ results?: Entry[]; count?: number; error?: string }>("/api/semantic", {
        q,
        source: opts?.source || "",
        n: String(opts?.n || 10),
        mode: opts?.mode || "hybrid",
      });
      if (raw.error) return { results: [], count: 0, error: raw.error };
      return { results: raw.results || [], count: raw.count || 0 };
    } catch {
      return { results: [], count: 0, error: "Semantic search unavailable" };
    }
  },

  // Setup detect
  detect: () => fetchJson<DetectResponse>("/api/setup/detect"),

  // Setup test
  testConnection: (db?: string) => fetchJson<{ ok: boolean; tables?: number; entries?: number; error?: string }>("/api/setup/test", db ? { db } : {}),

  // Setup config
  getConfig: (tool: string, opts?: { python?: string; mcp_server?: string; db?: string }) =>
    fetchJson<{ config: Record<string, unknown>; real_path: string; display_path: string }>("/api/setup/config", {
      tool,
      python: opts?.python || "",
      mcp_server: opts?.mcp_server || "",
      db: opts?.db || "",
    }),

  // Setup install
  installConfig: async (data: { config: Record<string, unknown>; real_path: string }) => {
    const res = await fetch("/api/setup/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return res.json();
  },

  // Setup ingest
  runIngest: async () => {
    const res = await fetch("/api/setup/ingest", { method: "POST" });
    return res.json();
  },

  // Export session to disk as JSON
  exportSession: async (id: string, dir?: string) => {
    return fetchJson<{ ok: boolean; path: string; session_id: string; date: string; entries: number; error?: string }>(
      "/api/export",
      { id, ...(dir ? { dir } : {}) }
    );
  },
};
