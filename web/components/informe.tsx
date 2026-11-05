"use client";

import clsx from "clsx";
import { Anchor, FlaskConical, Lightbulb, ShieldAlert, Users } from "lucide-react";
import { useApi } from "@/lib/api";
import { Loading, SectionTitle } from "./ui";

type Unidad = { titulares: number; fuera: string[]; duda: string[] };
type Angulo = { angulo: string; evidencia: string; por_que: string; piernas_a_revisar?: string[] };
export type Informe = {
  partido: string; aviso?: string;
  lectura?: { favorito: string; prob_ganar: string; marcador_cerebro: string; total_cerebro: number; total_mercado: number | null;
    spread_mercado: string | null; cerebro_vs_mercado?: { margen_local_pts: number; total_pts: number | null } };
  unidades?: { equipos: Record<string, Record<string, Unidad> | string>; notas: string[]; ajuste_aplicado_pts: Record<string, number | null> };
  bajas_ofensivas?: Record<string, { jugador: string; estado: string; prob_juega: string; detalle: string }[]>;
  quien_absorbe_el_volumen?: Record<string, { jugador: string; sube: string; linea?: { stat: string; proyeccion: number; linea: number | null } | null }[]>;
  qbs?: Record<string, { titular: string; prob_juega: string; motivo: string | null }>;
  plan_de_juego?: string[];
  picks_elite?: { pick: string; nivel: string; prob: string; mercado: string; momio: string | null }[];
  angulos_para_parlays?: Angulo[];
  como_leer?: string;
  si_va_perdiendo_o_ganando_al_medio?: Record<string, string[]>;
};

const EVID: Record<string, { label: string; cls: string; icon: typeof Anchor }> = {
  validado: { label: "Validado", cls: "bg-[var(--good)]/15 text-good", icon: Anchor },
  modelo: { label: "Modelo", cls: "bg-accent/15 text-accent", icon: FlaskConical },
  contexto: { label: "Contexto", cls: "bg-s3 text-ink2", icon: Lightbulb },
};

function Evid({ e }: { e: string }) {
  const k = e.startsWith("validado") ? "validado" : e.startsWith("modelo") ? "modelo" : "contexto";
  const v = EVID[k];
  const Icon = v.icon;
  return <span title={e} className={clsx("inline-flex h-fit shrink-0 items-center gap-1 self-start rounded-md px-2 py-0.5 text-[11px] font-semibold", v.cls)}><Icon size={12} />{v.label}</span>;
}

