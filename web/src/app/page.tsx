"use client";

import { useEffect, useState } from "react";
import { useSource } from "@/lib/source-context";
import { api, SOURCE_META, Entry, Session } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Database,
  MessageSquare,
  BookOpen,
  Lightbulb,
  ArrowRight,
  Search,
  HardDrive,
  Activity,
  Clock,
  Radio,
} from "lucide-react";
import Link from "next/link";

export default function DashboardPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const [stats, setStats] = useState({ entries: 0, sessions: 0, knowledge: 0, observations: 0 });
  const [sessions, setSessions] = useState<Session[]>([]);
  const [latestEntries, setLatestEntries] = useState<Entry[]>([]);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    api.stats().then((s) =>
      setStats({ entries: s.entries, sessions: s.sessions_done, knowledge: s.knowledge, observations: 0 })
    ).catch(() => {});
    api.sessions({ source, limit: 6 }).then((s) => setSessions(s.sessions || [])).catch(() => {});
    api.latest({ source, limit: 5 }).then((r) => setLatestEntries(r.entries || [])).catch(() => {});
  }, [source]);

  const statCards = [
    { label: "Entries", value: stats.entries, icon: Database, color: "text-blue-400" },
    { label: "Sessions", value: stats.sessions, icon: MessageSquare, color: "text-green-400" },
    { label: "Knowledge", value: stats.knowledge, icon: BookOpen, color: "text-purple-400" },
    { label: "Observations", value: stats.observations, icon: Lightbulb, color: "text-yellow-400" },
  ];

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} />
          {meta.label} workspace
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((s) => (
          <Card key={s.label}>
            <CardContent className="p-5 flex items-center justify-between">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{s.label}</p>
                <p className="text-2xl font-bold mt-1">{s.value.toLocaleString()}</p>
              </div>
              <s.icon className={`h-8 w-8 ${s.color} opacity-40`} />
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2/3 */}
        <div className="lg:col-span-2 space-y-6">
          {/* Quick search */}
          <Card>
            <CardContent className="p-5">
              <form onSubmit={(e) => { e.preventDefault(); if (searchQuery) window.location.href = `/search?q=${encodeURIComponent(searchQuery)}`; }}>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input className="pl-9" placeholder="Search conversations..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
                </div>
              </form>
            </CardContent>
          </Card>

          {/* Recent sessions */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Recent Sessions</CardTitle>
                <Link href="/sessions" className="text-xs text-primary hover:underline flex items-center gap-1">View all <ArrowRight className="h-3 w-3" /></Link>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {sessions.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">No sessions yet.</p>
              ) : (
                <div className="space-y-0.5">
                  {sessions.map((s) => (
                    <Link key={s.id} href={`/sessions/${s.id}`} className="flex items-center justify-between rounded-md px-3 py-2 text-sm hover:bg-muted transition-colors">
                      <div className="flex items-center gap-2.5">
                        <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                        <code className="text-xs text-primary">{s.id.slice(0, 8)}...</code>
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                        <span>{s.entries} entries</span>
                        <span>{s.started_at?.slice(0, 10) || ""}</span>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Latest activity */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Latest Activity</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-2">
              {latestEntries.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">No entries yet.</p>
              ) : (
                latestEntries.map((e, i) => (
                  <div key={i} className="rounded-md border bg-muted/30 p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <Badge variant="outline" className={
                        e.role === "user" ? "border-green-500/30 text-green-400 text-[10px]"
                        : e.role === "assistant" ? "border-blue-500/30 text-blue-400 text-[10px]"
                        : "border-yellow-500/30 text-yellow-400 text-[10px]"
                      }>{e.role}</Badge>
                      <span className="text-[10px] text-muted-foreground">{e.timestamp?.slice(0, 19)}</span>
                    </div>
                    <p className="text-xs text-foreground/80 line-clamp-2 font-mono">{e.content?.slice(0, 200)}</p>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right 1/3 */}
        <div className="space-y-6">
          {/* System */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">System</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-3">
              {[
                { icon: HardDrive, label: "Database", status: "Active", ok: true },
                { icon: Activity, label: "FTS Index", status: "Synced", ok: true },
                { icon: Clock, label: "Sources", status: "3 connected", ok: true },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <item.icon className="h-3.5 w-3.5" />
                    <span>{item.label}</span>
                  </div>
                  {item.ok ? (
                    <Badge variant="outline" className="text-green-400 border-green-500/30 text-[10px]">{item.status}</Badge>
                  ) : (
                    <span className="text-xs text-muted-foreground">{item.status}</span>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Quick actions */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Quick Actions</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-0.5">
              {[
                { label: "Search", href: "/search", icon: Search },
                { label: "Sessions", href: "/sessions", icon: MessageSquare },
                { label: "Live view", href: "/live", icon: Radio },
                { label: "Setup", href: "/setup", icon: Activity },
              ].map((a) => (
                <Link key={a.href} href={a.href} className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                  <a.icon className="h-3.5 w-3.5" />
                  <span>{a.label}</span>
                </Link>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
