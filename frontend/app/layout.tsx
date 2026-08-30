import type { Metadata } from "next";
import "@fontsource-variable/dm-sans";
import "@fontsource-variable/newsreader";
import "./globals.css";

export const metadata: Metadata = {
  title: "Skylark Signal — Live Business Intelligence",
  description: "Evidence-first conversational intelligence for monday.com.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
