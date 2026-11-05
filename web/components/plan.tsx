"use client";

import clsx from "clsx";
import { CalendarCheck, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { american, pct, useApi } from "@/lib/api";
import { Loading, SectionTitle } from "./ui";

type PlanLeg = { titulo: string; prob: number; momio: number | null; fuente: string; nota: string | null; nivel: string; game_label?: string;
  rival?: string | null; por_que?: string[]; kalshi?: number | null };
type Record = { semanas: number; patas: { ganadas: number; perdidas: number };
  perfiles: Record2 };
type Record2 = { [k: string]: { semanas: number; positivas: number; retorno_medio: number } };
type PlanParlay = { patas: string[]; prob: number; pago: number; apuesta: number; cobra_si_sale: number };
type Plan = {
  error?: string; semana?: number; perfil?: string; descripcion?: string; apuesta_total?: number; porcentaje_banca?: number;
  patas?: PlanLeg[]; parlays?: PlanParlay[]; prob_cobrar_algo?: number; prob_semana_en_positivo?: number; cobro_esperado?: number;
  historial?: { semanas: number; retorno_medio: number; semanas_positivas: number; banca_18_semanas_mediana: number; prob_perder: number;
    por_temporada?: { [s: string]: { semanas: number; positivas: number | null; retorno_medio: number | null } | null } } | null;
  precaucion?: { n: number; hit: number; activo: boolean; semanas: number } | null;
  alertas?: { id: string; at: string; texto: string; nivel: string }[];
  record_real?: Record;
  nota?: string;
};

const RIESGOS = [["sencillas", "Sencillas"], ["conservador", "Conservador"], ["medio", "Medio"], ["agresivo", "Agresivo"]] as const;

function money(x?: number) {
  return x == null ? "—" : `$${x.toLocaleString("es-MX", { maximumFractionDigits: 2 })}`;
}

export function PlanSemana() {
  const [banca, setBanca] = useState("1000");
  const [riesgo, setRiesgo] = useState<string>("conservador");
  useEffect(() => {                                   // recuerda la banca en este navegador
    try { const b = localStorage.getItem("plan_banca"); if (b) setBanca(b); } catch { /* sin almacenamiento */ }
  }, []);
  useEffect(() => { try { localStorage.setItem("plan_banca", banca); } catch { /* sin almacenamiento */ } }, [banca]);
  const b = Math.max(1, Number(banca.replace(/[^0-9.]/g, "")) || 1000);
  const { data, isLoading } = useApi<Plan>(`/api/plan?banca=${b}&riesgo=${riesgo}`, { revalidateOnFocus: false });

  return (
    <section className="card space-y-4 border-accent/40 p-5">
      <SectionTitle right={data?.semana ? <span className="text-xs text-mute">semana {data.semana}</span> : null}>
        <span className="inline-flex items-center gap-1.5"><CalendarCheck size={14} />Plan de la semana</span>
      </SectionTitle>
      <div className="flex flex-wrap items-end gap-4">
        <label className="text-xs text-mute">Tu banca total
          <input value={banca} onChange={(e) => setBanca(e.target.value)} inputMode="decimal"
            className="mt-1 block h-9 w-32 rounded-lg border border-line bg-s1 px-2 text-sm text-ink outline-none focus:border-accent tnum" />
        </label>
        <div className="text-xs text-mute">Perfil
          <div className="mt-1 flex rounded-lg bg-s2 p-0.5">
            {RIESGOS.map(([v, l]) => (
              <button key={v} onClick={() => setRiesgo(v)}
                className={clsx("rounded-md px-3 py-1.5 text-sm", riesgo === v ? "bg-s3 font-semibold text-ink" : "text-ink2")}>{l}</button>
            ))}
          </div>
        </div>
        {data?.descripcion && <p className="min-w-0 flex-1 text-xs text-ink2">{data.descripcion}</p>}
      </div>

      {isLoading || !data ? <Loading label="Armando el plan…" /> : data.error ? <p className="text-sm text-mute">{data.error}</p> : (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <div><div className="text-[11px] uppercase tracking-wider text-mute">Apuesta de la semana</div>
              <div className="text-xl font-bold tnum">{money(data.apuesta_total)}</div>
              <div className="text-xs text-mute">{pct(data.porcentaje_banca, 0)} de tu banca · {data.parlays?.length} parlays de {money(data.parlays?.[0]?.apuesta)}</div></div>
            <div><div className="text-[11px] uppercase tracking-wider text-mute">Cobras algo</div>
              <div className="text-xl font-bold tnum">{pct(data.prob_cobrar_algo, 0)}</div></div>
            <div><div className="text-[11px] uppercase tracking-wider text-mute">Semana en positivo</div>
              <div className={clsx("text-xl font-bold tnum", (data.prob_semana_en_positivo ?? 0) >= 0.5 ? "text-good" : "")}>{pct(data.prob_semana_en_positivo, 0)}</div></div>
            <div><div className="text-[11px] uppercase tracking-wider text-mute">Cobro esperado</div>
              <div className="text-xl font-bold tnum">{money(data.cobro_esperado)}</div>
              <div className="text-xs text-mute">por {money(data.apuesta_total)} apostados</div></div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-mute">Las patas (una por partido)</div>
              <ul className="space-y-1.5">
                {data.patas?.map((l) => (
                  <li key={l.titulo} className="text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-ink">{l.titulo} <span className="text-[11px] text-good">{l.nivel}</span></span>
                      <span className="shrink-0 tnum"><b>{pct(l.prob, 0)}</b> <span className="text-xs text-mute">{l.fuente} {american(l.momio)}</span>{l.kalshi != null && <span className={clsx("ml-1.5 text-[10px]", l.kalshi < 0.5 ? "text-warning" : "text-mute")} title="Lo que paga Kalshi (mercado con dinero real) por esta misma línea">K {pct(l.kalshi, 0)}</span>}</span>
                    </div>
                    {l.nota && <div className="flex items-start gap-1 text-[11px] text-warning"><Info size={11} className="mt-0.5 shrink-0" />{l.nota}</div>}
                    {(l.rival || (l.por_que?.length ?? 0) > 0) && (
                      <details className="mt-0.5 text-[11px] text-ink2">
                        <summary className="cursor-pointer text-mute hover:text-ink2">Por qué y contra quién</summary>
                        {l.rival && <div className={clsx("mt-0.5", l.rival.includes("a favor") ? "text-good" : l.rival.includes("en contra") ? "text-warning" : "")}>{l.rival}</div>}
                        {l.por_que?.map((f) => <div key={f} className={f.startsWith("Riesgo") ? "text-warning" : ""}>· {f}</div>)}
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-mute">Los parlays</div>
              <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
                {data.parlays?.map((p, i) => (
                  <li key={i} className="rounded-lg bg-s2/60 px-3 py-2 text-sm">
                    <div className="text-ink2">{p.patas.join(" + ")}</div>
                    <div className="mt-0.5 flex justify-between text-xs tnum">
                      <span>sale {pct(p.prob, 0)} · paga {p.pago}x</span>
                      <span>apuesta <b className="text-ink">{money(p.apuesta)}</b> → cobra <b className="text-good">{money(p.cobra_si_sale)}</b></span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {(data.alertas?.length ?? 0) > 0 && (
            <div className="space-y-1 rounded-lg border border-[var(--warning)]/40 px-4 py-2.5">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-warning">Avisos de tus patas</div>
              {data.alertas!.slice(0, 6).map((a) => (
                <div key={a.id} className={clsx("text-sm", a.nivel === "alerta" ? "text-critical" : "text-ink2")}>
                  <span className="text-[11px] text-mute">{new Date(a.at).toLocaleString("es-MX", { weekday: "short", hour: "2-digit", minute: "2-digit" })} · </span>{a.texto}
                </div>
              ))}
            </div>
          )}
          {data.precaucion?.activo && (
            <div className="rounded-lg bg-[var(--warning)]/15 px-4 py-2 text-sm text-warning">
              Modo precaución: las Élite van {pct(data.precaucion.hit, 0)} en las últimas {data.precaucion.semanas} semanas ({data.precaucion.n} picks).
              El plan apuesta la mitad hasta que se recuperen.
            </div>
          )}
          {data.historial && (
            <div className="rounded-lg border border-line px-4 py-3 text-xs text-ink2">
              <b className="text-ink">Historial honesto de este perfil</b> ({data.historial.semanas} semanas de todas las temporadas con líneas reales,
              cada una probada con un selector que no la vio): semanas en positivo {pct(data.historial.semanas_positivas, 0)}, retorno medio
              {" "}{data.historial.retorno_medio >= 0 ? "+" : ""}{Math.round(data.historial.retorno_medio * 100)}% de lo apostado por semana.
              Simulando 18 semanas con este % de banca: banca típica ×{data.historial.banca_18_semanas_mediana.toFixed(2)}, probabilidad de terminar
              perdiendo {pct(data.historial.prob_perder, 0)}.
              {data.historial.por_temporada && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {Object.entries(data.historial.por_temporada).map(([s, v]) => v && v.retorno_medio != null ? (
                    <span key={s} className={clsx("rounded-md px-2 py-0.5 tnum", v.retorno_medio >= 0 ? "bg-[var(--good)]/15 text-good" : "bg-[var(--critical)]/15 text-critical")}>
                      {s}: {v.retorno_medio >= 0 ? "+" : ""}{Math.round(v.retorno_medio * 100)}% / semana · {pct(v.positivas, 0)} en positivo{v.semanas < 10 ? ` (${v.semanas} sem.)` : ""}
                    </span>
                  ) : null)}
                </div>
              )}
              <div className="mt-1 text-mute">No todos los años funciona: en 2023 perdió y en 2024 quedó casi parejo. Apuesta poco y con disciplina.</div>
            </div>
          )}
          <div className="rounded-lg border border-line px-4 py-3 text-xs text-ink2">
            <b className="text-ink">Récord real del plan</b> (se guarda antes del primer partido y se califica solo):{" "}
            {data.record_real && data.record_real.semanas > 0 ? (
              <>{data.record_real.semanas} semanas · patas {data.record_real.patas.ganadas}–{data.record_real.patas.perdidas}
                {Object.entries(data.record_real.perfiles).map(([k, v]) => (
                  <span key={k}> · {k}: {v.positivas}/{v.semanas} semanas en positivo, {v.retorno_medio >= 0 ? "+" : ""}{Math.round(v.retorno_medio * 100)}% por semana</span>
                ))}</>
            ) : "empieza con esta semana; aquí verás cómo le fue de verdad a cada perfil."}
          </div>
          {data.nota && <p className="text-[11px] text-mute">{data.nota}</p>}
        </>
      )}
    </section>
  );
}
