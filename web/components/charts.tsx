"use client";

import { RefObject, useEffect, useMemo, useRef, useState } from "react";

/* Gráficas SVG ligeras: marcas delgadas, rejilla fina, tooltip al pasar el cursor.
   El texto usa tokens de texto (nunca el color de la serie). */

type Tip = { x: number; y: number; lines: [string, string][] } | null;

/** Ancho real del contenedor: el SVG se dibuja a escala 1:1 para que el texto siempre sea legible. */
function useWidth(ref: RefObject<HTMLDivElement | null>, fallback = 560) {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((e) => setW(Math.max(240, Math.round(e[0].contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}


function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg border border-line bg-s1 px-2.5 py-1.5 text-xs shadow-xl"
      style={{ left: tip.x, top: tip.y - 8 }}>
      {tip.lines.map(([v, l], i) => (
        <div key={i} className="whitespace-nowrap">
          <span className="font-semibold text-ink tnum">{v}</span> <span className="text-mute">{l}</span>
        </div>
      ))}
    </div>
  );
}

function niceTicks(lo: number, hi: number, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

/** Distribución discreta (margen o total de puntos) con la línea del mercado. */
export function PmfChart({ pmf, lo, hi, line, mu, height = 170, overLabel = "Más", underLabel = "Menos", fmtX = (v: number) => `${v}` }: {
  pmf: { min: number; p: number[] }; lo: number; hi: number; line?: number | null; mu?: number; height?: number;
  overLabel?: string; underLabel?: string; fmtX?: (v: number) => string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const W = useWidth(ref), H = height, padL = 34, padR = 10, padT = 10, padB = 24;
  const [tip, setTip] = useState<Tip>(null);
  const vals = useMemo(() => {
    const out: { x: number; p: number }[] = [];
    for (let x = lo; x <= hi; x++) {
      const i = x - pmf.min;
      out.push({ x, p: i >= 0 && i < pmf.p.length ? pmf.p[i] : 0 });
    }
    return out;
  }, [pmf, lo, hi]);
  const maxP = Math.max(...vals.map((v) => v.p), 0.01);
  const n = vals.length;
  const bw = (W - padL - padR) / n;
  const barW = Math.min(24, Math.max(1.5, bw - 2));
  const sx = (x: number) => padL + (x - lo) * bw + bw / 2;
  const sy = (p: number) => padT + (H - padT - padB) * (1 - p / maxP);
  const yTicks = niceTicks(0, maxP, 3);
  const xTicks = niceTicks(lo, hi, 8).filter((t) => Number.isInteger(t));
  const pOver = line != null ? vals.filter((v) => v.x > line).reduce((a, b) => a + b.p, 0) : null;

  return (
    <div ref={ref} className="relative" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img">
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={padL - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="var(--text-muted)">{(t * 100).toFixed(0)}%</text>
          </g>
        ))}
        {vals.map((v) => {
          const x = sx(v.x) - barW / 2, y = sy(v.p), h = Math.max(0, H - padB - y);
          const over = line != null ? v.x > line : true;
          const r = Math.min(4, barW / 2, h);
          return (
            <path key={v.x}
              d={`M${x},${H - padB} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + barW - r},${y} Q${x + barW},${y} ${x + barW},${y + r} L${x + barW},${H - padB} Z`}
              fill={over ? "var(--accent)" : "var(--neutral-bar)"}
              onMouseMove={(e) => {
                const b = ref.current!.getBoundingClientRect();
                setTip({ x: e.clientX - b.left, y: e.clientY - b.top, lines: [[`${(v.p * 100).toFixed(1)}%`, fmtX(v.x)]] });
              }} />
          );
        })}
        <line x1={padL} x2={W - padR} y1={H - padB} y2={H - padB} stroke="var(--axis)" strokeWidth={1} />
        {xTicks.map((t) => (
          <text key={t} x={sx(t)} y={H - 8} textAnchor="middle" fontSize={10} fill="var(--text-muted)">{fmtX(t)}</text>
        ))}
        {line != null && (
          <g>
            <line x1={sx(line)} x2={sx(line)} y1={padT} y2={H - padB} stroke="var(--text-secondary)" strokeWidth={1.5} />
            <text x={sx(line) + 4} y={padT + 10} fontSize={10.5} fill="var(--text-secondary)">línea {fmtX(line)}</text>
          </g>
        )}
        {mu != null && <circle cx={sx(Math.round(mu))} cy={H - padB} r={4.5} fill="var(--text-primary)" stroke="var(--surface-1)" strokeWidth={2} />}
      </svg>
      {pOver != null && (
        <div className="mt-1 flex justify-between text-xs text-ink2">
          <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-[var(--neutral-bar)]" />{underLabel}: <b className="text-ink tnum">{((1 - pOver) * 100).toFixed(1)}%</b></span>
          <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-accent" />{overLabel}: <b className="text-ink tnum">{(pOver * 100).toFixed(1)}%</b></span>
        </div>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

/** Rango proyectado de un jugador (10-90% y 25-75%) con marcadores de líneas. */
export function RangeStrip({ q, mu, lines = [], unit = "", height = 64 }: {
  q: number[]; mu: number; lines?: { value: number; label: string; strong?: boolean }[]; unit?: string; height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const W = useWidth(ref, 520), H = height, pad = 14;
  const hi = Math.max(q[4], ...lines.map((l) => l.value), mu) * 1.12 + 0.5;
  const lo = 0;
  const sx = (v: number) => pad + ((v - lo) / (hi - lo)) * (W - 2 * pad);
  const cy = 26;
  const ticks = niceTicks(lo, hi, 5);
  return (
    <div ref={ref}>
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={sx(t)} x2={sx(t)} y1={10} y2={H - 16} stroke="var(--grid)" strokeWidth={1} />
          <text x={sx(t)} y={H - 3} textAnchor="middle" fontSize={10} fill="var(--text-muted)">{t}</text>
        </g>
      ))}
      <rect x={sx(q[0])} y={cy - 7} width={Math.max(2, sx(q[4]) - sx(q[0]))} height={14} rx={7} fill="var(--accent)" opacity={0.22} />
      <rect x={sx(q[1])} y={cy - 7} width={Math.max(2, sx(q[3]) - sx(q[1]))} height={14} rx={7} fill="var(--accent)" opacity={0.55} />
      <circle cx={sx(mu)} cy={cy} r={5.5} fill="var(--accent)" stroke="var(--surface-1)" strokeWidth={2} />
      {lines.map((l, i) => (
        <g key={i}>
          <line x1={sx(l.value)} x2={sx(l.value)} y1={cy - 15} y2={cy + 15} stroke={l.strong ? "var(--text-primary)" : "var(--text-secondary)"} strokeWidth={l.strong ? 2 : 1.25} />
          <text x={sx(l.value)} y={cy - 18} textAnchor="middle" fontSize={10} fill="var(--text-secondary)">{l.label}</text>
        </g>
      ))}
      <title>{`Proyección ${mu.toFixed(1)} ${unit}; 80% entre ${q[0].toFixed(0)} y ${q[4].toFixed(0)}`}</title>
    </svg>
    </div>
  );
}

/** Últimos partidos vs una línea: columnas por encima en acento, por debajo en gris. */
export function LogBars({ items, line, height = 150, unit = "" }: {
  items: { label: string; sub?: string; value: number | null }[]; line?: number | null; height?: number; unit?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const W = useWidth(ref), H = height, padL = 30, padR = 8, padT = 12, padB = 30;
  const [tip, setTip] = useState<Tip>(null);
  const vals = items.map((i) => i.value ?? 0);
  const maxV = Math.max(...vals, line ?? 0, 1) * 1.1;
  const n = Math.max(items.length, 1);
  const bw = (W - padL - padR) / n;
  const barW = Math.min(24, bw - 6);
  const sy = (v: number) => padT + (H - padT - padB) * (1 - v / maxV);
  const ticks = niceTicks(0, maxV, 3);
  return (
    <div ref={ref} className="relative" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={padL - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="var(--text-muted)">{t}</text>
          </g>
        ))}
        {items.map((it, i) => {
          const v = it.value ?? 0;
          const cx = padL + i * bw + bw / 2, x = cx - barW / 2, y = sy(v), h = Math.max(0, H - padB - y);
          const over = line != null ? v > line : true;
          const r = Math.min(4, barW / 2, h);
          return (
            <g key={i} onMouseMove={(e) => {
              const b = ref.current!.getBoundingClientRect();
              setTip({ x: e.clientX - b.left, y: e.clientY - b.top, lines: [[`${it.value ?? "—"} ${unit}`, `${it.label} ${it.sub ?? ""}`]] });
            }}>
              <rect x={cx - bw / 2} y={padT} width={bw} height={H - padT - padB} fill="transparent" />
              {h > 0 && (
                <path d={`M${x},${H - padB} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + barW - r},${y} Q${x + barW},${y} ${x + barW},${y + r} L${x + barW},${H - padB} Z`}
                  fill={over ? "var(--accent)" : "var(--neutral-bar)"} />
              )}
              <text x={cx} y={H - 16} textAnchor="middle" fontSize={9.5} fill="var(--text-muted)">{it.label}</text>
              {it.sub && <text x={cx} y={H - 5} textAnchor="middle" fontSize={9} fill="var(--text-muted)">{it.sub}</text>}
            </g>
          );
        })}
        <line x1={padL} x2={W - padR} y1={H - padB} y2={H - padB} stroke="var(--axis)" strokeWidth={1} />
        {line != null && (
          <g>
            <line x1={padL} x2={W - padR} y1={sy(line)} y2={sy(line)} stroke="var(--text-secondary)" strokeWidth={1.5} />
            <text x={W - padR} y={sy(line) - 4} textAnchor="end" fontSize={10} fill="var(--text-secondary)">línea {line}</text>
          </g>
        )}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

/** Evolución de una probabilidad en el tiempo (con cruz que sigue al cursor). */
export function ProbLine({ points, label, height = 140 }: { points: { t: string; p: number }[]; label: string; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const W = useWidth(ref), H = height, padL = 34, padR = 10, padT = 10, padB = 22;
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return <div className="py-6 text-center text-xs text-mute">Aún no hay suficiente historial de cambios.</div>;
  const ts = points.map((p) => new Date(p.t).getTime());
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  const ps = points.map((p) => p.p);
  const lo = Math.max(0, Math.min(...ps) - 0.05), hi = Math.min(1, Math.max(...ps) + 0.05);
  const sx = (t: number) => padL + ((t - t0) / (t1 - t0 || 1)) * (W - padL - padR);
  const sy = (p: number) => padT + (H - padT - padB) * (1 - (p - lo) / (hi - lo || 1));
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(ts[i])},${sy(p.p)}`).join(" ");
  const ticks = niceTicks(lo, hi, 3);
  const onMove = (e: React.MouseEvent) => {
    const b = ref.current!.getBoundingClientRect();
    const x = ((e.clientX - b.left) / b.width) * W;
    let best = 0;
    ts.forEach((t, i) => { if (Math.abs(sx(t) - x) < Math.abs(sx(ts[best]) - x)) best = i; });
    setHover(best);
  };
  const hv = hover != null ? points[hover] : null;
  return (
    <div ref={ref} className="relative" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={padL - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="var(--text-muted)">{(t * 100).toFixed(0)}%</text>
          </g>
        ))}
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={sx(ts[ts.length - 1])} cy={sy(ps[ps.length - 1])} r={4} fill="var(--accent)" stroke="var(--surface-1)" strokeWidth={2} />
        {hv && hover != null && (
          <g>
            <line x1={sx(ts[hover])} x2={sx(ts[hover])} y1={padT} y2={H - padB} stroke="var(--axis)" strokeWidth={1} />
            <circle cx={sx(ts[hover])} cy={sy(hv.p)} r={4} fill="var(--accent)" stroke="var(--surface-1)" strokeWidth={2} />
          </g>
        )}
      </svg>
      {hv && hover != null && (
        <Tooltip tip={{ x: sx(ts[hover]), y: 20,
          lines: [[`${(hv.p * 100).toFixed(1)}%`, label], [new Date(hv.t).toLocaleString("es-MX", { weekday: "short", hour: "numeric", minute: "2-digit" }), ""]] }} />
      )}
    </div>
  );
}

/** Calibración: lo que Cinna dijo vs lo que pasó. */
export function CalibrationChart({ bins, height = 240 }: { bins: { bin: string; pred: number; real: number; n: number }[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const W = Math.min(useWidth(ref, 360), 520), H = height, pad = 36;
  const [tip, setTip] = useState<Tip>(null);
  const lo = 0.3, hi = 0.9;
  const s = (v: number) => (v - lo) / (hi - lo);
  const sx = (v: number) => pad + s(v) * (W - pad - 10);
  const sy = (v: number) => H - pad + 10 - s(v) * (H - pad - 10);
  const ticks = [0.3, 0.5, 0.7, 0.9];
  return (
    <div ref={ref} className="relative" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad} x2={W - 10} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
            <line x1={sx(t)} x2={sx(t)} y1={10} y2={H - pad + 10} stroke="var(--grid)" strokeWidth={1} />
            <text x={pad - 6} y={sy(t) + 3} textAnchor="end" fontSize={10} fill="var(--text-muted)">{t * 100}%</text>
            <text x={sx(t)} y={H - pad + 24} textAnchor="middle" fontSize={10} fill="var(--text-muted)">{t * 100}%</text>
          </g>
        ))}
        <line x1={sx(lo)} y1={sy(lo)} x2={sx(hi)} y2={sy(hi)} stroke="var(--axis)" strokeWidth={1.5} />
        {bins.map((b, i) => {
          const r = 4 + Math.min(6, Math.sqrt(b.n) / 3);
          return (
            <g key={i} onMouseMove={(e) => {
              const bb = ref.current!.getBoundingClientRect();
              setTip({ x: e.clientX - bb.left, y: e.clientY - bb.top, lines: [[`${(b.real * 100).toFixed(0)}% real`, `dijo ${(b.pred * 100).toFixed(0)}%`], [`${b.n}`, "picks"]] });
            }}>
              <circle cx={sx(Math.min(hi, Math.max(lo, b.pred)))} cy={sy(Math.min(hi, Math.max(lo, b.real)))} r={12} fill="transparent" />
              <circle cx={sx(Math.min(hi, Math.max(lo, b.pred)))} cy={sy(Math.min(hi, Math.max(lo, b.real)))} r={r}
                fill="var(--accent)" stroke="var(--surface-1)" strokeWidth={2} />
            </g>
          );
        })}
        <text x={W / 2 + 10} y={H - 2} textAnchor="middle" fontSize={10.5} fill="var(--text-secondary)">Probabilidad que dio Cinna</text>
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
