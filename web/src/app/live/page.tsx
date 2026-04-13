"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useSource } from "@/lib/source-context";
import { api, SOURCE_META, Entry } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Radio, Loader2, ArrowDown } from "lucide-react";

export default function LivePage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const [entries, setEntries] = useState<Entry[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevCountRef = useRef(0);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  // Handle scroll — disable auto-scroll if user scrolls up
  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 80;
    setAutoScroll(isNearBottom);
  }, []);

  const fetchEntries = useCallback(async () => {
    try {
      const r = await api.latest({ source, limit: 20 });
      const newEntries = (r.entries || []).reverse(); // oldest first
      setEntries(newEntries);
      setConnected(true);

      // Auto-scroll on new entries
      if (newEntries.length !== prevCountRef.current) {
        prevCountRef.current = newEntries.length;
        if (autoScroll) {
          // Use requestAnimationFrame to ensure DOM has updated
          requestAnimationFrame(() => scrollToBottom());
        }
      }
    } catch {
      setConnected(false);
    } finally {
      setLoading(false);
    }
  }, [source, autoScroll, scrollToBottom]);

  // Initial fetch
  useEffect(() => {
    setLoading(true);
    prevCountRef.current = 0;
    fetchEntries();
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll every 3 seconds
  useEffect(() => {
    const interval = setInterval(fetchEntries, 3000);
    return () => clearInterval(interval);
  }, [fetchEntries]);

  const roleBadgeClass = (role: string) => {
    switch (role) {
      case "user":
        return "border-green-500/30 text-green-400";
      case "assistant":
        return "border-blue-500/30 text-blue-400";
      default:
        return "border-yellow-500/30 text-yellow-400";
    }
  };

  return (
    <div className="p-6 flex flex-col h-[calc(100vh-0px)]">
      {/* Header */}
      <div className="shrink-0 mb-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Radio className="h-6 w-6" />
              Live View
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
              <span
                className="inline-block h-2 w-2 rounded-full animate-pulse"
                style={{ backgroundColor: meta.color }}
              />
              {meta.label} workspace
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div
              className={`h-2 w-2 rounded-full ${
                connected ? "bg-green-500 animate-pulse" : "bg-red-500"
              }`}
            />
            <span className="text-xs text-muted-foreground">
              {connected ? "Connected" : "Disconnected"}
            </span>
          </div>
        </div>
      </div>

      {/* Live Feed */}
      <Card className="flex-1 flex flex-col min-h-0">
        <CardHeader className="pb-2 shrink-0">
          <div className="flex items-center justify-between">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Live Feed
            </CardTitle>
            <span className="text-[10px] text-muted-foreground">
              {entries.length} entries &middot; polling every 3s
            </span>
          </div>
        </CardHeader>
        <CardContent className="flex-1 min-h-0 pt-0 pb-3 px-3 relative">
          {loading ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Connecting...</p>
            </div>
          ) : entries.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <Radio className="h-10 w-10 text-muted-foreground/20" />
              <p className="text-sm text-muted-foreground">
                No entries yet. Waiting for activity...
              </p>
            </div>
          ) : (
            <>
              <div
                ref={scrollRef}
                onScroll={handleScroll}
                className="h-full overflow-y-auto space-y-2 pr-1"
              >
                {entries.map((entry, i) => (
                  <div
                    key={`${entry.id}-${i}`}
                    className="rounded-md border bg-muted/30 p-3 animate-in fade-in duration-300"
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Badge
                        variant="outline"
                        className={`${roleBadgeClass(entry.role)} text-[10px]`}
                      >
                        {entry.role}
                      </Badge>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {entry.timestamp?.slice(11, 19) || ""}
                      </span>
                      {entry.session_id && (
                        <span className="text-[10px] text-muted-foreground/50 font-mono ml-auto">
                          {entry.session_id.slice(0, 8)}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words">
                      {entry.content?.slice(0, 500)}
                      {entry.content && entry.content.length > 500 ? "..." : ""}
                    </p>
                  </div>
                ))}
              </div>

              {/* Scroll-to-bottom button */}
              {!autoScroll && (
                <button
                  onClick={() => {
                    setAutoScroll(true);
                    scrollToBottom();
                  }}
                  className="absolute bottom-4 right-4 rounded-full bg-primary p-2 text-primary-foreground shadow-lg hover:bg-primary/90 transition-colors"
                  title="Scroll to bottom"
                >
                  <ArrowDown className="h-4 w-4" />
                </button>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
