"use client";

import { Crown, History, Link2, TrendingUp } from "lucide-react";
import { pct } from "@/lib/api";
import { CalibrationChart } from "./charts";
import { SectionTitle } from "./ui";

type Sel = { n: number; hit: number | null; roi?: number; momio_medio?: number } | null | undefined;
type SgpBlock = { n: number; real: number; independiente: number; cerebro: number; ll_independiente: number; ll_cerebro: number };
type Sgp = (SgpBlock & { se_ayudan?: SgpBlock; se_estorban?: SgpBlock }) | null | undefined;
export type RealLines = {
  resumen?: {
    elite_test?: Sel; super_test?: Sel; valor_test?: Sel; todas_test?: Sel;
    elite_cur?: Sel; super_cur?: Sel; valor_cur?: Sel; todas_cur?: Sel;
    elite_solo_test?: Sel; elite_solo_cur?: Sel; valor_no_elite_test?: Sel; valor_no_elite_cur?: Sel;
    clv?: { n: number; hacia_el_modelo: number } | null;
    parlays_test?: Record<string, { n: number; real: number; esperado: number }>;
    parlays_cur?: Record<string, { n: number; real: number; esperado: number }>;
    sgp_test?: Sgp; sgp_cur?: Sgp;
    alt_test?: Record<string, Sel> | null; alt_cur?: Record<string, Sel> | null;
    td_test?: Record<string, Sel> | null; td_cur?: Record<string, Sel> | null;
  } | null;
  n?: number; built?: string;
  calibracion?: Record<string, { lo: number; hi: number; n: number; pred: number; real: number }[] | null>;
  logloss?: Record<string, { test?: Record<string, number>; cur?: Record<string, number> }>;
  seasons?: { train: number; test: number; cur: number } | null;
};

const ROWS: [string, string][] = [
  ["todas", "Todas las líneas"], ["valor_no_elite", "Valor calculado, sin Élite (ya no se recomienda)"],
  ["elite_solo", "Élite → nivel Valor"], ["super", "Súper élite → nivel Seguro"],
];

