import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ORBIT",
  description: "AI reliability control plane. Observe. Reason. Act. Verify.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <header className="sticky top-0 z-10 border-b border-border bg-background/90 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="text-[15px] font-semibold tracking-[0.18em]">ORBIT</span>
              <span className="hidden text-[12px] text-muted sm:inline">Observe. Reason. Act. Verify.</span>
            </Link>
            <nav className="flex gap-4 text-[13px] text-muted">
              <Link href="/" className="hover:text-foreground">Dashboard</Link>
              <Link href="/evaluation" className="hover:text-foreground">Evaluation</Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-5 sm:px-6">{children}</main>
      </body>
    </html>
  );
}
