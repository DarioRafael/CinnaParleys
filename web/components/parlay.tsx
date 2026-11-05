"use client";

import clsx from "clsx";
import { Layers, Link2, Trash2, X } from "lucide-react";
import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { Pick, american, pct, post } from "@/lib/api";
import { TierBadge } from "./ui";

type Leg = Pick;
type Ctx = { legs: Leg[]; add: (p: Pick) => void; remove: (id: string) => void; has: (id: string) => boolean; clear: () => void; open: boolean; setOpen: (b: boolean) => void };
const ParlayCtx = createContext<Ctx | null>(null);

export function useParlay() {
  const c = useContext(ParlayCtx);
  if (!c) throw new Error("ParlayProvider faltante");
  return c;
}

export function ParlayProvider({ children }: { children: ReactNode }) {
  const [legs, setLegs] = useState<Leg[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    try {
      const s = localStorage.getItem("cerebro_parlay");
      if (s) setLegs(JSON.parse(s));
    } catch { /* almacenamiento no disponible */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem("cerebro_parlay", JSON.stringify(legs)); } catch { /* ignorar */ }
  }, [legs]);
  const value = useMemo<Ctx>(() => ({
    legs,
    add: (p) => setLegs((l) => (l.some((x) => x.pick_id === p.pick_id) ? l : [...l, p])),
    remove: (id) => setLegs((l) => l.filter((x) => x.pick_id !== id)),
    has: (id) => legs.some((x) => x.pick_id === id),
    clear: () => setLegs([]),
    open, setOpen,
  }), [legs, open]);
  return (
    <ParlayCtx.Provider value={value}>
      {children}
      <ParlayDrawer />
    </ParlayCtx.Provider>
  );
}

export function AddToParlay({ pick, compact }: { pick: Pick; compact?: boolean }) {
  const { add, remove, has } = useParlay();
  const inside = has(pick.pick_id);
  return (
    <button
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (inside) remove(pick.pick_id); else add(pick); }}
      className={clsx("inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition-colors",
        inside ? "border-accent bg-accent-soft text-accent" : "border-line text-ink2 hover:border-line-strong hover:text-ink")}
      title={inside ? "Quitar del combinado" : "Agregar al combinado"}
    >
      <Layers size={13} /> {compact ? (inside ? "✓" : "+") : inside ? "En combinado" : "Combinar"}
    </button>
  );
}

type ParlayRes = { p_joint: number; p_independent: number; lift: number; fair_american: number; fair_decimal: number;
  correlations: { i: number; j: number; r: number; text: string }[] };

function ParlayDrawer() {
  const { legs, remove, clear, open, setOpen } = useParlay();
  const [res, setRes] = useState<ParlayRes | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (legs.length < 2) { setRes(null); return; }
    setLoading(true);
    post<ParlayRes>("/api/parlay", {
      legs: legs.map((l) => ({ game_id: l.game_id, player_id: l.player_id ?? null, team: l.team ?? (l.type === "game" ? l.side : null),
        market: l.market, side: l.side, prob: l.prob, title: l.title })),
    }).then(setRes).catch(() => setRes(null)).finally(() => setLoading(false));
  }, [legs]);

  if (!legs.length && !open) return null;
  return (
    <>
      {!open && legs.length > 0 && (
        <button onClick={() => setOpen(true)}
          className="fixed bottom-24 right-4 z-40 flex items-center gap-2 rounded-full bg-brand-fill px-4 py-3 text-sm font-bold text-on-brand shadow-[0_12px_24px_-10px_var(--brand)] ring-4 ring-[var(--pink-soft)] md:bottom-6">
          <Layers size={16} /> Combinado · {legs.length}
        </button>
      )}
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end bg-[rgba(30,18,12,0.45)] backdrop-blur-[2px]" onClick={() => setOpen(false)}>
          <aside className="flex h-full w-full max-w-md flex-col border-l border-line bg-s1" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <div>
                <div className="font-display text-lg font-semibold">Tu combinado</div>
                <div className="text-xs text-mute">Probabilidad conjunta con correlaciones reales</div>
              </div>
              <button onClick={() => setOpen(false)} className="rounded-lg p-1.5 text-ink2 hover:bg-s2"><X size={18} /></button>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto px-5 py-4">
              {legs.length === 0 && <div className="py-10 text-center text-sm text-mute">Agrega picks con el botón “Combinar”.</div>}
              {legs.map((l, i) => (
                <div key={l.pick_id} className="rounded-xl border border-line bg-s2 px-3 py-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{i + 1}. {l.title}</div>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-mute">
                        <span>{l.game_label}</span><TierBadge tier={l.tier} />
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold tnum">{pct(l.prob)}</span>
                      <button onClick={() => remove(l.pick_id)} className="rounded-md p-1 text-mute hover:bg-s3 hover:text-ink"><Trash2 size={14} /></button>
                    </div>
                  </div>
                </div>
              ))}
              {res && res.correlations.length > 0 && (
                <div className="rounded-xl border border-line px-3 py-2.5">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-ink2"><Link2 size={13} /> Relación entre picks</div>
                  {res.correlations.map((c, k) => (
                    <div key={k} className="text-xs text-ink2">
                      {c.i + 1} y {c.j + 1}: {c.text} <span className={c.r > 0 ? "text-good" : "text-critical"}>({c.r > 0 ? "+" : ""}{c.r})</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="border-t border-line px-5 py-4">
              {legs.length >= 2 ? (
                <div className={clsx("space-y-2", loading && "opacity-60")}>
                  <div className="flex items-end justify-between">
                    <div>
                      <div className="text-xs text-mute">Probabilidad de acertar todo</div>
                      <div className="text-3xl font-semibold">{res ? pct(res.p_joint, 1) : "…"}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-mute">Momio justo</div>
                      <div className="text-lg font-semibold tnum">{res ? `${american(res.fair_american)} · ${res.fair_decimal}x` : "…"}</div>
                    </div>
                  </div>
                  {res && (
                    <div className="text-xs text-ink2">
                      Si fueran independientes: {pct(res.p_independent, 1)}.{" "}
                      {res.lift > 1.03 ? "Estos picks se refuerzan entre sí." : res.lift < 0.97 ? "Ojo: estos picks se contradicen un poco." : "Casi independientes."}
                      {" "}Si Draftea paga más que {res.fair_decimal}x, el combinado tiene valor.
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-sm text-mute">Agrega al menos 2 picks.</div>
              )}
              {legs.length > 0 && (
                <button onClick={clear} className="mt-3 w-full rounded-lg border border-line py-2 text-sm text-ink2 hover:bg-s2">Vaciar combinado</button>
              )}
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
