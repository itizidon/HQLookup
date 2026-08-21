import type { Metadata } from "next";
import { connection } from "next/server";
import "./globals.css";
import Providers from "./providers"

export const metadata: Metadata = {
  title: "HQLookup",
  description: "Secure search across your business documents.",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Nonce-based CSP requires every document response to be rendered per request.
  await connection();

  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
