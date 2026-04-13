"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, Entry } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ArrowLeft,
  Hash,
  Calendar,
  Loader2,
  MessageSquare,
  User,
  Bot,
  Download,
  Check,
} from "lucide-react";
import Link from "next/link";

export default function SessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;

  const [entries, setEntries] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    api
      .session(sessionId)
      .then((r) => {
        setEntries(r.entries || []);
        setTotal(r.total || 0);
      })
      .catch((err) => {
        setError(err.message || "Failed to load session");
        setEntries([]);
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleExport = async () => {
    if (!sessionId) return;
    setExporting(true);
    setExportResult(null);
    try {
      const res = await api.exportSession(sessionId);
      if (res.ok) {
        setExportResult(res.path);
      } else {
        setExportResult(`Error: ${res.error || "Export failed"}`);
      }
    } catch (err) {
      setExportResult("Export failed — is the backend running?");
    } finally {
      setExporting(false);
    }
  };

  const shortId = sessionId?.slice(0, 8) || "";

  // Derive date range from entries
  const timestamps = entries
    .map((e) => e.timestamp)
    .filter(Boolean)
    .sort();
  const dateStart = timestamps[0]?.slice(0, 19) || null;
  const dateEnd = timestamps[timestamps.length - 1]?.slice(0, 19) || null;

  const roleBadge = (role: string) => {
    switch (role) {
      case "user":
        return (
          <Badge
            variant="outline"
            className="border-green-500/30 text-green-400 text-[10px]"
          >
            <User className="h-2.5 w-2.5 mr-1" />
            user
          </Badge>
        );
      case "assistant":
        return (
          <Badge
            variant="outline"
            className="border-blue-500/30 text-blue-400 text-[10px]"
          >
            <Bot className="h-2.5 w-2.5 mr-1" />
            assistant
          </Badge>
        );
      default:
        return (
          <Badge
            variant="outline"
            className="border-yellow-500/30 text-yellow-400 text-[10px]"
          >
            {role}
          </Badge>
        );
    }
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/sessions"
          className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1 mb-2 transition-colors"
        >
          <ArrowLeft className="h-3 w-3" />
          Back to Sessions
        </Link>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <MessageSquare className="h-5 w-5 text-muted-foreground" />
            Session{" "}
            <code className="text-primary font-mono">{shortId}</code>
          </h1>
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={exporting || loading}
            className="gap-2"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : exportResult && !exportResult.startsWith("Error") ? (
              <Check className="h-4 w-4 text-green-400" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {exporting ? "Exporting..." : "Export JSON"}
          </Button>
        </div>
        {exportResult && (
          <p className={`text-xs mt-1 ${exportResult.startsWith("Error") ? "text-red-400" : "text-green-400"}`}>
            {exportResult.startsWith("Error") ? exportResult : `Exported to ${exportResult}`}
          </p>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="text-sm text-red-400">{error}</p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Session stats */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardContent className="p-4 flex items-center gap-3">
                <Hash className="h-5 w-5 text-blue-400 opacity-60" />
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Entries
                  </p>
                  <p className="text-lg font-bold">{total}</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4 flex items-center gap-3">
                <Calendar className="h-5 w-5 text-green-400 opacity-60" />
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Started
                  </p>
                  <p className="text-sm font-mono">
                    {dateStart || "unknown"}
                  </p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4 flex items-center gap-3">
                <Calendar className="h-5 w-5 text-purple-400 opacity-60" />
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Latest
                  </p>
                  <p className="text-sm font-mono">
                    {dateEnd || "unknown"}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Conversation */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Conversation
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-3">
              {entries.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  No entries in this session.
                </p>
              ) : (
                entries.map((entry, i) => {
                  const isUser = entry.role === "user";
                  const isAssistant = entry.role === "assistant";
                  return (
                    <div
                      key={i}
                      className={`flex ${isAssistant ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`rounded-lg border p-3 max-w-[85%] ${
                          isUser
                            ? "bg-green-500/5 border-green-500/20"
                            : isAssistant
                            ? "bg-blue-500/5 border-blue-500/20"
                            : "bg-yellow-500/5 border-yellow-500/20"
                        }`}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          {roleBadge(entry.role)}
                          <span className="text-[10px] text-muted-foreground">
                            {entry.timestamp?.slice(0, 19)}
                          </span>
                          {entry.source_line != null && (
                            <span className="text-[10px] text-muted-foreground/50">
                              line {entry.source_line}
                            </span>
                          )}
                        </div>
                        <pre className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words">
                          {entry.content}
                        </pre>
                      </div>
                    </div>
                  );
                })
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
