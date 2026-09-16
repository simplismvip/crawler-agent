"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import type { ModelInfo } from "@/lib/api";

export function ModelSelect({
  models,
  value,
  onChange,
  disabled,
}: {
  models: ModelInfo[];
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const current = models.find((item) => item.id === value);

  useEffect(() => {
    function onDoc(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1 rounded-full px-3 py-1.5 text-lg font-medium text-[var(--gm-ink)] hover:bg-[var(--gm-hover)] disabled:opacity-50"
      >
        {current?.id ?? value}
        <ChevronDown className="h-4 w-4 text-[var(--gm-mute)]" />
      </button>
      {open ? (
        <div className="absolute left-0 z-20 mt-2 max-h-[min(28rem,calc(100vh-6rem))] w-[min(28rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl bg-white py-2 shadow-capsule ring-1 ring-black/[0.06]">
          {models.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                onChange(item.id);
                setOpen(false);
              }}
              className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-[var(--gm-hover)]"
            >
              <span className="mt-0.5 w-4 shrink-0">
                {item.id === value ? <Check className="h-4 w-4 text-[var(--gm-blue)]" /> : null}
              </span>
              <span>
                <span className="block text-sm font-medium">{item.id}</span>
                <span className="mt-0.5 block text-xs text-[var(--gm-faint)]">
                  {item.context >= 1_000_000
                    ? `${item.context / 1_000_000}M context`
                    : `${Math.round(item.context / 1000)}k context`}{" "}
                  · {item.blurb}
                </span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
