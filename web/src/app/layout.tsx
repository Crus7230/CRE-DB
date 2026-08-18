import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "부동산 시장 인텔리전스 | IGIS Research",
  description: "Supabase market_intelligence 기반 부동산 시장정보 통합검색 대시보드",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
