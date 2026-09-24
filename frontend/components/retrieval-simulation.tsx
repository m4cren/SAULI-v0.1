"use client";

import { ArrowRight, Camera, Check, Clock3, DoorOpen, MapPin, PackageCheck, ScanLine } from "lucide-react";
import { useEffect, useState } from "react";
import type { FoundItem, Retrieval } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { BackButton, Button, SuccessMark } from "./common";

// Decorative QR-style pattern for a simulation, deliberately not a real QR code.
// The opaque random token contains no item details, identity, or credentials.
function FakeQr({ token }: { token: string }) {
  const seed = [...token].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) >>> 0, 0);
  const cells = Array.from({ length: 25 * 25 }, (_, index) => {
    const x = index % 25; const y = Math.floor(index / 25);
    const corner = [[0, 0], [18, 0], [0, 18]].find(([left, top]) => x >= left && x < left + 7 && y >= top && y < top + 7);
    if (corner) {
      const dx = x - corner[0]; const dy = y - corner[1];
      return dx === 0 || dx === 6 || dy === 0 || dy === 6 || (dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4);
    }
    const value = (Math.imul(seed ^ index, 1664525) + 1013904223) >>> 0;
    return value % 3 !== 0;
  });
  return <div className="fake-qr" role="img" aria-label="Decorative prototype QR-style pass. Use the simulate station scan button; this is not a scannable code.">{cells.map((filled, index) => <span key={index} className={filled ? "filled" : ""} />)}<span className="qr-demo-mark">DEMO</span></div>;
}

export function RetrievalPass({ item, token, expiresAt, onBack, onScan, onRenew }: {
  item: FoundItem; token: string; expiresAt: number; onBack: () => void; onScan: () => void; onRenew: () => void;
}) {
  const [remaining, setRemaining] = useState(() => Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000)));
  useEffect(() => {
    const timer = setInterval(() => setRemaining(Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000))), 500);
    return () => clearInterval(timer);
  }, [expiresAt]);
  const expired = remaining <= 0;
  return <div className="retrieval-pass fade-in"><BackButton onClick={onBack}>Results</BackButton><div className="centered-heading"><div className="eyebrow">RETRIEVAL PASS</div><h1>Scan at the SAULI station</h1></div><div className={`pass-card ${expired ? "expired" : ""}`}><div className="pass-card-heading"><ScanLine size={15} /><span>PROTOTYPE PASS</span><span>DEMO</span></div><FakeQr token={token} /><p className="qr-caption">NOT A SCANNABLE QR CODE</p><h2>{item.analysis.object_name}</h2><p className="pass-item-code">{item.item_code}</p><div className="expiry-row"><span><Clock3 size={14} />{expired ? "Expired" : "Expires in"}</span><strong aria-label={`${Math.floor(remaining / 60)} minutes and ${remaining % 60} seconds remaining`}>{String(Math.floor(remaining / 60)).padStart(2, "0")}:{String(remaining % 60).padStart(2, "0")}</strong></div></div>{expired ? <Button onClick={onRenew}>Generate new pass <ArrowRight size={17} /></Button> : <Button onClick={onScan}><ScanLine size={18} /> Simulate station scan</Button>}</div>;
}

export function CompartmentDisplay() {
  return <div className="compartment-diagram" role="img" aria-label="Illustrative cabinet with ten pocket-size slots and five medium-size slots. Demonstration compartment C3 is highlighted."><div className="cabinet-columns"><div className="cabinet-section"><span>POCKET-SIZE</span><div className="pocket-grid">{Array.from({ length: 10 }, (_, i) => <div key={i} className={i === 4 ? "chosen" : ""}>{i === 4 ? <><MapPin size={14} /><strong>C3</strong></> : `P-${String(i + 1).padStart(2, "0")}`}</div>)}</div></div><div className="cabinet-section"><span>MEDIUM-SIZE</span><div className="medium-grid">{Array.from({ length: 5 }, (_, i) => <div key={i}>M-{String(i + 1).padStart(2, "0")}</div>)}</div></div><div className="cabinet-section station-column"><span>STATION</span><div><Camera size={22} /><small>CAMERA</small></div><div><span className="tiny-screen" /><small>TOUCHSCREEN</small></div></div></div><div className="cabinet-legend"><span><i />Your demo compartment</span><span>Illustration only</span></div></div>;
}

export function SimulatedLocation({ onRemove, onBack, busy }: { onRemove: () => void; onBack: () => void; busy: boolean }) {
  return <div className="fade-in"><BackButton onClick={onBack} disabled={busy}>Retrieval pass</BackButton><div className="centered-heading"><SuccessMark /><h1>Locate your item</h1></div><div className="compartment-label"><span>SIMULATED COMPARTMENT</span><strong>C3</strong><p>Pocket-size section</p></div><CompartmentDisplay /><ol className="retrieval-steps"><li><span><Check size={15} /></span><div><strong>Pass accepted</strong></div></li><li><span><DoorOpen size={16} /></span><div><strong>Open the highlighted compartment</strong></div></li><li><span><PackageCheck size={16} /></span><div><strong>Remove only your item</strong></div></li></ol><Button onClick={onRemove} loading={busy}>{busy ? "Recording retrieval…" : "Simulate item removal"}{!busy && <ArrowRight size={18} />}</Button></div>;
}

export function RetrievalComplete({ retrieval, onSearch }: { retrieval: Retrieval; onSearch: () => void }) {
  return <div className="retrieved-view fade-in"><div className="centered-heading"><SuccessMark /><h1>Item retrieved</h1></div><dl className="detail-rows receipt-rows"><div><dt>Item</dt><dd>{retrieval.item_name}</dd></div><div><dt>Item code</dt><dd>{retrieval.item_code}</dd></div><div><dt>Compartment</dt><dd>{retrieval.compartment}</dd></div><div><dt>Retriever</dt><dd>{retrieval.retriever}</dd></div><div><dt>Recorded</dt><dd>{formatDate(retrieval.retrieved_at)}</dd></div></dl><div className="retrieval-saved"><span><Check size={16} /></span><div><strong>Retrieval log saved</strong></div></div><div className="completion-bottom"><Button onClick={onSearch}>Return to search <ArrowRight size={18} /></Button></div></div>;
}
