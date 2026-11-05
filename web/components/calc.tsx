"use client";

import clsx from "clsx";
import { Calculator } from "lucide-react";
import { useEffect, useState } from "react";
import { american, pct, post } from "@/lib/api";

type CalcRes = { p_over: number; p_under: number; side: string; p_side: number; fair_over: number; fair_under: number;
  fair_dec_over: number; fair_dec_under: number; verdict: string };

export function Calc({ playerId, gameId, stat, unit, mu }: { playerId: string; gameId: string; stat: string; unit: string; mu: number }) {
  const [line, setLine] = useState<string>("");
  const [res, setRes] = useState<CalcRes | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setRes(null); setLine(""); }, [stat]);
  const run = () => {
    const v = parseFloat(line);
    if (isNaN(v)) return;
    setErr(null);
    post<CalcRes>("/api/calc", { player_id: playerId, game_id: gameId, stat, line: v }).then(setRes).catch((e) => setErr(String(e)));
  };
  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Calculator size={16} className="text-accent" /> Línea de Draftea</div>
      <div className="flex gap-2">
        <input value={line} onChange={(e) => setLine(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()}
          inputMode="decimal" placeholder={`p. ej. ${Math.round(mu) + 0.5}`}
          className="w-full rounded-lg border border-line bg-s2 px-3 py-2 text-sm outline-none focus:border-accent tnum" />
        <button onClick={run} className="rounded-lg bg-accent px-4 text-sm font-semibold text-on-accent">Calcular</button>
      </div>
      {err && <div className="mt-2 text-xs text-critical">{err}</div>}
      {res && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {(["over", "under"] as const).map((side) => {
              const p = side === "over" ? res.p_over : res.p_under;
              const best = res.side === side;
              return (
                <div key={side} className={clsx("rounded-xl border px-3 py-2.5", best ? "border-accent bg-accent-soft" : "border-line")}>
                  <div className="text-xs text-ink2">{side === "over" ? "Más" : "Menos"} de {line} {unit}</div>
                  <div className="text-2xl font-bold tnum">{pct(p, 1)}</div>
                  <div className="text-[11px] text-mute tnum">momio justo {american(side === "over" ? res.fair_over : res.fair_under)} · {side === "over" ? res.fair_dec_over : res.fair_dec_under}x</div>
                </div>
              );
            })}
          </div>
          <div className="text-sm"><b>{res.verdict}</b> <span className="text-ink2">hacia {res.side === "over" ? "Más" : "Menos"}. Si Draftea paga más que el momio justo, hay valor.</span></div>
        </div>
      )}
    </div>
  );
}
