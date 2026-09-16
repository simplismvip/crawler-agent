"use client";

import { FormEvent, KeyboardEvent, useLayoutEffect, useRef } from "react";
import { ArrowUp, Square } from "lucide-react";

export function InputBar({
  value,
  onChange,
  disabled,
  busy,
  onSubmit,
  onStop,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  busy: boolean;
  onSubmit: () => void;
  onStop: () => void;
}) {
  const area = useRef<HTMLTextAreaElement>(null);
  const text = value ?? "";

  useLayoutEffect(() => {
    const node = area.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(Math.max(node.scrollHeight, 36), 168)}px`;
  }, [text]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (busy || disabled || !text.trim()) return;
    onSubmit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  const canSend = Boolean(text.trim()) && !busy && !disabled;

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-3xl px-4 pb-5 pt-8">
      <div className="flex items-center gap-2 rounded-[28px] bg-white px-4 py-2 shadow-capsule ring-1 ring-black/[0.08]">
        <textarea
          ref={area}
          value={text}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="问网页，或直接粘贴 http(s) 链接"
          className="gm-input max-h-40 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 text-[var(--gm-ink)] outline-none placeholder:text-[var(--gm-faint)] disabled:bg-transparent disabled:opacity-60"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--gm-ink)] text-white"
            aria-label="停止"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition ${
              canSend ? "bg-[var(--gm-ink)] text-white" : "bg-[#e8eaed] text-[#9aa0a6]"
            }`}
            aria-label="发送"
          >
            <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
          </button>
        )}
      </div>
      <p className="mt-2 text-center text-[11px] text-[var(--gm-faint)]">
        只抓取公开网页。需要登录的站点（如小红书）当前抓不到正文。
      </p>
    </form>
  );
}
