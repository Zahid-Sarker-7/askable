"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { UploadedDocument } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getOrCreateSessionId(): string {
  const key = "askable_session_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

export function useDocuments() {
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef<string>("");

  useEffect(() => {
    sessionId.current = getOrCreateSessionId();
    loadDocuments();
  }, []);

  const headers = () => ({ "X-Session-ID": sessionId.current });

  const loadDocuments = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/documents`, { headers: headers() });
      if (!res.ok) return;
      const data = await res.json();
      setDocuments(data.documents ?? []);
    } catch {
      // silently fail — document list is non-critical
    }
  }, []);

  const upload = useCallback(
    async (file: File, sourceTitle?: string): Promise<void> => {
      // TODO: Implement upload.
      //
      // 1. Set isUploading = true, clear error
      // 2. Build a FormData object:
      //    const form = new FormData();
      //    form.append("file", file);
      //    if (sourceTitle) form.append("source_title", sourceTitle);
      //
      // 3. POST to /upload with X-Session-ID header:
      //    const res = await fetch(`${API_URL}/upload`, {
      //      method: "POST",
      //      headers: headers(),   // NOTE: do NOT set Content-Type — browser sets it with boundary
      //      body: form,
      //    });
      //
      // 4. If !res.ok: parse error detail and setError(detail)
      //
      // 5. If ok: call loadDocuments() to refresh the list
      //
      // 6. Finally: setIsUploading(false)

      setIsUploading(true);
      setError(null);
      const form = new FormData();
      form.append("file", file);
      if (sourceTitle) form.append("source_title", sourceTitle);

      try {
        const res = await fetch(`${API_URL}/upload`, {
          method: "POST",
          headers: headers(),
          body: form,
        });

        if (!res.ok) {
          const data = await res.json();
          setError(data.detail ?? "Upload failed");
        } else {
          await loadDocuments();
        }
      } catch (err) {
        setError("Upload failed");
      } finally {
        setIsUploading(false);
      }
    },
    [loadDocuments]
  );

  const deleteDoc = useCallback(
    async (docId: string): Promise<void> => {
      // TODO: Implement deleteDoc.
      //
      // 1. DELETE to /documents/{docId} with X-Session-ID header:
      //    await fetch(`${API_URL}/documents/${docId}`, {
      //      method: "DELETE",
      //      headers: headers(),
      //    });
      //
      // 2. Remove the document from local state optimistically:
      //    setDocuments(prev => prev.filter(d => d.doc_id !== docId));
      //
      // (No need to reload — optimistic removal is instant)

      try {
        await fetch(`${API_URL}/documents/${docId}`, {
          method: "DELETE",
          headers: headers(),
        });
        setDocuments((prev) => prev.filter((d) => d.doc_id !== docId));
      } catch (err) {
        // silently fail — deletion is non-critical
      }
    },
    []
  );

  return {
    documents,
    isUploading,
    error,
    sessionId: sessionId.current,
    upload,
    deleteDoc,
    reload: loadDocuments,
  };
}
