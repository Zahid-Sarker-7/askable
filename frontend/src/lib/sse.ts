import type { StreamEvent, RAGRequest } from "./types";

export function parseSSEChunk(
  text: string,
  buffer: string
): { events: StreamEvent[]; remaining: string } {
  const combined = buffer + text;
  const parts = combined.split("\n\n");
  const remaining = parts.pop() ?? "";

  const events: StreamEvent[] = [];
  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    const lines = trimmed.split("\n");
    for (const line of lines) {
      if (line.startsWith("data:")) {
        const dataStr = line.slice(5).trim();
        try {
          events.push(JSON.parse(dataStr) as StreamEvent);
        } catch {
          // Skip malformed JSON
        }
      }
    }
  }
  return { events, remaining };
}

export async function* createSSEStream(
  url: string,
  body: RAGRequest,
  signal?: AbortSignal,
  sessionId?: string
): AsyncGenerator<StreamEvent> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (sessionId) headers["X-Session-ID"] = sessionId;

  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ ...body }),
    signal,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const errorBody = await response.json();
      if (errorBody.detail) detail = errorBody.detail;
    } catch {
      // Use status code as message
    }
    throw new Error(detail);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Response body is not readable");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const text = decoder.decode(value, { stream: true });
    const { events, remaining } = parseSSEChunk(text, buffer);
    buffer = remaining;

    for (const event of events) {
      yield event;
    }
  }

  if (buffer.trim()) {
    const { events } = parseSSEChunk(buffer + "\n\n", "");
    for (const event of events) {
      yield event;
    }
  }
}
