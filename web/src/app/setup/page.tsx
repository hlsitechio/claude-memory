"use client";

import { useState } from "react";
import { useSource } from "@/lib/source-context";
import { SOURCE_META } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Settings, AlertTriangle, ExternalLink } from "lucide-react";

export default function SetupPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const [iframeError, setIframeError] = useState(false);

  return (
    <div className="p-6 flex flex-col h-[calc(100vh-0px)]">
      {/* Header */}
      <div className="shrink-0 mb-4">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Settings className="h-6 w-6" />
          Setup
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label} workspace
        </p>
      </div>

      {/* Iframe or Fallback */}
      {iframeError ? (
        <Card className="flex-1">
          <CardContent className="py-16 flex flex-col items-center justify-center gap-4">
            <AlertTriangle className="h-10 w-10 text-yellow-400/60" />
            <div className="text-center">
              <p className="text-sm text-foreground font-medium">
                Setup wizard unavailable
              </p>
              <p className="text-xs text-muted-foreground mt-1.5 max-w-md">
                The Python viewer at{" "}
                <code className="text-primary bg-muted px-1.5 py-0.5 rounded text-[11px]">
                  http://127.0.0.1:37888
                </code>{" "}
                doesn&apos;t appear to be running. Start the Memory Engine Python server first,
                then refresh this page.
              </p>
              <div className="flex items-center justify-center gap-3 mt-4">
                <button
                  onClick={() => setIframeError(false)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  Retry
                </button>
                <a
                  href="http://127.0.0.1:37888/setup"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                >
                  Open directly
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="flex-1 overflow-hidden">
          <iframe
            src="http://127.0.0.1:37888/setup"
            className="w-full h-full border-0 rounded-lg"
            style={{ minHeight: "calc(100vh - 120px)" }}
            title="Memory Engine Setup"
            onError={() => setIframeError(true)}
            onLoad={(e) => {
              // Detect cross-origin iframe load failures
              try {
                const frame = e.currentTarget;
                // If we can't access contentWindow.location, it loaded something
                // If the server is down, the browser shows its own error page
                if (frame.contentDocument?.title === "") {
                  // Blank page might indicate failure — but this check is best-effort
                }
              } catch {
                // Cross-origin is expected and fine — means the server responded
              }
            }}
          />
        </Card>
      )}
    </div>
  );
}