export function RealLinesSection({ r }: { r: RealLines | null | undefined }) {
  const s = r?.resumen;
  if (!s) return null;
  const cell = (x: Sel) => (x && x.n ? (
    <div className="leading-tight">
      <div><b className="text-ink tnum">{pct(x.hit ?? 0, 1)}</b> <span className="text-xs text-mute tnum">({x.n.toLocaleString("es-MX")})</span></div>
      {x.roi != null && (
        <div className={x.roi >= 0.005 ? "text-[11px] font-semibold text-good tnum" : "text-[11px] text-mute tnum"}>
          retorno {x.roi >= 0 ? "+" : ""}{(x.roi * 100).toFixed(1)}%
        </div>
      )}
    </div>
  ) : "—");
  const sgp = s.sgp_test;
  const ss = r?.seasons ?? { train: 2024, test: 2025, cur: 2026 };
  const cal = r?.calibracion?.ou ?? [];
  return (
    <section className="space-y-4">
      <SectionTitle right={<span className="text-xs text-mute">{(r?.n ?? 0).toLocaleString("es-MX")} apuestas reales · líneas de cierre de 8 casas</span>}>
        Prueba con líneas reales ({ss.train}–{ss.cur})
      </SectionTitle>
      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[420px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
                <th className="px-5 py-2.5 font-medium">Más/Menos de jugadores</th>
                <th className="px-3 py-2.5 text-right font-medium">{ss.test} (nunca vista)</th>
                <th className="px-3 py-2.5 text-right font-medium">{ss.cur} (en curso)</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([k, label]) => (
                <tr key={k} className="border-b border-line last:border-0">
                  <td className="px-5 py-2.5">
                    <span className="inline-flex items-center gap-1.5">{k === "elite_solo" || k === "super" ? <Crown size={13} className="text-warning" /> : null}{label}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right">{cell(s[`${k}_test` as keyof typeof s] as Sel)}</td>
                  <td className="px-3 py-2.5 text-right">{cell(s[`${k}_cur` as keyof typeof s] as Sel)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-line px-5 py-3 text-xs text-ink2">
            Para ganarle a un momio de -110 se necesita acertar 52.4%. El retorno está medido al momio típico de una casa (no al
            mejor precio), por apuesta de 1 unidad. El modelo nunca vio esas temporadas al entrenarse. Sólo líneas del partido completo
            antes del kickoff (sin cuartos, mitades ni líneas en vivo).
          </p>
        </div>
        <div className="space-y-4">
          {s.clv && (
            <div className="card flex items-start gap-3 p-4">
              <TrendingUp size={18} className="mt-0.5 text-good" />
              <div className="text-sm text-ink2">
                <b className="text-ink">{pct(s.clv.hacia_el_modelo, 0)}</b> de las veces la línea se movió de la apertura al cierre
                hacia el lado de Cinna ({s.clv.n.toLocaleString("es-MX")} casos). Es la señal que usan los apostadores profesionales:
                Cinna anticipa al mercado.
              </div>
            </div>
          )}
          <div className="card p-4">
            <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><History size={15} /> Parlays de picks élite</div>
            {[[String(ss.test), s.parlays_test], [String(ss.cur), s.parlays_cur]].map(([y, v]) => v ? (
              <div key={y as string} className="flex flex-wrap gap-x-5 gap-y-1 py-1 text-xs text-ink2">
                <span className="w-10 font-semibold text-ink">{y as string}</span>
                {Object.entries(v as Record<string, { n: number; real: number; esperado: number }>).map(([k, x]) => (
                  <span key={k}>{k.replace("_picks", " picks")}: salió <b className="text-ink">{pct(x.real, 0)}</b> (esperado {pct(x.esperado, 0)}, {x.n})</span>
                ))}
              </div>
            ) : null)}
            <p className="mt-1 text-[11px] text-mute">Combinaciones de picks élite de partidos distintos, semana por semana.</p>
          </div>
          {sgp && sgp.n > 0 && (
            <div className="card p-4">
              <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><Link2 size={15} /> Parlays del mismo partido ({ss.test})</div>
              {([["Todos", sgp], ["Picks que se ayudan", sgp.se_ayudan], ["Picks que se estorban", sgp.se_estorban]] as [string, SgpBlock | undefined][])
                .filter(([, v]) => v && v.n > 0).map(([label, v]) => (
                  <div key={label} className="flex flex-wrap justify-between gap-x-4 border-b border-line py-1.5 text-xs text-ink2 last:border-0">
                    <span className="font-medium text-ink">{label} <span className="text-mute">({v!.n.toLocaleString("es-MX")})</span></span>
                    <span className="tnum">salió <b className="text-ink">{pct(v!.real, 1)}</b> · Cinna {pct(v!.cerebro, 1)} · si fueran independientes {pct(v!.independiente, 1)}</span>
                  </div>
                ))}
              <p className="mt-1.5 text-[11px] text-mute">
                Pares de picks de un mismo juego. Si Cinna está más cerca de lo que salió que el cálculo "independiente", sus correlaciones
                (QB↔WR, RB↔marcador…) funcionan y los parlays del mismo partido están bien calculados.
              </p>
            </div>
          )}
        </div>
      </div>
      {(s.alt_test || s.td_test) && (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-mute">
                <th className="px-5 py-2.5 font-medium">Escaleras y touchdowns</th>
                <th className="px-3 py-2.5 text-right font-medium">Escaleras {ss.test}</th>
                <th className="px-3 py-2.5 text-right font-medium">Escaleras {ss.cur}</th>
                <th className="px-3 py-2.5 text-right font-medium">TDs {ss.test}</th>
                <th className="px-3 py-2.5 text-right font-medium">TDs {ss.cur}</th>
              </tr>
            </thead>
            <tbody>
              {([["segura", "Seguras"], ["arriesgada", "Arriesgadas"], ["todas", "Todas"]] as [string, string][]).map(([k, label]) => (
                <tr key={k} className="border-b border-line last:border-0">
                  <td className="px-5 py-2.5">{label}</td>
                  <td className="px-3 py-2.5 text-right">{cell(s.alt_test?.[k])}</td>
                  <td className="px-3 py-2.5 text-right">{cell(s.alt_cur?.[k])}</td>
                  <td className="px-3 py-2.5 text-right">{cell(s.td_test?.[k])}</td>
                  <td className="px-3 py-2.5 text-right">{cell(s.td_cur?.[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-line px-5 py-3 text-xs text-ink2">
            En escaleras y TDs el % de acierto no dice mucho solo (un +250 acierta poco y aun así puede ganar dinero): lo que importa es el
            retorno. Medido al momio típico de una casa, sin buscar el mejor precio.
          </p>
        </div>
      )}
      {cal.length > 0 && (
        <div className="card p-5">
          <SectionTitle>Calibración con líneas reales (Más/Menos)</SectionTitle>
          <div className="grid gap-4 md:grid-cols-[1fr_1fr]">
            <CalibrationChart bins={cal.map((c) => ({ bin: `${Math.round(c.lo * 100)}–${Math.round(c.hi * 100)}%`, pred: c.pred, real: c.real, n: c.n }))} />
            <div className="text-sm text-ink2">
              <p>Cada punto es un grupo de picks: lo que Cinna decía contra lo que pasó. En vivo, la app ya muestra la probabilidad
                <b className="text-ink"> corregida con esta calibración</b>, así que un 60% significa 60% real.</p>
              <ul className="mt-3 space-y-1 text-xs">
                {cal.map((c) => (
                  <li key={c.lo} className="flex justify-between border-b border-line py-1 last:border-0">
                    <span>{Math.round(c.lo * 100)}–{Math.round(c.hi * 100)}%</span>
                    <span className="tnum">dice {pct(c.pred, 1)} · real <b className="text-ink">{pct(c.real, 1)}</b> · {c.n.toLocaleString("es-MX")}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
