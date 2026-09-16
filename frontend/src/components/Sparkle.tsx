"use client";

import { useId } from "react";

export function Sparkle({ className = "h-6 w-6" }: { className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <defs>
        <linearGradient id={id} x1="4" y1="2" x2="20" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#4b90ff" />
          <stop offset="48%" stopColor="#c158dc" />
          <stop offset="100%" stopColor="#ff62c6" />
        </linearGradient>
      </defs>
      <path
        fill={`url(#${id})`}
        d="M12 1.6c.35 4.05 2.35 7.3 6.4 8.4-4.05.95-6.05 4.2-6.4 8.4-.35-4.2-2.35-7.45-6.4-8.4 4.05-1.1 6.05-4.35 6.4-8.4Z"
      />
    </svg>
  );
}
