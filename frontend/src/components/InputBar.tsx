"use client";

import { FormEvent, KeyboardEvent, useState } from "react";

export function InputBar({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (text: string) => void;
}) {
  const [value, setValue] = useState("");

  function submit(event?: FormEvent) {
    event?.preventDefault();
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={submit} className="border-t border-zinc-200 bg-white p-4">
      <div className="mx-auto flex max-w-3xl gap-2">
        <textarea
          value={value}
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder="输入问题或带上 http(s) URL…"
          className="min-h-[52px] flex-1 resize-y rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none ring-zinc-400 focus:ring-2 disabled:bg-zinc-100"
        />
        <button
          type="submit"
          disabled={disabled}
          className="self-end rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          发送
        </button>
      </div>
    </form>
  );
}
