import type { Metadata } from "next";
import { GlobalNavigation } from "@/components/global-navigation";
import "./globals.css";

export const metadata: Metadata = {
  title: "SAULI · A little closer to found",
  description: "A campus lost-and-found research prototype for LSPU San Pablo City Campus.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><GlobalNavigation />{children}</body></html>;
}
