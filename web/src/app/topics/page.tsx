"use client";

import { useEffect, useState, useMemo } from "react";
import { useSource } from "@/lib/source-context";
import { api, SOURCE_META, Entry } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Hash, Loader2 } from "lucide-react";

// Common stop words to exclude from frequency analysis
const STOP_WORDS = new Set([
  "the", "be", "to", "of", "and", "a", "in", "that", "have", "i",
  "it", "for", "not", "on", "with", "he", "as", "you", "do", "at",
  "this", "but", "his", "by", "from", "they", "we", "say", "her",
  "she", "or", "an", "will", "my", "one", "all", "would", "there",
  "their", "what", "so", "up", "out", "if", "about", "who", "get",
  "which", "go", "me", "when", "make", "can", "like", "time", "no",
  "just", "him", "know", "take", "people", "into", "year", "your",
  "good", "some", "could", "them", "see", "other", "than", "then",
  "now", "look", "only", "come", "its", "over", "think", "also",
  "back", "after", "use", "two", "how", "our", "work", "first",
  "well", "way", "even", "new", "want", "because", "any", "these",
  "give", "day", "most", "us", "is", "was", "are", "been", "has",
  "had", "did", "does", "am", "were", "being", "been", "more",
  "here", "should", "where", "very", "much", "may", "still",
  "such", "each", "own", "need", "too", "let", "using", "used",
]);

interface WordFrequency {
  word: string;
  count: number;
}

function extractTopics(entries: Entry[], maxTopics: number = 60): WordFrequency[] {
  const freq: Record<string, number> = {};

  for (const entry of entries) {
    if (!entry.content) continue;
    const words = entry.content
      .toLowerCase()
      .replace(/[^a-z0-9\s_-]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length > 3 && !STOP_WORDS.has(w) && !/^\d+$/.test(w));

    for (const word of words) {
      freq[word] = (freq[word] || 0) + 1;
    }
  }

  return Object.entries(freq)
    .map(([word, count]) => ({ word, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, maxTopics);
}

function fontSizeForCount(count: number, max: number, min: number): string {
  if (max === min) return "text-base";
  const ratio = (count - min) / (max - min);
  if (ratio > 0.8) return "text-2xl font-bold";
  if (ratio > 0.6) return "text-xl font-semibold";
  if (ratio > 0.4) return "text-lg font-medium";
  if (ratio > 0.2) return "text-base";
  return "text-sm";
}

function opacityForCount(count: number, max: number, min: number): number {
  if (max === min) return 0.8;
  return 0.4 + 0.6 * ((count - min) / (max - min));
}

export default function TopicsPage() {
  const { source } = useSource();
  const meta = SOURCE_META[source];
  const [entries, setEntries] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .latest({ source, limit: 100 })
      .then((r) => setEntries(r.entries || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [source]);

  const topics = useMemo(() => extractTopics(entries), [entries]);
  const maxCount = topics.length > 0 ? topics[0].count : 0;
  const minCount = topics.length > 0 ? topics[topics.length - 1].count : 0;

  // Shuffle for cloud display (deterministic based on word)
  const shuffledTopics = useMemo(() => {
    const arr = [...topics];
    for (let i = arr.length - 1; i > 0; i--) {
      const j = (arr[i].word.charCodeAt(0) * 31 + i) % (i + 1);
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }, [topics]);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Hash className="h-6 w-6" />
          Topics
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-1.5">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label} workspace
        </p>
      </div>

      {loading ? (
        <Card>
          <CardContent className="py-16 flex flex-col items-center justify-center gap-3">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Analyzing topics...</p>
          </CardContent>
        </Card>
      ) : topics.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <Hash className="h-10 w-10 mx-auto text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">
              No entries found to extract topics from.
            </p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Start a session to see topics appear here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Tag Cloud */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Word Cloud
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-3 items-center justify-center py-4">
                {shuffledTopics.map((t) => (
                  <span
                    key={t.word}
                    className={`${fontSizeForCount(t.count, maxCount, minCount)} text-primary transition-opacity hover:opacity-100 cursor-default`}
                    style={{ opacity: opacityForCount(t.count, maxCount, minCount) }}
                    title={`${t.word}: ${t.count} occurrences`}
                  >
                    {t.word}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Ranked List */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Top Terms ({topics.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1">
                {topics.slice(0, 30).map((t, i) => (
                  <div
                    key={t.word}
                    className="flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm hover:bg-muted transition-colors"
                  >
                    <span className="text-[10px] text-muted-foreground/50 w-5 text-right font-mono">
                      {i + 1}
                    </span>
                    <span className="flex-1 font-mono text-xs">{t.word}</span>
                    <Badge
                      variant="outline"
                      className="text-[10px] border-primary/20 text-primary"
                    >
                      {t.count}
                    </Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
