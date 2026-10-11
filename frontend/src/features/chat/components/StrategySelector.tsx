"use client";

import type { Strategy } from "@/lib/types";

const STRATEGIES: { value: Strategy; label: string; description: string }[] = [
  { value: "standard", label: "Standard", description: "Hybrid search (dense + BM25 + RRF)" },
  { value: "hyde", label: "HyDE", description: "Hypothetical document embeddings" },
  { value: "multi_query", label: "Multi-Query", description: "Query expansion with variations" },
];

interface StrategySelectorProps {
  value: Strategy;
  onChange: (strategy: Strategy) => void;
  disabled: boolean;
}

export function StrategySelector({ value, onChange, disabled }: StrategySelectorProps) {
  return (
    <div className="flex gap-1">
      {STRATEGIES.map((s) => (
        <button
          key={s.value}
          onClick={() => onChange(s.value)}
          disabled={disabled}
          title={s.description}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            value === s.value
              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
              : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
