"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type ToolCard = {
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  preview?: string;
  error?: string | null;
};

export function ToolPanel({ tool }: { tool: ToolCard }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-md border border-zinc-200 bg-white text-sm">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left"
        onClick={() => setOpen((value) => !value)}
      >
        <span>
          {tool.status === "running" ? "正在执行" : tool.status === "ok" ? "已完成" : "失败"}{" "}
          <code className="rounded bg-zinc-100 px-1">{tool.name}</code>
        </span>
        <span className="text-zinc-400">{open ? "收起" : "展开"}</span>
      </button>
      {open ? (
        <div className="space-y-2 border-t border-zinc-100 px-3 py-2 text-zinc-600">
          <pre className="overflow-x-auto whitespace-pre-wrap break-all text-xs">
            {JSON.stringify(tool.args, null, 2)}
          </pre>
          {tool.error ? <p className="text-red-600">{tool.error}</p> : null}
          {tool.preview ? <p className="whitespace-pre-wrap">{tool.preview}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function MessageBubble({
  role,
  content,
  tools,
}: {
  role: "user" | "assistant";
  content: string;
  tools: ToolCard[];
}) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-3xl space-y-2 rounded-lg px-4 py-3 ${
          isUser ? "bg-zinc-900 text-white" : "bg-white text-zinc-900 ring-1 ring-zinc-200"
        }`}
      >
        {tools.map((tool, index) => (
          <ToolPanel key={`${tool.name}-${index}`} tool={tool} />
        ))}
        {content ? (
          isUser ? (
            <p className="whitespace-pre-wrap text-sm">{content}</p>
          ) : (
            <div className="prose prose-sm max-w-none prose-p:my-2">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}
