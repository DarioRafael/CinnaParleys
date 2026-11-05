"use client";

import clsx from "clsx";
import { Flame, Gem, ShieldCheck, type LucideIcon } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { TIER, Team, pct } from "@/lib/api";
import { CinnaBun, SwirlSpinner } from "./brand";
import { IconTile, PIcon, Tone } from "./icons";

export function TeamLogo({ team, size = 32, className }: { team?: Partial<Team> | null; size?: number; className?: string }) {
  const [err, setErr] = useState(false);
  if (!team?.logo || err) {
    return (
      <div
        className={clsx("grid place-items-center rounded-full bg-s3 text-[10px] font-bold text-ink2", className)}
        style={{ width: size, height: size }}
      >
        {team?.abbr ?? "?"}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={team.logo} alt={team.name ?? team.abbr} width={size} height={size} onError={() => setErr(true)}
      className={clsx("object-contain", className)} style={{ width: size, height: size }} />
  );
}

export function Headshot({ src, name, size = 40 }: { src?: string | null; name?: string; size?: number }) {
  const [err, setErr] = useState(false);
  const initials = (name ?? "?").split(" ").map((x) => x[0]).slice(0, 2).join("");
  return (
    <div className="shrink-0 overflow-hidden rounded-full bg-s3" style={{ width: size, height: size }}>
      {src && !err ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={name} className="h-full w-full object-cover object-top" onError={() => setErr(true)} />
      ) : (
        <div className="grid h-full w-full place-items-center text-xs font-semibold text-ink2">{initials}</div>
      )}
    </div>
  );
}

const TIER_ICON = { segura: ShieldCheck, valor: Gem, arriesgada: Flame } as const;

export function TierBadge({ tier, size = "sm" }: { tier?: string | null; size?: "sm" | "md" }) {
  if (!tier || !TIER[tier]) return null;
  const Icon = TIER_ICON[tier as keyof typeof TIER_ICON];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full font-semibold", TIER[tier].cls,
      size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs")}>
      <Icon size={size === "sm" ? 12 : 14} strokeWidth={2.4} />
      {TIER[tier].label}
    </span>
  );
}

/** Barra de probabilidad: el lado con ventaja en el color de acento, el otro en gris. */
export function WinBar({ left, right, pLeft, height = 8 }: { left: string; right: string; pLeft: number; height?: number }) {
  const lFav = pLeft >= 0.5;
  return (
    <div>
      <div className="flex overflow-hidden rounded-full" style={{ height, gap: 2 }}>
        <div className="rounded-l-full" style={{ width: `${pLeft * 100}%`, background: lFav ? "var(--accent)" : "var(--neutral-bar)" }} />
        <div className="rounded-r-full" style={{ width: `${(1 - pLeft) * 100}%`, background: !lFav ? "var(--accent)" : "var(--neutral-bar)" }} />
      </div>
      <div className="mt-1.5 flex justify-between text-xs tnum">
        <span className={lFav ? "font-semibold text-ink" : "text-mute"}>{left} {pct(pLeft)}</span>
        <span className={!lFav ? "font-semibold text-ink" : "text-mute"}>{pct(1 - pLeft)} {right}</span>
      </div>
    </div>
  );
}

/** Medidor horizontal 0–100% para probabilidades/confianza. */
export function Meter({ value, color = "var(--accent)", track = "var(--surface-3)", height = 6 }: {
  value: number; color?: string; track?: string; height?: number;
}) {
  return (
    <div className="w-full overflow-hidden rounded-full" style={{ height, background: track }}>
      <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
    </div>
  );
}

