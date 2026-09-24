"use client";

import { usePathname } from "next/navigation";
import { BottomNav, Header } from "@/components/common";

export function GlobalNavigation() {
  const pathname = usePathname();
  const active = pathname.startsWith("/retrieve") ? "retrieve" : "station";

  return <>
    <Header active={active} />
    <BottomNav active={active} />
  </>;
}
