"use client";

import Link from "next/link";
import { AlertCircle, ArrowLeft, ArrowUpRight, Check, CircleHelp, HeartHandshake, LoaderCircle, Monitor, Search, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

export function Wordmark() {
  return <span className="wordmark" aria-label="SAULI">S<span>A</span>UL<span>I</span><span className="wordmark-dot" /></span>;
}

export function Header({ active }: { active: "station" | "retrieve" }) {
  return <header className="site-header">
    <div className="header-inner">
      <Link href="/station" className="brand-link" aria-label="SAULI home"><Wordmark /><span className="brand-caption">CAMPUS LOST & FOUND</span></Link>
      <nav className="desktop-nav" aria-label="Main navigation">
        <Link href="/station" className={active === "station" ? "active" : ""} aria-current={active === "station" ? "page" : undefined}><Monitor size={16} /> Station</Link>
        <Link href="/retrieve" className={active === "retrieve" ? "active" : ""} aria-current={active === "retrieve" ? "page" : undefined}><Search size={16} /> Find an item</Link>
      </nav>
      <div className="header-end"><span className="prototype-label"><span /> Prototype</span></div>
    </div>
  </header>;
}

export function BottomNav({ active }: { active: "station" | "retrieve" }) {
  return <nav className="bottom-nav" aria-label="Mobile navigation">
    <Link href="/retrieve" className={active === "retrieve" ? "active" : ""} aria-current={active === "retrieve" ? "page" : undefined}><Search size={21} /><span>Find an item</span></Link>
    <Link href="/station" className={active === "station" ? "active" : ""} aria-current={active === "station" ? "page" : undefined}><Monitor size={21} /><span>Station</span></Link>
  </nav>;
}

export function Button({ children, secondary = false, loading = false, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { secondary?: boolean; loading?: boolean }) {
  return <button className={`${secondary ? "button-secondary" : "button-primary"} ${className}`} {...props} disabled={props.disabled || loading}>{loading && <LoaderCircle size={18} className="spin" aria-hidden="true" />}{children}</button>;
}

export function BackButton({ onClick, children = "Back", disabled = false }: { onClick: () => void; children?: ReactNode; disabled?: boolean }) {
  return <button type="button" className="back-button" onClick={onClick} disabled={disabled}><ArrowLeft size={18} />{children}</button>;
}

export function ErrorMessage({ message }: { message: string }) {
  if (!message) return null;
  return <div className="error-message" role="alert"><AlertCircle size={19} /><div><strong>We couldn’t complete that</strong><p>{message}</p></div></div>;
}

export function Note({ children, title, kind = "info" }: { children: ReactNode; title?: string; kind?: "info" | "privacy" | "simulation" }) {
  const Icon = kind === "privacy" ? ShieldCheck : kind === "simulation" ? CircleHelp : HeartHandshake;
  return <div className={`note note-${kind}`}><Icon size={18} aria-hidden="true" /><div>{title && <strong>{title}</strong>}<p>{children}</p></div></div>;
}

export function SuccessMark() { return <div className="success-mark"><Check size={30} strokeWidth={2} /></div>; }

export function PageFooter() {
  return <footer className="page-footer"><span>Made for things that find their way back.</span><span>LSPU · San Pablo City Campus <ArrowUpRight size={13} /></span></footer>;
}

export function ItemImage({ src, alt, className = "" }: { src?: string; alt: string; className?: string }) {
  return <div className={`item-image ${className}`}>{src ? <img src={src} alt={alt} referrerPolicy="no-referrer" onError={(event) => { event.currentTarget.hidden = true; event.currentTarget.nextElementSibling?.removeAttribute("hidden"); }} /> : null}<span hidden={Boolean(src)}>Image unavailable.<br />Reopen the item to refresh its image.</span></div>;
}
