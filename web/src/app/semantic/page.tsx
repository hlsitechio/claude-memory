"use client";

import { useEffect, useState, useCallback } from "react";
import { useSource } from "@/lib/source-context";
import { api, SOURCE_META, Entry } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sparkles, Loader2, Inbox } from "lucide-react";

type SemanticResult = Entry & { similarity?: number };

const MODE_OPTIONS = [
  { value: "hybrid", label: "Hybrid" },
  { value: "semantic", label: "Semantic" },
  { value: "keyword", label: "Keyword" },
] as const;

const LIMIT_OPTIONS = [
  { value: "10", label: "10 results" },
  { value: "15", label: "15 results" },
  { value: "25", label: "25 results" },
] as const;

const EXAMPLE_QUERIES = [
  "How to fix build errors in TypeScript",
  "Database migration strategies",
  "Authentication flow implementation",
  "API rate limiting patterns",
  "Error handling best practices",
];

function roleBadgeClass(role: string): string {
  switch (role) {
    case "user":
      return "border-green-500/30 text-green-400 text-[10px]";
    case "assistant":
      return "border-blue-500/30 text-blue-400 text-[10px]";
    case "system":
      return "border-yellow-500/30 text-yellow-400 text-[10px]";
    default:
      return "text-[10px]";
  }
}

function similarityColor(score: number): string {
  if (score >= 0.8) return "border-emerald-500/40 text-emerald-400 bg-emerald-500/10";
  if (score >= 0.6) return "border-blue-500/40 text-blue-400 bg-blue-500/10";
  if (score >= 0.4) return "border-yellow-500/40 text-yellow-400 bg-yellow-500/10";
  return "border-zinc-500/40 text-zinc-400 bg-zinc-500/10";
}

function formatTimestamp(ts: string): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts.slice(0, 19);
  }
}

export default function SemanticPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("hybrid");
  const [limit, setLimit] = useState("10");
  const [results, setResults] = useState<SemanticResult[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const performSearch = useCallback(
    async (q: string) => {
      if (!q.trim()) {
        setResults([]);
        setCount(0);
        setHasSearched(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const data = await api.semantic(q, {
          source,
          n: Number(limit),
          mode,
        });
        setResults(data.results || []);
        setCount(data.count || 0);
        setHasSearched(true);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Semantic search failed");
        setResults([]);
        setCount(0);
      } finally {
        setLoading(false);
      }
    },
    [source, mode, limit]
  );

  // Re-run search when mode or limit changes (if there's a query)
  useEffect(() => {
    if (query.trim()) {
      performSearch(query);
    }
  }, [mode, limit]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    performSearch(query);
  }

  function handleExampleClick(example: string) {
    setQuery(example);
    performSearch(example);
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold">Semantic Search</h1>
          <Sparkles className="h-5 w-5 text-purple-400 opacity-60" />
        </div>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label} workspace
        </p>
      </div>

      {/* Search input */}
      <form onSubmit={handleSubmit}>
        <div className="relative">
          <Sparkles className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9 h-10"
            placeholder="Search by meaning..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </form>

      {/* Filters row */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={mode} onValueChange={(v) => setMode(v ?? "hybrid")}>
          <SelectTrigger className="w-[130px]" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MODE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={limit} onValueChange={(v) => setLimit(v ?? "10")}>
          <SelectTrigger className="w-[130px]" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {LIMIT_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasSearched && !loading && (
          <span className="text-xs text-muted-foreground ml-auto">
            {count} result{count !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Results */}
      <div className="space-y-3">
        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">
              Searching by meaning...
            </span>
          </div>
        )}

        {error && (
          <Card>
            <CardContent className="p-5">
              <p className="text-sm text-destructive">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* Empty state with example queries */}
        {!loading && !error && !hasSearched && (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Sparkles className="h-10 w-10 mb-4 opacity-30" />
            <p className="text-sm mb-1">Find entries by meaning, not just keywords</p>
            <p className="text-xs mb-6 text-muted-foreground/60">
              Try one of these example queries:
            </p>
            <div className="flex flex-col gap-1.5 w-full max-w-md">
              {EXAMPLE_QUERIES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => handleExampleClick(example)}
                  className="text-left rounded-md border border-border/50 px-3 py-2 text-xs text-foreground/70 hover:bg-muted hover:text-foreground transition-colors"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* No results after search */}
        {!loading && !error && hasSearched && results.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <Inbox className="h-10 w-10 mb-3 opacity-40" />
            <p className="text-sm">No semantic matches found</p>
            <p className="text-xs mt-1">Try rephrasing your query or switching modes</p>
          </div>
        )}

        {/* Result cards */}
        {!loading &&
          !error &&
          results.map((entry, i) => (
            <Card key={`${entry.session_id}-${entry.timestamp}-${i}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                  {entry.similarity != null && (
                    <Badge
                      variant="outline"
                      className={`text-[10px] font-mono ${similarityColor(entry.similarity)}`}
                    >
                      {(entry.similarity * 100).toFixed(1)}%
                    </Badge>
                  )}
                  <Badge variant="outline" className={roleBadgeClass(entry.role)}>
                    {entry.role}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground">
                    {formatTimestamp(entry.timestamp)}
                  </span>
                  {entry.session_id && (
                    <code className="text-[10px] text-muted-foreground/60 ml-auto">
                      {entry.session_id.slice(0, 12)}
                    </code>
                  )}
                </div>
                <p className="text-xs text-foreground/80 font-mono whitespace-pre-wrap leading-relaxed">
                  {entry.content?.slice(0, 300)}
                  {entry.content && entry.content.length > 300 && (
                    <span className="text-muted-foreground">...</span>
                  )}
                </p>
              </CardContent>
            </Card>
          ))}
      </div>
    </div>
  );
}