export function Stat({ label, value, sub, className }: { label: string; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={clsx("card px-4 py-3", className)}>
      <div className="text-xs font-semibold text-mute">{label}</div>
      <div className="mt-1 font-display text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink2">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[];
}) {
  return (
    <div className="inline-flex flex-wrap rounded-2xl border border-line bg-s2 p-1">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={clsx("flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-semibold transition-colors",
            value === o.value ? "bg-s1 text-ink shadow-[0_1px_0_var(--border),0_4px_10px_-6px_rgba(var(--shadow-color),0.35)]" : "text-ink2 hover:text-ink")}>
          {o.label}
          {o.count != null && <span className={clsx("rounded-full px-1.5 text-[11px] tnum", value === o.value ? "bg-brand-soft text-brand" : "bg-page/70 text-mute")}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function SectionTitle({ children, right, icon, tone = "canela" }: { children: ReactNode; right?: ReactNode; icon?: PIcon; tone?: Tone }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <h2 className="flex items-center gap-2 font-display text-[13px] font-medium uppercase tracking-[0.12em] text-ink2">
        {icon ? <IconTile icon={icon} tone={tone} size={26} className="-my-1" /> : <span className="h-2 w-2 rounded-full bg-pink" />}{children}
      </h2>
      {right}
    </div>
  );
}

/** Encabezado de cada página: título con carácter, ícono en masa de canela y su explicación. */
export function PageHeader({ icon: Icon, duo, tone = "canela", kicker, title, children, right }: {
  icon?: LucideIcon; duo?: PIcon; tone?: Tone; kicker?: ReactNode; title: ReactNode; children?: ReactNode; right?: ReactNode;
}) {
  return (
    <div className="hero px-5 py-5 md:px-7 md:py-6">
      <div className="relative z-10 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 max-w-3xl items-start gap-4">
          {duo ? (
            <span className="hidden rounded-[24px] bg-pill p-1.5 shadow-[0_10px_22px_-12px_rgba(var(--shadow-color),0.45)] ring-1 ring-[var(--border)] sm:block">
              <IconTile icon={duo} tone={tone} size={56} iconSize={32} iconClassName="float-a" />
            </span>
          ) : Icon && (
            <div className="hidden h-12 w-12 shrink-0 place-items-center rounded-2xl bg-brand-fill text-on-brand shadow-[0_8px_18px_-8px_var(--brand)] sm:grid">
              <Icon size={24} strokeWidth={2.2} />
            </div>
          )}
          <div className="min-w-0">
            {kicker && <div className="-rotate-1 font-hand text-[19px] font-semibold leading-none text-brand">{kicker}</div>}
            <h1 className="font-display text-[28px] font-semibold leading-tight tracking-tight text-ink md:text-[32px]">{title}</h1>
            {children && <div className="mt-1.5 space-y-1 text-sm leading-relaxed text-ink2">{children}</div>}
          </div>
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>
    </div>
  );
}

export function Empty({ children, mood = "sleepy" }: { children: ReactNode; mood?: "happy" | "think" | "sleepy" }) {
  return (
    <div className="card grid place-items-center gap-3 px-6 py-12 text-center text-sm text-ink2">
      <CinnaBun size={64} mood={mood} className="bob" />
      <div className="max-w-md">{children}</div>
    </div>
  );
}

const BAKING = ["Horneando datos…", "Amasando simulaciones…", "Glaseando probabilidades…", "Espolvoreando canela…"];

export function Loading({ label }: { label?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (label) return;
    const t = setInterval(() => setI((x) => (x + 1) % BAKING.length), 1600);
    return () => clearInterval(t);
  }, [label]);
  return (
    <div className="grid place-items-center gap-3 py-24 text-sm font-semibold text-mute">
      <SwirlSpinner size={34} />
      {label ?? BAKING[i]}
    </div>
  );
}

export function StatusPill({ status, detail, period, clock }: { status: string; detail?: string; period?: number; clock?: string }) {
  if (status === "in") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-critical/15 px-2 py-0.5 text-[11px] font-semibold text-critical">
        <span className="live-dot h-1.5 w-1.5 rounded-full bg-critical" /> EN VIVO {period ? `· Q${period}` : ""} {clock ?? ""}
      </span>
    );
  }
  if (status === "post") {
    return <span className="rounded-full bg-s3 px-2 py-0.5 text-[11px] font-semibold text-ink2">{detail?.includes("OT") ? "Final (TE)" : "Final"}</span>;
  }
  return null;
}

/** Número que sube contando cuando aparece (o cuando cambia). */
export function CountUp({ value, ms = 900 }: { value: number; ms?: number }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      setV(Math.round(value * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return <>{v}</>;
}
