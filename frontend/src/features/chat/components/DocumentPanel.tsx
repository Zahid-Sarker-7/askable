"use client";

import { useRef } from "react";
import type { UploadedDocument } from "@/lib/types";

interface DocumentPanelProps {
  documents: UploadedDocument[];
  isUploading: boolean;
  error: string | null;
  onUpload: (file: File) => Promise<void>;
  onDelete: (docId: string) => Promise<void>;
  onClose: () => void;
}

function FileIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
    </svg>
  );
}

export function DocumentPanel({
  documents,
  isUploading,
  error,
  onUpload,
  onDelete,
  onClose,
}: DocumentPanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      onUpload(file);
      e.target.value = "";
    }
  }

  function formatDate(iso: string) {
    if (!iso) return "";
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  return (
    <div className="absolute right-0 top-14 z-20 w-80 rounded-xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <h2 className="text-sm font-semibold">Documents</h2>
        <button
          onClick={onClose}
          className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
        >
          ✕
        </button>
      </div>

      {/* Upload area */}
      <div className="p-4">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={isUploading}
          className="flex w-full flex-col items-center gap-1 rounded-lg border-2 border-dashed border-zinc-300 py-4 text-sm text-zinc-500 transition-colors hover:border-zinc-400 hover:text-zinc-700 disabled:opacity-50 dark:border-zinc-600 dark:hover:border-zinc-500"
        >
          <FileIcon />
          {isUploading ? "Uploading…" : "Click to upload"}
          <span className="text-xs text-zinc-400">PDF, TXT, DOCX · max 10 MB</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.txt,.docx"
          className="hidden"
          onChange={handleFileChange}
        />

        {error && (
          <p className="mt-2 text-xs text-red-500">{error}</p>
        )}
      </div>

      {/* Document list */}
      {documents.length > 0 && (
        <div className="max-h-60 overflow-y-auto border-t border-zinc-100 dark:border-zinc-800">
          {documents.map((doc) => (
            <div
              key={doc.doc_id}
              className="flex items-center gap-2 px-4 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-800"
            >
              <FileIcon />
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium">{doc.source_title}</p>
                <p className="text-xs text-zinc-400">
                  {doc.chunk_count} chunks · {formatDate(doc.ingested_at)}
                </p>
              </div>
              <button
                onClick={() => onDelete(doc.doc_id)}
                className="flex-shrink-0 rounded p-1 text-zinc-300 hover:text-red-500 dark:text-zinc-600"
                title="Delete document"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {documents.length === 0 && (
        <p className="px-4 pb-4 text-center text-xs text-zinc-400">
          No documents uploaded yet.
        </p>
      )}
    </div>
  );
}
