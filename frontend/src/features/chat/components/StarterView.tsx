"use client";

import type { UploadedDocument } from "@/lib/types";

interface StarterViewProps {
  includeSamples: boolean;
  documents: UploadedDocument[];
  onAsk: (question: string) => void;
}

// Curated starter questions for the built-in sample docs.
// These map to the sample corpus (pricing, refund, security, onboarding, API docs).
const SAMPLE_QUESTIONS = [
  "What is the refund policy?",
  "How much does the Pro plan cost?",
  "What encryption is used for data at rest?",
  "What is the on-call compensation?",
  "What HTTP status code is returned for rate limiting?",
];

const SAMPLE_TOPICS = ["Pricing", "Refund Policy", "Security", "Onboarding", "API Docs"];

export function StarterView({ includeSamples, documents, onAsk }: StarterViewProps) {
  const hasUploads = documents.length > 0;

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-8 text-center">
      <div>
        <h2 className="text-base font-semibold">Ask a question</h2>
        <p className="mt-1 text-sm text-zinc-500">
          {hasUploads
            ? "Answers come from your uploaded documents."
            : "Answers come from the sample documents below."}
        </p>
      </div>

      {/* What's available to search */}
      <div className="flex flex-wrap justify-center gap-1.5">
        {hasUploads
          ? documents.map((d) => (
              <span
                key={d.doc_id}
                className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
              >
                {d.source_title}
              </span>
            ))
          : SAMPLE_TOPICS.map((t) => (
              <span
                key={t}
                className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
              >
                {t}
              </span>
            ))}
      </div>

      {/* Clickable starter questions — only meaningful for the sample corpus */}
      {includeSamples && !hasUploads && (
        <div className="flex w-full max-w-md flex-col gap-2">
          <p className="text-xs font-medium text-zinc-400">Try asking</p>
          {SAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => onAsk(q)}
              className="rounded-lg border border-zinc-200 px-3 py-2 text-left text-sm text-zinc-700 transition-colors hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:border-zinc-500 dark:hover:bg-zinc-800"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {hasUploads && (
        <p className="max-w-md text-xs text-zinc-400">
          Type a question about your document{documents.length > 1 ? "s" : ""} in the box below.
        </p>
      )}
    </div>
  );
}
