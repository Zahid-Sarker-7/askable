"use client";

import { useState } from "react";

import type { Strategy } from "@/lib/types";
import { useDocuments } from "../hooks/useDocuments";
import { useRAGStream } from "../hooks/useRAGStream";
import { ChatInput } from "./ChatInput";
import { DocumentPanel } from "./DocumentPanel";
import { EmptyState } from "./EmptyState";
import { MessageList } from "./MessageList";
import { StarterView } from "./StarterView";
import { StrategySelector } from "./StrategySelector";

function DocumentIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  );
}

export function ChatPage() {
  const [strategy, setStrategy] = useState<Strategy>("standard");
  const [showDocs, setShowDocs] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [includeSamples, setIncludeSamples] = useState(false);

  const { documents, isUploading, error: uploadError, sessionId, upload, deleteDoc } = useDocuments();
  const { messages, isStreaming, error, sendQuery, stopStreaming, clearMessages } = useRAGStream();

  const hasContext = documents.length > 0 || includeSamples;

  function handleSend(query: string) {
    sendQuery(query, strategy, sessionId, includeSamples, documents.length > 0);
  }

  function handleTrySamples() {
    setIncludeSamples(true);
  }

  return (
    <div className="relative flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">Askable</h1>
          {includeSamples && (
            <button
              onClick={() => setIncludeSamples(false)}
              title="Turn off sample docs"
              className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700 transition-colors hover:bg-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:hover:bg-amber-900/50"
            >
              samples on
              <span aria-hidden className="text-sm leading-none">×</span>
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowDocs((s) => !s)}
            className="relative flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-zinc-600 transition-colors hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            <DocumentIcon />
            <span>Docs</span>
            {documents.length > 0 && (
              <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-zinc-900 text-[10px] text-white dark:bg-zinc-100 dark:text-zinc-900">
                {documents.length}
              </span>
            )}
          </button>

          <button
            onClick={() => setShowAdvanced((s) => !s)}
            className="rounded-lg px-2 py-1.5 text-xs text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
            title="Advanced settings"
          >
            Advanced
          </button>

          {messages.length > 0 && (
            <button
              onClick={clearMessages}
              disabled={isStreaming}
              className="rounded-lg px-3 py-1.5 text-sm text-zinc-500 transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              Clear
            </button>
          )}
        </div>
      </header>

      {/* Advanced settings row (hidden by default) */}
      {showAdvanced && (
        <div className="flex items-center gap-3 border-b border-zinc-200 bg-zinc-50 px-4 py-2 dark:border-zinc-800 dark:bg-zinc-900/50">
          <span className="text-xs text-zinc-400">Retrieval strategy:</span>
          <StrategySelector value={strategy} onChange={setStrategy} disabled={isStreaming} />
          <label className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500">
            <input
              type="checkbox"
              checked={includeSamples}
              onChange={(e) => setIncludeSamples(e.target.checked)}
            />
            Include sample docs
          </label>
        </div>
      )}

      {/* Document panel (dropdown) */}
      {showDocs && (
        <DocumentPanel
          documents={documents}
          isUploading={isUploading}
          error={uploadError}
          onUpload={upload}
          onDelete={deleteDoc}
          onClose={() => setShowDocs(false)}
        />
      )}

      {/* Body: empty state → starter view → messages */}
      {messages.length === 0 && !hasContext ? (
        <EmptyState onUploadClick={() => setShowDocs(true)} onTrySamples={handleTrySamples} />
      ) : messages.length === 0 ? (
        <StarterView includeSamples={includeSamples} documents={documents} onAsk={handleSend} />
      ) : (
        <MessageList messages={messages} />
      )}

      {/* Error banner */}
      {error && (
        <div className="mx-4 mb-2 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-zinc-200 p-4 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <ChatInput onSend={handleSend} disabled={isStreaming || !hasContext} />
          </div>
          {isStreaming && (
            <button
              onClick={stopStreaming}
              className="rounded-xl border border-zinc-300 px-4 py-3 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              Stop
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