export function InformePanel({ id }: { id: string }) {
  const { data, isLoading } = useApi<Informe>(`/api/informe/${id}`);
  if (isLoading || !data) return <Loading label="Armando el informe…" />;
  if (data.aviso) return <div className="card p-5 text-sm text-mute">{data.aviso}</div>;
  const L = data.lectura;
  const teams = Object.keys(data.unidades?.equipos ?? {});
  return (
    <div className="space-y-5">
      {L && (
        <div className="card grid gap-3 p-5 text-sm sm:grid-cols-4">
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Favorito</div>
            <div className="font-semibold">{L.favorito} {L.prob_ganar}</div><div className="text-xs text-mute">{L.marcador_cerebro}</div></div>
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Mercado</div>
            <div className="font-semibold">{L.spread_mercado ?? "—"} · total {L.total_mercado ?? "—"}</div></div>
          <div><div className="text-[11px] uppercase tracking-wider text-mute">Cinna vs mercado</div>
            <div className="font-semibold tnum">{L.cerebro_vs_mercado ? `${L.cerebro_vs_mercado.margen_local_pts > 0 ? "+" : ""}${L.cerebro_vs_mercado.margen_local_pts} pts margen local` : "—"}</div>
            {L.cerebro_vs_mercado?.total_pts != null && <div className="text-xs text-mute">{L.cerebro_vs_mercado.total_pts > 0 ? "+" : ""}{L.cerebro_vs_mercado.total_pts} pts en el total</div>}</div>
          <div><div className="text-[11px] uppercase tracking-wider text-mute">QBs</div>
            {Object.entries(data.qbs ?? {}).map(([t, q]) => <div key={t} className="text-ink2"><b className="text-ink">{t}</b> {q.titular}{q.prob_juega !== "100%" ? ` (${q.prob_juega})` : ""}</div>)}</div>
        </div>
      )}

      <div className="card p-4">
        <SectionTitle right={<span className="text-xs text-mute">OL · DL · LB · CB · S</span>}>Salud de cada unidad</SectionTitle>
        <div className="grid gap-4 md:grid-cols-2">
          {teams.map((t) => {
            const u = data.unidades!.equipos[t];
            const adj = data.unidades!.ajuste_aplicado_pts?.[t];
            return (
              <div key={t}>
                <div className="mb-1.5 flex items-center justify-between text-sm font-semibold">{t}
                  {adj ? <span className="rounded-md bg-[var(--good)]/15 px-2 py-0.5 text-[11px] text-good">+{adj.toFixed(1)} pts por CB rival fuera</span> : null}</div>
                {typeof u === "string" ? <div className="text-sm text-mute">Unidades completas: sin titulares fuera ni en duda.</div> : (
                  <ul className="space-y-1.5 text-sm">
                    {Object.entries(u).map(([g, x]) => (
                      <li key={g}><span className="text-ink2">{g}</span> <span className="text-xs text-mute">({x.titulares} titulares)</span>
                        {x.fuera.map((n) => <div key={n} className="ml-3 text-critical">Fuera: {n}</div>)}
                        {x.duda.map((n) => <div key={n} className="ml-3 text-warning">Duda: {n}</div>)}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
        {!!data.unidades?.notas.length && <ul className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-ink2">
          {data.unidades.notas.map((n) => <li key={n}>• {n}</li>)}</ul>}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-4">
          <SectionTitle>Bajas ofensivas</SectionTitle>
          {Object.entries(data.bajas_ofensivas ?? {}).map(([t, lst]) => (
            <div key={t} className="mb-2">
              <div className="text-xs font-semibold text-mute">{t}</div>
              {lst.length ? lst.map((b) => (
                <div key={b.jugador} className="text-sm"><span className="text-ink">{b.jugador}</span> <span className="text-warning">{b.estado} · juega {b.prob_juega}</span>
                  {b.detalle && <div className="text-xs text-mute">{b.detalle}</div>}</div>
              )) : <div className="text-sm text-mute">Sin bajas.</div>}
            </div>
          ))}
        </div>
        <div className="card p-4">
          <SectionTitle><span className="inline-flex items-center gap-1.5"><Users size={14} />Quién absorbe el volumen</span></SectionTitle>
          {Object.keys(data.quien_absorbe_el_volumen ?? {}).length ? Object.entries(data.quien_absorbe_el_volumen!).map(([t, lst]) => (
            <div key={t} className="mb-2">
              <div className="text-xs font-semibold text-mute">{t}</div>
              {lst.map((x) => (
                <div key={x.jugador} className="text-sm"><span className="text-ink">{x.jugador}</span> <span className="text-good">{x.sube}</span>
                  {x.linea && <div className="text-xs text-mute">{x.linea.stat}: proyección {x.linea.proyeccion} vs línea {x.linea.linea ?? "—"}</div>}</div>
              ))}
            </div>
          )) : <div className="text-sm text-mute">Nadie hereda volumen relevante esta semana.</div>}
        </div>
      </div>

      <div className="card p-4">
        <SectionTitle right={<span className="text-xs text-mute">cada ángulo trae su evidencia</span>}>
          <span className="inline-flex items-center gap-1.5"><ShieldAlert size={14} />Ángulos para parlays</span></SectionTitle>
        <ul className="space-y-3">
          {(data.angulos_para_parlays ?? []).map((a, i) => (
            <li key={i} className="flex gap-3">
              <Evid e={a.evidencia} />
              <div className="text-sm"><div className="text-ink">{a.angulo}</div>
                <div className="text-xs text-mute">{a.por_que}</div>
                {a.piernas_a_revisar?.map((l) => <div key={l} className="text-xs text-ink2">→ {l}</div>)}</div>
            </li>
          ))}
        </ul>
        {data.como_leer && <p className="mt-3 border-t border-line pt-2 text-[11px] text-mute">{data.como_leer}</p>}
      </div>

      {data.si_va_perdiendo_o_ganando_al_medio && (
        <div className="card p-4">
          <SectionTitle>¿Y si va perdiendo o ganando al medio tiempo?</SectionTitle>
          <div className="grid gap-4 md:grid-cols-2">
            {Object.entries(data.si_va_perdiendo_o_ganando_al_medio).map(([t, rows]) => (
              <div key={t}><div className="mb-1 text-xs font-semibold text-mute">{t}</div>
                <ul className="space-y-0.5 text-sm text-ink2">{rows.map((r) => <li key={r}>{r}</li>)}</ul></div>
            ))}
          </div>
        </div>
      )}

      {!!data.plan_de_juego?.length && (
        <div className="card p-4">
          <SectionTitle right={<span className="text-xs text-mute">descriptivo</span>}>Plan de juego (esquema)</SectionTitle>
          <ul className="space-y-1 text-sm text-ink2">{data.plan_de_juego.map((x) => <li key={x}>• {x}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
