"use client";

import { useEffect, useState } from "react";
import { useSource } from "@/lib/source-context";
import { api, SOURCE_META, Entry } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Database,
  MessageSquare,
  Calendar,
  Clock,
  Loader2,
} from "lucide-react";

export default function TimelinePage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const [stats, setStats] = useState({
    entries: 0,
    sessions: 0,
    sessionsTotal: 0,
  });
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);

    const statsPromise = api
      .stats()
      .then((s) =>
        setStats({
          entries: s.entries,
          sessions: s.sessions_done,
          sessionsTotal: s.sessions_total,
        })
      )
      .catch(() => {});

    const entriesPromise = api
      .latest({ source, limit: 30 })
      .then((r) => setEntries(r.entries || []))
      .catch(() => setEntries([]));

    Promise.all([statsPromise, entriesPromise]).finally(() =>
      setLoading(false)
    );
  }, [source]);

  // Derive date range from loaded entries
  const timestamps = entries
    .map((e) => e.timestamp)
    .filter(Boolean)
    .sort();
  const earliest = timestamps[0]?.slice(0, 10) || "--";
  const latest = timestamps[timestamps.length - 1]?.slice(0, 10) || "--";

  const statCards = [
    {
      label: "Total Entries",
      value: stats.entries.toLocaleString(),
      icon: Database,
      color: "text-blue-400",
    },
    {
      label: "Sessions Completed",
      value: stats.sessions.toLocaleString(),
      icon: MessageSquare,
      color: "text-green-400",
    },
    {
      label: "Sessions Total",
      value: stats.sessionsTotal.toLocaleString(),
      icon: MessageSquare,
      color: "text-purple-400",
    },
    {
      label: "Date Range",
      value: `${earliest} \u2014 ${latest}`,
      icon: Calendar,
      color: "text-yellow-400",
      small: true,
    },
  ];

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
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Timeline</h1>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label} workspace
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          {/* Stats row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {statCards.map((s) => (
              <Card key={s.label}>
                <CardContent className="p-5 flex items-center justify-between">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      {s.label}
                    </p>
                    <p
                      className={`mt-1 font-bold ${
                        s.small ? "text-sm" : "text-2xl"
                      }`}
                    >
                      {s.value}
                    </p>
                  </div>
                  <s.icon className={`h-8 w-8 ${s.color} opacity-40`} />
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Recent entries */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Recent Entries (Latest 30)
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-2">
              {entries.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  No entries yet.
                </p>
              ) : (
                entries.map((entry, i) => (
                  <div
                    key={i}
                    className="rounded-md border bg-muted/30 p-3"
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${roleBadgeClass(entry.role)}`}
                      >
                        {entry.role}
                      </Badge>
                      <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                        <Clock className="h-2.5 w-2.5" />
                        {entry.timestamp?.slice(0, 19)}
                      </span>
                      {entry.session_id && (
                        <span className="text-[10px] text-muted-foreground/50 font-mono">
                          session:{entry.session_id.slice(0, 8)}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-foreground/80 line-clamp-2 font-mono">
                      {entry.content?.slice(0, 300)}
                    </p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
