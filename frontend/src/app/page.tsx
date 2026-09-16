"use client";

import { useRef, useState } from "react";
import { InputBar } from "@/components/InputBar";
import { MessageBubble, type ToolCard } from "@/components/Message";
import { Sidebar } from "@/components/Sidebar";
import { readSse } from "@/lib/sse";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools: ToolCard[];
};

export default function HomePage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const abortRef = useRef<AbortController | null>(null);

  async function send(text: string) {
    const user: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text, tools: [] };
    const assistantId = crypto.randomUUID();
    const assistant: ChatMessage = { id: assistantId, role: "assistant", content: "", tools: [] };
    setMessages((current) => [...current, user, assistant]);
    setBusy(true);
    setStatus("请求中");
    const controller = new AbortController();
    abortRef.current = controller;

    const patchAssistant = (updater: (message: ChatMessage) => ChatMessage) => {
      setMessages((current) =>
        current.map((message) => (message.id === assistantId ? updater(message) : message)),
      );
    };

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: [] }),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      await readSse(
        response,
        (eventName, data) => {
          if (eventName === "token" && typeof data.text === "string") {
            patchAssistant((message) => ({ ...message, content: message.content + data.text }));
          }
          if (eventName === "tool_start") {
            const card: ToolCard = {
              name: String(data.name ?? "tool"),
              args: (data.args as Record<string, unknown>) ?? {},
              status: "running",
            };
            patchAssistant((message) => ({ ...message, tools: [...message.tools, card] }));
            setStatus(`调用 ${card.name}`);
          }
          if (eventName === "tool_end") {
            patchAssistant((message) => {
              const tools = [...message.tools];
              const index = [...tools].reverse().findIndex((tool) => tool.name === data.name && tool.status === "running");
              const realIndex = index === -1 ? -1 : tools.length - 1 - index;
              if (realIndex >= 0) {
                tools[realIndex] = {
                  ...tools[realIndex],
                  status: data.status === "ok" ? "ok" : "error",
                  preview: typeof data.preview === "string" ? data.preview : "",
                  error: typeof data.error === "string" ? data.error : null,
                };
              }
              return { ...message, tools };
            });
          }
          if (eventName === "error" && typeof data.message === "string") {
            patchAssistant((message) => ({
              ...message,
              content: message.content || data.message as string,
            }));
            setStatus(data.message as string);
          }
          if (eventName === "done") {
            setStatus(data.status === "error" ? "结束（错误）" : "完成");
            if (data.status === "error") {
              patchAssistant((message) => ({
                ...message,
                content: message.content || "请求失败，请重试。",
              }));
            }
          }
        },
        controller.signal,
      );
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        setStatus("已取消");
      } else {
        setStatus((error as Error).message);
        patchAssistant((message) => ({
          ...message,
          content: message.content || `请求失败：${(error as Error).message}`,
        }));
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-h-screen flex-1 flex-col">
        <header className="border-b border-zinc-200 px-4 py-3 text-sm text-zinc-500">{status}</header>
        <main className="flex-1 space-y-4 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <p className="text-center text-sm text-zinc-500">
              试着问：抓取 https://news.ycombinator.com 首页前 5 条标题，用表格输出。
            </p>
          ) : (
            messages.map((message) => (
              <MessageBubble
                key={message.id}
                role={message.role}
                content={message.content}
                tools={message.tools}
              />
            ))
          )}
        </main>
        <InputBar disabled={busy} onSubmit={send} />
      </div>
    </div>
  );
}
