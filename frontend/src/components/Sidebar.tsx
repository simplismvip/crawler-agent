"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil, Plus, Search, Trash2 } from "lucide-react";
import type { ConversationSummary } from "@/lib/api";

export function Sidebar({
  open,
  conversations,
  activeId,
  query,
  onQuery,
  onNewChat,
  onSelect,
  onRename,
  onDelete,
}: {
  open: boolean;
  conversations: ConversationSummary[];
  activeId: string | null;
  query: string;
  onQuery: (value: string) => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  return (
    <aside
      className={`flex h-dvh shrink-0 flex-col overflow-hidden bg-[var(--gm-sidebar)] transition-[width] duration-200 ${
        open ? "w-[268px]" : "w-[72px]"
      }`}
    >
      <div className={`flex h-14 items-center ${open ? "px-3" : "justify-center px-2"}`}>
        <button
          type="button"
          onClick={onNewChat}
          title="新对话"
          className="flex items-center gap-3 rounded-full px-2 py-2 text-sm font-medium text-[var(--gm-ink)] hover:bg-[var(--gm-hover)]"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white shadow-sm">
            <Plus className="h-4 w-4" />
          </span>
          {open ? "新对话" : null}
        </button>
      </div>
      {open ? (
        <>
          <div className="px-4 pb-2">
            <label className="flex items-center gap-2 rounded-full bg-white/80 px-3 py-2 text-sm text-[var(--gm-mute)] ring-1 ring-black/[0.04]">
              <Search className="h-4 w-4" />
              <input
                value={query}
                onChange={(event) => onQuery(event.target.value)}
                placeholder="搜索对话"
                className="w-full bg-transparent outline-none placeholder:text-[var(--gm-faint)]"
              />
            </label>
          </div>
          <div className="gm-scrollbar flex-1 overflow-y-auto px-3 pb-4">
            <p className="px-3 pb-1 pt-3 text-xs font-medium text-[var(--gm-faint)]">最近</p>
            {(conversations ?? []).length === 0 ? (
              <p className="px-3 pt-2 text-xs text-[var(--gm-faint)]">还没有对话</p>
            ) : (
              conversations.map((item) => (
                <ConversationRow
                  key={item.id}
                  item={item}
                  active={item.id === activeId}
                  onSelect={() => onSelect(item.id)}
                  onRename={onRename}
                  onDelete={onDelete}
                />
              ))
            )}
          </div>
        </>
      ) : null}
    </aside>
  );
}

function ConversationRow({
  item,
  active,
  onSelect,
  onRename,
  onDelete,
}: {
  item: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [title, setTitle] = useState(item.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTitle(item.title);
  }, [item.title]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  async function save() {
    const next = title.trim() || "新对话";
    setEditing(false);
    if (next !== item.title) await onRename(item.id, next);
  }

  return (
    <div
      className={`group mb-0.5 flex items-center rounded-full px-3 py-2 text-sm ${
        active ? "bg-[var(--gm-active)]" : "hover:bg-[var(--gm-hover)]"
      }`}
    >
      {editing ? (
        <input
          ref={inputRef}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          onBlur={() => void save()}
          onKeyDown={(event) => {
            if (event.key === "Enter") void save();
            if (event.key === "Escape") {
              setTitle(item.title);
              setEditing(false);
            }
          }}
          className="w-full bg-transparent outline-none"
        />
      ) : confirmDelete ? (
        <div className="flex w-full items-center justify-between gap-1 text-xs">
          <span>删除？</span>
          <span className="flex gap-1">
            <button type="button" className="rounded-full px-2 py-1 hover:bg-white" onClick={() => void onDelete(item.id)}>
              删除
            </button>
            <button type="button" className="rounded-full px-2 py-1 hover:bg-white" onClick={() => setConfirmDelete(false)}>
              取消
            </button>
          </span>
        </div>
      ) : (
        <>
          <button type="button" onClick={onSelect} className="min-w-0 flex-1 truncate text-left">
            {item.title}
          </button>
          <span className="hidden shrink-0 group-hover:flex">
            <button
              type="button"
              className="rounded-full p-1 hover:bg-white"
              aria-label="重命名"
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              className="rounded-full p-1 hover:bg-white"
              aria-label="删除"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </span>
        </>
      )}
    </div>
  );
}
