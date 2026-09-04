import type { Metadata } from "next";
import { connection } from "next/server";
import { headers } from "next/headers";
import Script from "next/script";
import "./globals.css";
import Providers from "./providers";

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

  const nonce = (await headers()).get("x-nonce") ?? undefined;

  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>

        <Script
          nonce={nonce}
          src="https://www.googletagmanager.com/gtag/js?id=AW-18430725015"
          strategy="afterInteractive"
        />

        <Script
          nonce={nonce}
          id="google-ads-tag"
          strategy="afterInteractive"
        >
          {`
            window.dataLayer = window.dataLayer || [];

            function gtag() {
              window.dataLayer.push(arguments);
            }

            gtag('js', new Date());
            gtag('config', 'AW-18430725015');
          `}
        </Script>
      </body>
    </html>
  );
}