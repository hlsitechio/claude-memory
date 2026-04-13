"use client";

import { Suspense, useEffect, useState, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
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
import { Search, Loader2, Inbox } from "lucide-react";

const ROLE_OPTIONS = [
  { value: "__all__", label: "All Roles" },
  { value: "user", label: "User" },
  { value: "assistant", label: "Assistant" },
  { value: "system", label: "System" },
] as const;

const DAYS_OPTIONS = [
  { value: "__all__", label: "All Time" },
  { value: "1", label: "Today" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
] as const;

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

function SearchPageInner() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialQuery = searchParams.get("q") || "";
  const [query, setQuery] = useState(initialQuery);
  const [role, setRole] = useState("__all__");
  const [days, setDays] = useState("__all__");
  const [results, setResults] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const performSearch = useCallback(
    async (q: string) => {
      setLoading(true);
      setError(null);
      try {
        const roleFilter = role === "__all__" ? undefined : role;
        if (q.trim()) {
          const data = await api.search(q, {
            source,
            role: roleFilter,
            limit: 30,
          });
          setResults(data.results || []);
          setTotal(data.total || 0);
          setHasSearched(true);
        } else {
          const data = await api.latest({
            source,
            role: roleFilter,
            limit: 30,
          });
          setResults(data.entries || []);
          setTotal(data.total || 0);
          setHasSearched(true);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch results");
        setResults([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [source, role]
  );

  // Run search on mount if query param exists, and when filters change
  useEffect(() => {
    performSearch(query);
  }, [performSearch, query]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    router.replace(`/search${params.toString() ? `?${params}` : ""}`);
    performSearch(query);
  }

  // Filter by days client-side (the API may not support a date filter directly)
  const filteredResults =
    days === "__all__"
      ? results
      : results.filter((entry) => {
          if (!entry.timestamp) return true;
          const entryDate = new Date(entry.timestamp);
          const cutoff = new Date();
          cutoff.setDate(cutoff.getDate() - Number(days));
          return entryDate >= cutoff;
        });

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Search</h1>
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
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9 h-10"
            placeholder="Search conversations, code, and knowledge..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </form>

      {/* Filters row */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={role} onValueChange={(v) => setRole(v ?? "__all__")}>
          <SelectTrigger className="w-[140px]" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROLE_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={days} onValueChange={(v) => setDays(v ?? "__all__")}>
          <SelectTrigger className="w-[140px]" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DAYS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasSearched && !loading && (
          <span className="text-xs text-muted-foreground ml-auto">
            {filteredResults.length} of {total} results
          </span>
        )}
      </div>

      {/* Results */}
      <div className="space-y-3">
        {loading && (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="ml-2 text-sm text-muted-foreground">Searching...</span>
          </div>
        )}

        {error && (
          <Card>
            <CardContent className="p-5">
              <p className="text-sm text-destructive">{error}</p>
            </CardContent>
          </Card>
        )}

        {!loading && !error && hasSearched && filteredResults.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <Inbox className="h-10 w-10 mb-3 opacity-40" />
            <p className="text-sm">No results found</p>
            <p className="text-xs mt-1">
              {query ? "Try adjusting your search or filters" : "No entries recorded yet"}
            </p>
          </div>
        )}

        {!loading &&
          !error &&
          filteredResults.map((entry, i) => (
            <Card key={`${entry.session_id}-${entry.timestamp}-${i}`}>
              <CardContent className="p-4">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
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

export default function SearchPage() {
  return (
    <Suspense fallback={<div className="p-6 text-muted-foreground">Loading...</div>}>
      <SearchPageInner />
    </Suspense>
  );
}
