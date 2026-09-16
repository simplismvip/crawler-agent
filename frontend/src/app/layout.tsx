import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Crawler Agent",
  description: "V1.1 public-web retrieval agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
