"use client";

import { useSource } from "@/lib/source-context";
import { SOURCE_META } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Lightbulb,
  GitBranch,
  AlertTriangle,
  CheckCircle2,
  Sparkles,
} from "lucide-react";

const OBSERVATION_TYPES = [
  {
    label: "Patterns",
    description: "Recurring code patterns, workflows, and behaviors detected across sessions",
    icon: GitBranch,
    color: "text-blue-400",
    borderColor: "border-blue-500/20",
    count: 0,
  },
  {
    label: "Decisions",
    description: "Architecture choices, library selections, and trade-offs made during development",
    icon: CheckCircle2,
    color: "text-green-400",
    borderColor: "border-green-500/20",
    count: 0,
  },
  {
    label: "Discoveries",
    description: "New insights, gotchas, and surprising findings from debugging and exploration",
    icon: Sparkles,
    color: "text-purple-400",
    borderColor: "border-purple-500/20",
    count: 0,
  },
  {
    label: "Warnings",
    description: "Potential issues, deprecated patterns, and things to watch out for",
    icon: AlertTriangle,
    color: "text-yellow-400",
    borderColor: "border-yellow-500/20",
    count: 0,
  },
];

export default function ObservationsPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Lightbulb className="h-6 w-6" />
          Observations
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label} workspace
        </p>
      </div>

      {/* Description */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-start gap-3">
            <Lightbulb className="h-5 w-5 text-yellow-400/60 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm text-foreground font-medium">
                Auto-extracted patterns, decisions, and discoveries
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                The Memory Engine analyzes your conversations to surface recurring patterns,
                important decisions, and noteworthy discoveries. These observations help you
                maintain context across long-running projects.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Observation Type Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {OBSERVATION_TYPES.map((type) => (
          <Card
            key={type.label}
            className={`${type.borderColor} hover:border-primary/20 transition-colors`}
          >
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium flex items-center gap-2">
                  <type.icon className={`h-4 w-4 ${type.color}`} />
                  {type.label}
                </CardTitle>
                <Badge
                  variant="outline"
                  className="text-[10px] text-muted-foreground border-border"
                >
                  {type.count} found
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">{type.description}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Empty State */}
      <Card>
        <CardContent className="py-16 text-center">
          <Lightbulb className="h-10 w-10 mx-auto text-muted-foreground/20 mb-3" />
          <p className="text-sm text-muted-foreground">
            No observations extracted yet.
          </p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            Observations will appear here as the engine analyzes your sessions.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
