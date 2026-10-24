import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "@/components/Nav";
import { LiveControls, Toaster } from "@/components/LiveControls";
import { InstrumentProvider, InstrumentSelect } from "@/lib/instrument";
import { LiveProvider } from "@/lib/live";
import { Badge } from "@/components/ui";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Forex AI Assistant",
  description: "Forex & metals AI trading assistant — paper trading only",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col font-sans">
        <InstrumentProvider>
        <LiveProvider>
          <header className="sticky top-0 z-10 border-b border-edge bg-bg/90 backdrop-blur">
            <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-2.5">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold tracking-tight">Forex AI</span>
                <Badge tone="warn">Paper trading</Badge>
                <InstrumentSelect />
              </div>
              <div className="flex flex-wrap items-center gap-3">
              <LiveControls />
              <Nav />
            </div>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5">{children}</main>
          <footer className="border-t border-edge px-4 py-3 text-center text-[11px] text-muted">
            Signals are statistical model outputs, not guarantees. No real-money orders are placed. Forex trading carries
            a high risk of loss.
          </footer>
        <Toaster />
        </LiveProvider>
        </InstrumentProvider>
      </body>
    </html>
  );
}
