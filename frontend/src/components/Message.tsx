"use client";

import type { Components } from "react-markdown";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, ChevronDown, Copy, FileJson, Film, Globe, Images, Link2, Monitor, Share2, Wrench } from "lucide-react";
import { Sparkle } from "@/components/Sparkle";
import type { ToolCard } from "@/lib/api";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs text-[var(--gm-mute)] opacity-70 hover:bg-[var(--gm-hover)] hover:opacity-100"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "已复制" : "复制"}
    </button>
  );
}

function isFailureText(content: string) {
  const text = content.trim();
  return /^connection error\.?$/i.test(text) || text.startsWith("请求失败");
}

const markdownComponents: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
};

const TOOL_UI: Record<string, { icon: typeof Globe; running: string; done: string }> = {
  search_web: { icon: Globe, running: "正在搜索网页", done: "已搜索网页" },
  scrape_page: { icon: Link2, running: "正在抓取页面", done: "已抓取页面" },
  collect_dataset: { icon: FileJson, running: "正在保存数据集", done: "已保存数据集" },
  scrape_rendered: { icon: Monitor, running: "正在渲染页面", done: "已渲染页面" },
  download_media: { icon: Film, running: "正在提取媒体", done: "已提取媒体" },
  download_gallery: { icon: Images, running: "正在下载图集", done: "已下载图集" },
  scrape_social: { icon: Share2, running: "正在抓取社交内容", done: "已抓取社交内容" },
};

export function ToolPanel({ tool }: { tool: ToolCard }) {
  const [open, setOpen] = useState(tool.status === "running" || tool.status === "error");
  const ui = TOOL_UI[tool.name] ?? { icon: Wrench, running: `正在调用 ${tool.name}`, done: `已调用 ${tool.name}` };
  const Icon = ui.icon;
  const label = tool.status === "running" ? ui.running : ui.done;
  return (
    <div className="overflow-hidden rounded-2xl bg-[var(--gm-chip)] text-sm">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[var(--gm-mute)]"
        onClick={() => setOpen((value) => !value)}
      >
        <Icon className={`h-4 w-4 ${tool.status === "running" ? "animate-pulse text-[var(--gm-blue)]" : ""}`} />
        <span className="flex-1">
          {label}
          {tool.status === "error" ? " · 失败" : ""}
        </span>
        <ChevronDown className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className="space-y-2 border-t border-white/80 px-3 py-2 text-[13px] text-[var(--gm-mute)]">
          <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[12px]">
            {JSON.stringify(tool.args, null, 2)}
          </pre>
          {tool.error ? <p className="text-red-600">{tool.error}</p> : null}
          {tool.preview ? <p className="whitespace-pre-wrap leading-6">{tool.preview}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function MessageBubble({
  role,
  content,
  tools,
  streaming = false,
}: {
  role: "user" | "assistant";
  content: string;
  tools: ToolCard[];
  streaming?: boolean;
}) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-[24px] bg-[var(--gm-sidebar)] px-4 py-3 text-[15px] leading-7">
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      </div>
    );
  }

  const failed = Boolean(content) && isFailureText(content);

  return (
    <div className="flex gap-3">
      <div className="relative mt-1 h-7 w-7 shrink-0 self-start">
        <Sparkle className={`h-7 w-7 ${streaming ? "gm-sparkle-busy" : ""}`} />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {tools.map((tool, index) => (
          <ToolPanel key={tool.id ?? `${tool.name}-${index}`} tool={tool} />
        ))}
        {failed ? (
          <div className="rounded-2xl bg-red-50 px-4 py-3 text-[14px] leading-6 text-red-700">{content}</div>
        ) : content ? (
          <div className={`md-body ${streaming ? "gm-caret" : ""}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          <p className="text-sm text-[var(--gm-faint)]">正在思考…</p>
        )}
        {content && !streaming ? (
          <div className="flex">
            <CopyButton text={content} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
