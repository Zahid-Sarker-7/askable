"use client";

interface EmptyStateProps {
  onUploadClick: () => void;
  onTrySamples: () => void;
}

export function EmptyState({ onUploadClick, onTrySamples }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-zinc-100 dark:bg-zinc-800">
        <svg className="h-7 w-7 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
        </svg>
      </div>

      <div>
        <h2 className="text-base font-semibold">Upload a document to get started</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Ask questions and get answers grounded in your own files.
        </p>
      </div>

      <button
        onClick={onUploadClick}
        className="rounded-xl bg-zinc-900 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200"
      >
        Upload Document
      </button>

      <button
        onClick={onTrySamples}
        className="text-xs text-zinc-400 underline-offset-2 hover:text-zinc-600 hover:underline dark:hover:text-zinc-300"
      >
        or try with sample docs
      </button>
    </div>
  );
}
