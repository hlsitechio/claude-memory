"use client";

import { SourceProvider } from "@/lib/source-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppSidebar } from "@/components/app-sidebar";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SourceProvider>
      <TooltipProvider>
        <div className="flex min-h-screen">
          <AppSidebar />
          <main className="flex-1 ml-[220px]">{children}</main>
        </div>
      </TooltipProvider>
    </SourceProvider>
  );
}
