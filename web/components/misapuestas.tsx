"use client";

import clsx from "clsx";
import { Wallet } from "lucide-react";
import { useState } from "react";
import { pct, post, useApi } from "@/lib/api";
import { SectionTitle } from "./ui";

type Resumen = {
  apuestas: number; ganadas: number; pendientes: number; apostado: number; cobrado: number; balance: number;
  patas: { total: number; ganadas: number; el_cerebro_decia: number | null };
  por_tipo: { [k: string]: { patas: number; ganadas: number; acierto: number; cerebro_decia: number } };
  pendientes_detalle: { id: string; patas: string[]; prob_conjunta: number | null; monto: number | null; pago: number | null }[];
  ultimas: { id: string; estado: string; patas: string[]; prob_conjunta: number | null; monto: number | null; cobro: number | null }[];
};
type Registro = {
  error?: string; registrada?: string; prob_conjunta?: number | null; pago_justo?: number; valor_esperado?: number;
  patas?: { titulo: string; prob: number | null; semaforo?: string; en_contra?: string[] }[]; no_entendi?: string[];
};

export function MisApuestas() {
  const { data, mutate } = useApi<Resumen>("/api/mis_apuestas", { revalidateOnFocus: false });
  const [texto, setTexto] = useState("");
  const [monto, setMonto] = useState("");
  const [pago, setPago] = useState("");
  const [res, setRes] = useState<Registro | null>(null);

  async function registrar() {
    if (!texto.trim()) return;
    const r = await post<Registro>("/api/mis_apuestas", { texto, monto: Number(monto) || null, pago: Number(pago) || null });
    setRes(r);
    if (!r.error) { setTexto(""); mutate(); }
  }

  return (
    <section className="card space-y-4 p-5">
      <SectionTitle><span className="inline-flex items-center gap-1.5"><Wallet size={14} />Mis apuestas</span></SectionTitle>
      <p className="text-xs text-mute">Anota lo que apostaste: Cinna revisa cada pata, te dice la probabilidad real del parlay y lo califica solo cuando terminan los partidos.</p>
      <div className="grid gap-2 md:grid-cols-[1fr_auto_auto_auto]">
        <textarea value={texto} onChange={(e) => setTexto(e.target.value)} rows={2} placeholder="Young 220 yds de pase, Young 20 completos, Stafford 262 yds"
          className="rounded-lg border border-line bg-s1 p-2 text-sm text-ink outline-none focus:border-accent" />
        <input value={monto} onChange={(e) => setMonto(e.target.value)} placeholder="Monto" inputMode="decimal"
          className="h-9 w-24 rounded-lg border border-line bg-s1 px-2 text-sm text-ink outline-none focus:border-accent" />
        <input value={pago} onChange={(e) => setPago(e.target.value)} placeholder="Paga (x)" inputMode="decimal"
          className="h-9 w-24 rounded-lg border border-line bg-s1 px-2 text-sm text-ink outline-none focus:border-accent" />
        <button onClick={registrar} className="h-9 rounded-lg bg-accent px-3 text-sm font-semibold text-on-accent">Registrar</button>
      </div>
      {res && (
        <div className="rounded-lg border border-line p-3 text-sm">
          {res.error ? <span className="text-warning">{res.error}</span> : (
            <>
              <div className="mb-1"><b>Sale {pct(res.prob_conjunta, 0)}</b>{res.pago_justo ? <span className="text-xs text-mute"> · pago justo ~{res.pago_justo}x{res.valor_esperado != null ? ` · valor esperado ${pct(res.valor_esperado, 0)}` : ""}</span> : null}</div>
              <ul className="space-y-0.5 text-xs">
                {res.patas?.map((l) => (
                  <li key={l.titulo} className={clsx(l.semaforo === "rojo" ? "text-critical" : l.semaforo === "amarillo" ? "text-warning" : "text-ink2")}>
                    {l.titulo} — {pct(l.prob, 0)}{l.en_contra?.length ? ` · en contra: ${l.en_contra.slice(0, 2).join("; ")}` : ""}
                  </li>
                ))}
              </ul>
              {res.no_entendi?.length ? <div className="mt-1 text-xs text-warning">No entendí: {res.no_entendi.join(", ")}</div> : null}
            </>
          )}
        </div>
      )}
      {data && data.apuestas + data.pendientes > 0 && (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-4 tnum">
            <span>Calificadas: <b>{data.ganadas}/{data.apuestas}</b></span>
            <span>Apostado: <b>${data.apostado}</b></span>
            <span>Cobrado: <b>${data.cobrado}</b></span>
            <span className={data.balance >= 0 ? "text-good" : "text-critical"}>Balance: <b>${data.balance}</b></span>
            <span>Patas: <b>{data.patas.ganadas}/{data.patas.total}</b>{data.patas.el_cerebro_decia != null ? ` (Cinna decía ${pct(data.patas.el_cerebro_decia, 0)})` : ""}</span>
          </div>
          {Object.keys(data.por_tipo).length > 0 && (
            <div className="text-xs text-ink2">Por tipo: {Object.entries(data.por_tipo).map(([k, v]) => `${k} ${v.ganadas}/${v.patas} (Cinna ${pct(v.cerebro_decia, 0)})`).join(" · ")}</div>
          )}
          {data.pendientes_detalle.map((a) => (
            <div key={a.id} className="text-xs text-mute">Pendiente: {a.patas.join(" + ")} — sale {pct(a.prob_conjunta, 0)}</div>
          ))}
        </div>
      )}
    </section>
  );
}
