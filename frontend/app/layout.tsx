import type { Metadata, Viewport } from "next";
import "./globals.css";
import Providers from "./providers";

export const metadata: Metadata = {
  applicationName: "HQLookup",
  title: {
    default: "HQLookup",
    template: "%s | HQLookup",
  },
  description:
    "Search your business documents and spreadsheets with secure, organization-aware AI.",
  keywords: ["business search", "document search", "RAG", "knowledge base"],
  category: "technology",
  robots: {
    index: false,
    follow: false,
  },
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#ffffff",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
