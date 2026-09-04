import type { Metadata } from "next";
import "./globals.css";
import { TopNav } from "@/components/top-nav";

export const metadata: Metadata = {
  title: "StockWeb · 投研工作台",
  description: "个人股票投研工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="app-shell">
          <header className="site-header">
            <div className="brand-block">
              <div className="brand-mark">S</div>
              <div>
                <div className="brand-name">StockWeb</div>
                <div className="brand-subtitle">PERSONAL RESEARCH WORKBENCH</div>
              </div>
            </div>
            <TopNav />
          </header>
          <main className="page-wrap">{children}</main>
        </div>
      </body>
    </html>
  );
}
