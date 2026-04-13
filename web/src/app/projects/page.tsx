"use client";

import { useSource } from "@/lib/source-context";
import { SOURCE_META } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  FolderOpen,
  Plus,
  FolderKanban,
  Clock,
  MessageSquare,
} from "lucide-react";

const PLACEHOLDER_PROJECTS = [
  {
    name: "Default Workspace",
    description: "Uncategorized sessions and entries",
    sessions: 0,
    lastActive: "—",
    status: "active" as const,
  },
];

export default function ProjectsPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FolderOpen className="h-6 w-6" />
            Projects
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: meta.color }}
            />
            {meta.label} workspace
          </p>
        </div>
        <button
          disabled
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground opacity-50 cursor-not-allowed"
          title="Coming soon"
        >
          <Plus className="h-4 w-4" />
          Create Project
        </button>
      </div>

      {/* Description */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-start gap-3">
            <FolderKanban className="h-5 w-5 text-muted-foreground mt-0.5 shrink-0" />
            <div>
              <p className="text-sm text-foreground font-medium">
                Organize sessions by theme
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Group related conversations into projects. Tag sessions with project names,
                track progress across multiple coding sessions, and keep your memory organized.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Project Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {PLACEHOLDER_PROJECTS.map((project) => (
          <Card
            key={project.name}
            className="hover:border-primary/30 transition-colors cursor-default"
          >
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <FolderOpen className="h-4 w-4 text-primary/60" />
                  {project.name}
                </CardTitle>
                <Badge
                  variant="outline"
                  className={
                    project.status === "active"
                      ? "text-green-400 border-green-500/30 text-[10px]"
                      : "text-muted-foreground border-border text-[10px]"
                  }
                >
                  {project.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground mb-3">
                {project.description}
              </p>
              <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <MessageSquare className="h-3 w-3" />
                  {project.sessions} sessions
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {project.lastActive}
                </span>
              </div>
            </CardContent>
          </Card>
        ))}

        {/* Add Project Card */}
        <Card className="border-dashed border-2 hover:border-primary/30 transition-colors cursor-not-allowed opacity-50">
          <CardContent className="p-6 flex flex-col items-center justify-center h-full min-h-[140px] gap-2">
            <Plus className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-xs text-muted-foreground">New Project</p>
            <p className="text-[10px] text-muted-foreground/60">Coming soon</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
