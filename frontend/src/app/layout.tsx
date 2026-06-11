import type { Metadata } from "next";
import { Inter, EB_Garamond } from "next/font/google";
import NextTopLoader from "nextjs-toploader";
import "./globals.css";
import "katex/dist/katex.min.css";
import { AuthProvider } from "@/contexts/AuthContext";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const ebGaramond = EB_Garamond({ subsets: ["latin"], variable: "--font-eb-garamond" });

export const metadata: Metadata = {
  title: "Relearn",
  description: "Citation-first agentic study workspace",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${ebGaramond.variable}`}>
      <body>
        <NextTopLoader color="#2563eb" showSpinner={false} />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
