"use client";

import { useSource } from "@/lib/source-context";
import { Source, SOURCE_META } from "@/lib/api";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  Terminal,
  GitBranch,
  Bot,
  CheckCircle2,
  Database,
  MessageSquare,
  Clock,
  ArrowRight,
} from "lucide-react";
import Link from "next/link";

const SOURCE_ICONS: Record<Source, React.ElementType> = {
  claude_code: Terminal,
  copilot: GitBranch,
  codex: Bot,
};

const SOURCE_DESCRIPTIONS: Record<Source, string> = {
  claude_code: "Anthropic's AI coding assistant. Conversations stored in ~/.claude/projects/",
  copilot: "GitHub's AI pair programmer. Sessions stored in ~/.copilot/session-state/",
  codex: "OpenAI's coding agent. Sessions stored in ~/.codex/sessions/",
};

interface SourceStats {
  entries: number;
  sessions: number;
  lastActive: string;
}

export default function CliPage() {
  const { source, setSource } = useSource();
  const [stats, setStats] = useState<Record<Source, SourceStats>>({
    claude_code: { entries: 0, sessions: 0, lastActive: "" },
    copilot: { entries: 0, sessions: 0, lastActive: "" },
    codex: { entries: 0, sessions: 0, lastActive: "" },
  });

  useEffect(() => {
    // Fetch stats for all sources
    api.stats().then((s) => {
      // The stats endpoint returns global stats — we'll show totals
      // In a real implementation, you'd query per-source
      setStats((prev) => ({
        ...prev,
        claude_code: { ...prev.claude_code, entries: s.entries, sessions: s.sessions_done },
      }));
    }).catch(() => {});

    // Fetch session counts per source
    (["claude_code", "copilot", "codex"] as Source[]).forEach((src) => {
      api.sessions({ source: src, limit: 1 }).then((r) => {
        setStats((prev) => ({
          ...prev,
          [src]: {
            ...prev[src],
            sessions: r.total || r.sessions?.length || 0,
            lastActive: r.sessions?.[0]?.started_at?.slice(0, 10) || "Never",
          },
        }));
      }).catch(() => {});

      api.latest({ source: src, limit: 1 }).then((r) => {
        setStats((prev) => ({
          ...prev,
          [src]: {
            ...prev[src],
            entries: r.total || r.entries?.length || 0,
          },
        }));
      }).catch(() => {});
    });
  }, []);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">CLI Tools</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Switch between your AI coding tools. Each workspace is fully isolated.
        </p>
      </div>

      {/* CLI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {(Object.keys(SOURCE_META) as Source[]).map((key) => {
          const meta = SOURCE_META[key];
          const Icon = SOURCE_ICONS[key];
          const isActive = source === key;
          const st = stats[key];

          return (
            <Card
              key={key}
              className={cn(
                "cursor-pointer transition-all hover:border-foreground/20",
                isActive
                  ? "ring-2 ring-offset-2 ring-offset-background"
                  : "opacity-80 hover:opacity-100"
              )}
              style={isActive ? { borderColor: meta.color } : {}}
              onClick={() => setSource(key)}
            >
              <CardContent className="p-6">
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div
                      className="flex h-10 w-10 items-center justify-center rounded-lg"
                      style={{ backgroundColor: `${meta.color}20` }}
                    >
                      <Icon className="h-5 w-5" style={{ color: meta.color }} />
                    </div>
                    <div>
                      <h3 className="font-semibold text-foreground">{meta.label}</h3>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        {SOURCE_DESCRIPTIONS[key]}
                      </p>
                    </div>
                  </div>
                  {isActive && (
                    <Badge
                      variant="outline"
                      className="text-[10px] border-green-500/30 text-green-400"
                    >
                      <CheckCircle2 className="h-3 w-3 mr-1" />
                      Active
                    </Badge>
                  )}
                </div>

                {/* Stats */}
                <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-border">
                  <div>
                    <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                      <Database className="h-3 w-3" />
                      <span className="text-[10px] uppercase tracking-wider">Entries</span>
                    </div>
                    <p className="text-lg font-bold" style={{ color: isActive ? meta.color : undefined }}>
                      {st.entries.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                      <MessageSquare className="h-3 w-3" />
                      <span className="text-[10px] uppercase tracking-wider">Sessions</span>
                    </div>
                    <p className="text-lg font-bold" style={{ color: isActive ? meta.color : undefined }}>
                      {st.sessions.toLocaleString()}
                    </p>
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
                      <Clock className="h-3 w-3" />
                      <span className="text-[10px] uppercase tracking-wider">Last</span>
                    </div>
                    <p className="text-xs font-medium text-muted-foreground mt-1">
                      {st.lastActive || "—"}
                    </p>
                  </div>
                </div>

                {/* Action */}
                {isActive ? (
                  <Link
                    href="/"
                    className="flex items-center justify-center gap-2 mt-4 rounded-md px-4 py-2 text-sm font-medium transition-colors"
                    style={{ backgroundColor: `${meta.color}20`, color: meta.color }}
                  >
                    Go to Dashboard <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                ) : (
                  <button
                    onClick={() => setSource(key)}
                    className="flex items-center justify-center gap-2 mt-4 w-full rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  >
                    Switch to {meta.label}
                  </button>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Info */}
      <Card className="bg-muted/30">
        <CardContent className="p-5">
          <p className="text-sm text-muted-foreground">
            Each CLI tool has its own isolated workspace. Conversations, sessions, and search results
            never mix between tools. Switch tools above, then use the sidebar to browse that tool's data.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
