"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSource } from "@/lib/source-context";
import { Source, SOURCE_META } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  Home,
  Search,
  BrainCircuit,
  Clock,
  MessageSquare,
  Hash,
  FolderOpen,
  Lightbulb,
  Radio,
  Settings,
  TerminalSquare,
  Terminal,
  GitBranch,
  Bot,
} from "lucide-react";

const SOURCE_ICONS: Record<Source, React.ElementType> = {
  claude_code: Terminal,
  copilot: GitBranch,
  codex: Bot,
};

const NAV_ITEMS = [
  { section: "Home", items: [
    { key: "home", label: "Dashboard", href: "/", icon: Home },
  ] },
  {
    section: "Search",
    items: [
      { key: "search", label: "Search", href: "/search", icon: Search },
      { key: "semantic", label: "Semantic", href: "/semantic", icon: BrainCircuit },
    ],
  },
  {
    section: "Browse",
    items: [
      { key: "timeline", label: "Timeline", href: "/timeline", icon: Clock },
      { key: "sessions", label: "Sessions", href: "/sessions", icon: MessageSquare },
      { key: "topics", label: "Topics", href: "/topics", icon: Hash },
    ],
  },
  {
    section: "Organize",
    items: [
      { key: "projects", label: "Projects", href: "/projects", icon: FolderOpen },
      { key: "observations", label: "Observations", href: "/observations", icon: Lightbulb },
    ],
  },
  { section: "Live", items: [{ key: "live", label: "Live View", href: "/live", icon: Radio }] },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { source, setSource } = useSource();

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-[220px] flex-col border-r border-border bg-sidebar">
      {/* Brand */}
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-3.5">
        <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
        <span className="text-sm font-semibold text-foreground">Memory Engine</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {NAV_ITEMS.map((group, gi) => (
          <div key={group.section}>
            <div className="mb-1">
              <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {group.section}
              </div>
              {group.items.map((item) => {
                const isActive =
                  item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                return (
                  <Link
                    key={item.key}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-all",
                      isActive
                        ? "bg-accent text-accent-foreground font-medium border-l-2 border-primary"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground border-l-2 border-transparent"
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>

            {/* CLI section right after Home */}
            {gi === 0 && (
              <div className="mb-1">
                <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  CLI
                </div>
                {(Object.keys(SOURCE_META) as Source[]).map((key) => {
                  const meta = SOURCE_META[key];
                  const Icon = SOURCE_ICONS[key];
                  const isActive = source === key;
                  return (
                    <button
                      key={key}
                      onClick={() => setSource(key)}
                      className={cn(
                        "flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-all",
                        isActive
                          ? "bg-accent text-accent-foreground font-medium border-l-2"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground border-l-2 border-transparent"
                      )}
                      style={isActive ? { borderLeftColor: meta.color } : {}}
                    >
                      <Icon className="h-4 w-4" />
                      <span className="flex-1 text-left">{meta.label}</span>
                      {isActive && (
                        <div
                          className="h-2 w-2 rounded-full"
                          style={{ backgroundColor: meta.color }}
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
        <Link href="/setup" className="flex items-center gap-2 hover:text-foreground transition-colors">
          <Settings className="h-3.5 w-3.5" />
          <span>Setup</span>
        </Link>
      </div>
    </aside>
  );
}
