"use client";

import { createContext, useContext, useState, ReactNode } from "react";
import { Source } from "./api";

interface SourceContextType {
  source: Source;
  setSource: (s: Source) => void;
}

const SourceContext = createContext<SourceContextType>({
  source: "claude_code",
  setSource: () => {},
});

export function SourceProvider({ children }: { children: ReactNode }) {
  const [source, setSource] = useState<Source>("claude_code");
  return (
    <SourceContext.Provider value={{ source, setSource }}>
      {children}
    </SourceContext.Provider>
  );
}

export function useSource() {
  return useContext(SourceContext);
}
