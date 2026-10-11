"use client";

interface SourcesListProps {
  sources: string[];
}

export function SourcesList({ sources }: SourcesListProps) {
  if (sources.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      <span className="text-xs text-zinc-400">Sources:</span>
      {sources.map((source) => {
        const filename = source.split("/").pop() ?? source;
        return (
          <span
            key={source}
            className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
          >
            {filename}
          </span>
        );
      })}
    </div>
  );
}
