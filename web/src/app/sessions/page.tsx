"use client";

import { useEffect, useState } from "react";
import { useSource } from "@/lib/source-context";
import { api, SOURCE_META, Session } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  MessageSquare,
  Search,
  Calendar,
  Hash,
  Loader2,
  Download,
  Check,
} from "lucide-react";
import Link from "next/link";

export default function SessionsPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [exportedIds, setExportedIds] = useState<Set<string>>(new Set());

  const handleExport = async (e: React.MouseEvent, sessionId: string) => {
    e.preventDefault(); // Don't navigate to session detail
    e.stopPropagation();
    setExportingId(sessionId);
    try {
      const res = await api.exportSession(sessionId);
      if (res.ok) {
        setExportedIds((prev) => new Set(prev).add(sessionId));
      }
    } catch {
      // silently fail
    } finally {
      setExportingId(null);
    }
  };

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    setLoading(true);
    api
      .sessions({ source, limit: 50, query: debouncedQuery || undefined })
      .then((r) => {
        setSessions(r.sessions || []);
        setTotal(r.total || 0);
      })
      .catch(() => {
        setSessions([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [source, debouncedQuery]);

  const statusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "border-green-500/30 text-green-400";
      case "active":
        return "border-blue-500/30 text-blue-400";
      case "aborted":
        return "border-red-500/30 text-red-400";
      default:
        return "border-yellow-500/30 text-yellow-400";
    }
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Sessions</h1>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label} workspace
        </p>
      </div>

      {/* Search */}
      <Card>
        <CardContent className="p-5">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Filter sessions by content..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Results count */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {loading ? "Loading..." : `${total} session${total !== 1 ? "s" : ""} found`}
        </p>
      </div>

      {/* Session list */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : sessions.length === 0 ? (
        <Card>
          <CardContent className="p-10 text-center">
            <MessageSquare className="h-10 w-10 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">
              {debouncedQuery ? "No sessions match your search." : "No sessions yet."}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {sessions.map((s) => (
            <Link key={s.id} href={`/sessions/${s.id}`}>
              <Card className="hover:bg-muted/50 transition-colors cursor-pointer">
                <CardContent className="p-4 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <MessageSquare className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                    <div>
                      <div className="flex items-center gap-2">
                        <code className="text-sm font-mono text-primary">
                          {s.id.slice(0, 8)}
                        </code>
                        <Badge
                          variant="outline"
                          className={`text-[10px] ${statusColor(s.status)}`}
                        >
                          {s.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Hash className="h-3 w-3" />
                          {s.entries} entries
                        </span>
                        <span className="flex items-center gap-1">
                          <Calendar className="h-3 w-3" />
                          {s.started_at?.slice(0, 10) || "unknown"}
                        </span>
                        {s.ended_at && (
                          <span className="text-muted-foreground/60">
                            ended {s.ended_at.slice(0, 10)}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={(e) => handleExport(e, s.id)}
                      disabled={exportingId === s.id}
                      title="Export session as JSON"
                    >
                      {exportingId === s.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : exportedIds.has(s.id) ? (
                        <Check className="h-3.5 w-3.5 text-green-400" />
                      ) : (
                        <Download className="h-3.5 w-3.5" />
                      )}
                    </Button>
                    <span className="text-muted-foreground/40 text-xs">View</span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
