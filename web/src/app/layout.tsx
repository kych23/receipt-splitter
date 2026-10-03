import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible_Next, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Interface type: designed for legibility (low vision), which is the brief.
const ui = Atkinson_Hyperlegible_Next({
  variable: "--font-ui",
  subsets: ["latin"],
  // next/font can't compute metrics for this family, so name the fallback explicitly.
  fallback: ["system-ui", "sans-serif"],
  adjustFontFallback: false,
});

// What the receipt itself "prints": prices, totals, tax.
const print = IBM_Plex_Mono({
  variable: "--font-print",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
});

export const metadata: Metadata = {
  title: "ReceiptSplit",
  description: "Split shared grocery receipts exactly, tax included.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#dce2e7" },
    { media: "(prefers-color-scheme: dark)", color: "#151a20" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${ui.variable} ${print.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
