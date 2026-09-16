import type { Metadata } from "next";
import { Inter, Noto_Sans_SC } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const noto = Noto_Sans_SC({
  variable: "--font-noto",
  weight: ["400", "500", "600", "700"],
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "Crawler Agent",
  description: "公开网页检索 Agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className={`${inter.variable} ${noto.variable} font-sans`} style={{ fontFamily: "var(--font-noto), var(--font-inter), sans-serif" }}>
        {children}
      </body>
    </html>
  );
}
