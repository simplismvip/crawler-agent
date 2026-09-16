"use client";

import { useEffect, useRef, useState } from "react";
import { Menu } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { InputBar } from "@/components/InputBar";
import { MessageBubble } from "@/components/Message";
import { ModelSelect } from "@/components/ModelSelect";
import { Sidebar } from "@/components/Sidebar";
import {
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchModels,
  renameConversation,
  type ChatMessage,
  type ConversationSummary,
  type ModelInfo,
  type ToolCard,
} from "@/lib/api";
import { readSse } from "@/lib/sse";

export default function HomePage() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [model, setModel] = useState("MiniMax-M3");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [query, setQuery] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void fetchModels()
      .then((payload) => {
        setModels(payload.models);
        setModel((current) => current || payload.default);
      })
      .catch((error) => console.error(error));
  }, []);

  useEffect(() => {
    if (!query) {
      void fetchConversations("")
        .then((list) => setConversations(list ?? []))
        .catch((error) => console.error(error));
      return;
    }
    const handle = window.setTimeout(() => {
      void fetchConversations(query)
        .then((list) => setConversations(list ?? []))
        .catch((error) => console.error(error));
    }, 200);
    return () => window.clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function resetToNewChat() {
    abortRef.current?.abort();
    setActiveId(null);
    setMessages([]);
    setDraft("");
    setBusy(false);
  }

  async function openConversation(id: string) {
    const detail = await fetchConversation(id);
    setActiveId(detail.id);
    setModel(detail.model);
    setMessages(detail.messages);
  }

  async function send(text?: string) {
    const content = (text ?? draft).trim();
    if (!content || busy) return;
    const user: ChatMessage = { id: crypto.randomUUID(), role: "user", content, tools: [] };
    const assistantId = crypto.randomUUID();
    const assistant: ChatMessage = { id: assistantId, role: "assistant", content: "", tools: [] };
    setMessages((current) => [...current, user, assistant]);
    setDraft("");
    setBusy(true);
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
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: content,
          conversation_id: activeId,
          model,
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      await readSse(
        response,
        (eventName, data) => {
          if (eventName === "conversation") {
            const id = String(data.conversation_id);
            const title = String(data.title ?? content);
            const usedModel = String(data.model ?? model);
            setActiveId(id);
            setConversations((current) => {
              const next: ConversationSummary = {
                id,
                title,
                model: usedModel,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              };
              return [next, ...current.filter((item) => item.id !== id)];
            });
          }
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
              content: message.content || (data.message as string),
            }));
          }
          if (eventName === "done" && data.status === "error") {
            patchAssistant((message) => ({
              ...message,
              content: message.content || "请求失败，请重试。",
            }));
          }
        },
        controller.signal,
      );
      void fetchConversations(query).then((list) => setConversations(list ?? []));
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
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
    <div className="flex h-dvh overflow-hidden bg-white">
      <Sidebar
        open={sidebarOpen}
        conversations={conversations}
        activeId={activeId}
        query={query}
        onQuery={setQuery}
        onNewChat={resetToNewChat}
        onSelect={(id) => void openConversation(id)}
        onRename={async (id, title) => {
          const updated = await renameConversation(id, title);
          setConversations((current) => current.map((item) => (item.id === id ? { ...item, ...updated } : item)));
        }}
        onDelete={async (id) => {
          await deleteConversation(id);
          setConversations((current) => current.filter((item) => item.id !== id));
          if (activeId === id) resetToNewChat();
        }}
      />
      <div className="relative flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-1 px-2">
          <button
            type="button"
            className="rounded-full p-2 text-[var(--gm-mute)] hover:bg-[var(--gm-hover)]"
            aria-label={sidebarOpen ? "收起侧边栏" : "展开侧边栏"}
            onClick={() => setSidebarOpen((value) => !value)}
          >
            <Menu className="h-5 w-5" />
          </button>
          <ModelSelect models={models} value={model} onChange={setModel} disabled={busy} />
          {busy ? <span className="ml-1 text-sm text-[var(--gm-faint)]">正在生成</span> : null}
        </header>
        <div ref={scroller} className="gm-scrollbar flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <EmptyState
              onPick={(text) => {
                setDraft(text);
                void send(text);
              }}
            />
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-8 px-4 pb-36 pt-6">
              {messages.map((message, index) => (
                <MessageBubble
                  key={message.id}
                  role={message.role}
                  content={message.content}
                  tools={message.tools}
                  streaming={busy && message.role === "assistant" && index === messages.length - 1}
                />
              ))}
            </div>
          )}
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-white via-white to-transparent pt-12">
          <div className="pointer-events-auto">
            <InputBar
              value={draft}
              onChange={setDraft}
              disabled={busy}
              busy={busy}
              onSubmit={() => void send()}
              onStop={() => abortRef.current?.abort()}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
