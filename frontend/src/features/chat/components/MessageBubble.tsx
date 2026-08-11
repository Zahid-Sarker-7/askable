"use client";

import type { ChatMessage } from "@/lib/types";
import { SourcesList } from "./SourcesList";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
            : "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
        }`}
      >
        <p className="whitespace-pre-wrap text-sm leading-relaxed">
          {message.content}
          {message.isStreaming && (
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-current" />
          )}
        </p>
        {message.sources && message.sources.length > 0 && (
          <SourcesList sources={message.sources} />
        )}
      </div>
    </div>
  );
}
