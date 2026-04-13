"use client";

import { useEffect, useState, useRef } from "react";
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
  Wrench,
  ChevronDown,
  ChevronRight,
  Map,
  Zap,
} from "lucide-react";
import Link from "next/link";

interface Segment {
  index: number;
  title: string;
  start_line: number;
  start_entry_id: number;
  timestamp: string;
  entries: number;
  tool_calls: number;
  assistant_chars: number;
}

interface Digest {
  stats: {
    total_entries: number;
    by_role: Record<string, number>;
    tool_calls: number;
    total_chars: number;
    time_start: string;
    time_end: string;
  };
  segments: Segment[];
  segment_count: number;
  key_moments: { source_line: number; preview: string; length: number; timestamp: string }[];
}

export default function SessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;

  const [entries, setEntries] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [showToc, setShowToc] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [collapsedToolGroups, setCollapsedToolGroups] = useState(new Set<number>());
  const entryRefs = useRef<Record<number, HTMLDivElement>>({});

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);

    Promise.all([
      api.session(sessionId),
      api.digest(sessionId).catch(() => null),
    ])
      .then(([sessionData, digestData]) => {
        setEntries(sessionData.entries || []);
        setTotal(sessionData.total || 0);
        if (digestData) setDigest(digestData);
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
    } catch {
      setExportResult("Export failed — is the backend running?");
    } finally {
      setExporting(false);
    }
  };

  const scrollToLine = (line: number) => {
    const el = entryRefs.current[line];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      el.classList.add("ring-2", "ring-primary/50");
      setTimeout(() => el.classList.remove("ring-2", "ring-primary/50"), 2000);
    }
  };

  const shortId = sessionId?.slice(0, 8) || "";

  // Classify entries
  const isTool = (content: string) =>
    content.startsWith("[TOOL:") || content.startsWith('{"result":');

  const getToolName = (content: string) => {
    if (content.startsWith("[TOOL:")) {
      const end = content.indexOf("]");
      if (end > 0) return content.slice(6, end);
    }
    return "result";
  };

  // Group consecutive tool entries
  type DisplayItem =
    | { type: "entry"; entry: Entry; index: number }
    | { type: "tool-group"; entries: Entry[]; startIndex: number };

  const displayItems: DisplayItem[] = [];
  let toolBuffer: Entry[] = [];
  let toolStartIdx = 0;

  entries.forEach((entry, i) => {
    if (isTool(entry.content)) {
      if (toolBuffer.length === 0) toolStartIdx = i;
      toolBuffer.push(entry);
    } else {
      if (toolBuffer.length > 0) {
        displayItems.push({ type: "tool-group", entries: [...toolBuffer], startIndex: toolStartIdx });
        toolBuffer = [];
      }
      displayItems.push({ type: "entry", entry, index: i });
    }
  });
  if (toolBuffer.length > 0) {
    displayItems.push({ type: "tool-group", entries: [...toolBuffer], startIndex: toolStartIdx });
  }

  const roleBadge = (role: string) => {
    switch (role) {
      case "user":
        return (
          <Badge variant="outline" className="border-green-500/30 text-green-400 text-[10px]">
            <User className="h-2.5 w-2.5 mr-1" />user
          </Badge>
        );
      case "assistant":
        return (
          <Badge variant="outline" className="border-blue-500/30 text-blue-400 text-[10px]">
            <Bot className="h-2.5 w-2.5 mr-1" />assistant
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="border-yellow-500/30 text-yellow-400 text-[10px]">
            {role}
          </Badge>
        );
    }
  };

  const toggleToolGroup = (idx: number) => {
    setCollapsedToolGroups((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
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
            Session <code className="text-primary font-mono">{shortId}</code>
          </h1>
          <div className="flex items-center gap-2">
            {digest && (
              <>
                <Button variant="outline" size="sm" onClick={() => setShowToc(!showToc)} className="gap-2">
                  <Map className="h-4 w-4" />
                  {showToc ? "Hide" : "Map"} ({digest.segment_count})
                </Button>
                <Button variant="outline" size="sm" onClick={() => setShowTools(!showTools)} className="gap-2">
                  <Wrench className="h-4 w-4" />
                  {showTools ? "Collapse" : "Expand"} Tools
                </Button>
              </>
            )}
            <Button variant="outline" size="sm" onClick={handleExport} disabled={exporting || loading} className="gap-2">
              {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : exportResult && !exportResult.startsWith("Error") ? <Check className="h-4 w-4 text-green-400" /> : <Download className="h-4 w-4" />}
              {exporting ? "Exporting..." : "Export"}
            </Button>
          </div>
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
        <Card><CardContent className="p-10 text-center"><p className="text-sm text-red-400">{error}</p></CardContent></Card>
      ) : (
        <>
          {/* Stats row */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <Card>
              <CardContent className="p-3 flex items-center gap-2">
                <Hash className="h-4 w-4 text-blue-400 opacity-60" />
                <div>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Entries</p>
                  <p className="text-base font-bold">{total}</p>
                </div>
              </CardContent>
            </Card>
            {digest && (
              <>
                <Card>
                  <CardContent className="p-3 flex items-center gap-2">
                    <Wrench className="h-4 w-4 text-yellow-400 opacity-60" />
                    <div>
                      <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Tool Calls</p>
                      <p className="text-base font-bold">{digest.stats.tool_calls}</p>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-3 flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-green-400 opacity-60" />
                    <div>
                      <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Turns</p>
                      <p className="text-base font-bold">{digest.segment_count}</p>
                    </div>
                  </CardContent>
                </Card>
              </>
            )}
            <Card>
              <CardContent className="p-3 flex items-center gap-2">
                <Calendar className="h-4 w-4 text-green-400 opacity-60" />
                <div>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Started</p>
                  <p className="text-[11px] font-mono">{digest?.stats.time_start?.slice(0, 16) || "?"}</p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-3 flex items-center gap-2">
                <Calendar className="h-4 w-4 text-purple-400 opacity-60" />
                <div>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">Ended</p>
                  <p className="text-[11px] font-mono">{digest?.stats.time_end?.slice(0, 16) || "?"}</p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Table of Contents */}
          {showToc && digest && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                  <Map className="h-3.5 w-3.5" /> Conversation Map — {digest.segment_count} turns
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0 max-h-[400px] overflow-y-auto">
                <div className="space-y-0.5">
                  {digest.segments.map((seg, i) => (
                    <button
                      key={i}
                      onClick={() => scrollToLine(seg.start_line)}
                      className="w-full text-left px-2 py-1 rounded hover:bg-muted/50 transition-colors flex items-center gap-2 text-[11px] group"
                    >
                      <span className="text-muted-foreground w-8 shrink-0">#{i + 1}</span>
                      <span className="text-primary/60 font-mono w-12 shrink-0">L{seg.start_line}</span>
                      <span className="truncate text-foreground/80 group-hover:text-foreground">{seg.title}</span>
                      {seg.tool_calls > 0 && (
                        <Badge variant="outline" className="ml-auto shrink-0 text-[9px] border-yellow-500/30 text-yellow-500">
                          {seg.tool_calls} tools
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Key moments */}
          {showToc && digest && digest.key_moments.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                  <Zap className="h-3.5 w-3.5" /> Key Moments — longest responses
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="space-y-1">
                  {digest.key_moments.slice(0, 5).map((km, i) => (
                    <button
                      key={i}
                      onClick={() => scrollToLine(km.source_line)}
                      className="w-full text-left px-2 py-1.5 rounded hover:bg-muted/50 transition-colors flex items-center gap-2 text-[11px]"
                    >
                      <span className="text-primary/60 font-mono w-12 shrink-0">L{km.source_line}</span>
                      <span className="text-muted-foreground w-16 shrink-0">{(km.length / 1000).toFixed(1)}k chars</span>
                      <span className="truncate text-foreground/70">{km.preview}</span>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Conversation */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Conversation
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-3">
              {displayItems.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">No entries in this session.</p>
              ) : (
                displayItems.map((item, di) => {
                  if (item.type === "tool-group") {
                    const toolEntries = item.entries;
                    const names = [...new Set(toolEntries.map((e) => getToolName(e.content)))];
                    const label = names.slice(0, 4).join(", ") + (names.length > 4 ? ` +${names.length - 4}` : "");
                    const isOpen = showTools || collapsedToolGroups.has(item.startIndex);

                    return (
                      <div key={`tg-${di}`} className="border border-yellow-500/10 rounded-lg bg-yellow-500/[0.02]">
                        <button
                          className="w-full flex items-center gap-2 px-3 py-2 text-[11px] text-yellow-500/70 hover:text-yellow-400 transition-colors"
                          onClick={() => toggleToolGroup(item.startIndex)}
                        >
                          {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                          <Wrench className="h-3 w-3" />
                          <span>{toolEntries.length} tool call{toolEntries.length > 1 ? "s" : ""}: {label}</span>
                        </button>
                        {isOpen && (
                          <div className="px-3 pb-2 space-y-1">
                            {toolEntries.map((te, ti) => (
                              <div
                                key={ti}
                                ref={(el) => { if (el && te.source_line != null) entryRefs.current[te.source_line] = el; }}
                                className="text-[10px] text-muted-foreground border-l-2 border-yellow-500/20 pl-2"
                              >
                                <span className="text-muted-foreground/50">{te.timestamp?.slice(11, 19)} L{te.source_line}</span>
                                <pre className="whitespace-pre-wrap break-words mt-0.5 max-h-32 overflow-y-auto">{te.content.slice(0, 500)}{te.content.length > 500 ? "…" : ""}</pre>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  }

                  const entry = item.entry;
                  const isUser = entry.role === "user";
                  const isAssistant = entry.role === "assistant";

                  return (
                    <div
                      key={`e-${di}`}
                      ref={(el) => { if (el && entry.source_line != null) entryRefs.current[entry.source_line] = el; }}
                      id={`L${entry.source_line}`}
                      className={`flex ${isAssistant ? "justify-end" : "justify-start"} transition-all`}
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
                          <span className="text-[10px] text-muted-foreground">{entry.timestamp?.slice(0, 19)}</span>
                          {entry.source_line != null && (
                            <span className="text-[10px] text-muted-foreground/50">L{entry.source_line}</span>
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
