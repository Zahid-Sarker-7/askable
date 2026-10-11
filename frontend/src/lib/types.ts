// SSE event types — discriminated union matching the backend's JSON format.
// The backend sends: data: {"type": "token", "content": "..."}\n\n
export type StreamEvent =
  | { type: "token"; content: string }
  | { type: "sources"; sources: string[] }
  | { type: "done" }
  | { type: "error"; message: string };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: string[];
  isStreaming?: boolean;
}

export type Strategy = "standard" | "hyde" | "multi_query";

export interface RAGRequest {
  query: string;
  model?: string;
  strategy?: Strategy;
  include_samples?: boolean;
  has_uploads?: boolean;
}

export interface UploadedDocument {
  doc_id: string;
  source_title: string;
  source: string;
  doc_type: string;
  owner: string;
  ingested_at: string;
  version: number;
  chunk_count: number;
}
