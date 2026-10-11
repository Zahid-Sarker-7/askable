"use client";

import { useCallback, useRef, useState } from "react";

import { createSSEStream } from "@/lib/sse";
import type { ChatMessage, Strategy } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function updateLastMessage(
  prev: ChatMessage[],
  update: Partial<ChatMessage>
): ChatMessage[] {
  const updated = [...prev];
  updated[updated.length - 1] = { ...updated[updated.length - 1], ...update };
  return updated;
}

export function useRAGStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  const sendQuery = useCallback(
    async (
      query: string,
      strategy: Strategy,
      sessionId: string,
      includeSamples: boolean,
      hasUploads: boolean,
    ) => {
      setError(null);
      abortRef.current?.abort();

      const controller = new AbortController();
      abortRef.current = controller;

      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", content: query },
        { id: crypto.randomUUID(), role: "assistant", content: "", isStreaming: true },
      ]);
      setIsStreaming(true);

      try {
        const stream = createSSEStream(
          `${API_URL}/rag/query`,
          { query, strategy, include_samples: includeSamples, has_uploads: hasUploads },
          controller.signal,
          sessionId
        );

        for await (const event of stream) {
          if (event.type === "token") {
            setMessages((prev) =>
              updateLastMessage(prev, {
                content: prev[prev.length - 1].content + event.content,
              })
            );
          } else if (event.type === "sources") {
            setMessages((prev) => updateLastMessage(prev, { sources: event.sources }));
          } else if (event.type === "done") {
            setMessages((prev) => updateLastMessage(prev, { isStreaming: false }));
          } else if (event.type === "error") {
            setError(event.message);
          }
        }
      } catch (err) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
        }
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          return last?.isStreaming ? updateLastMessage(prev, { isStreaming: false }) : prev;
        });
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    []
  );

  return { messages, isStreaming, error, sendQuery, stopStreaming, clearMessages };
}
