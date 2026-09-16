"use client";

import { Sparkle } from "@/components/Sparkle";

const SUGGESTIONS = [
  {
    label: "抓取 HN 首页前 5 条",
    text: "抓取 https://news.ycombinator.com 首页前 5 条标题，用表格输出。",
  },
  {
    label: "Fastify 升级说明",
    text: "搜索 Fastify 的官方升级说明，列出主要 breaking changes。",
  },
  {
    label: "总结古诗词网栏目",
    text: "抓取 https://www.gushici.net 首页，总结栏目结构。",
  },
];

export function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 pb-32">
      <Sparkle className="h-14 w-14" />
      <h1 className="gm-gradient-text mt-5 text-[3.25rem] font-medium leading-none tracking-tight">你好</h1>
      <p className="mt-4 text-[15px] text-[var(--gm-mute)]">需要我帮你搜索或抓取哪个公开网页？</p>
      <div className="mt-10 grid w-full max-w-3xl gap-3 sm:grid-cols-3">
        {SUGGESTIONS.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => onPick(item.text)}
            className="rounded-2xl bg-[var(--gm-chip)] px-4 py-4 text-left text-sm leading-6 text-[var(--gm-mute)] transition hover:bg-[var(--gm-hover)]"
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
