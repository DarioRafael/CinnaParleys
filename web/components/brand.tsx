"use client";

import clsx from "clsx";
import { useId } from "react";

/** Logo de CinnaParleys: un balón-rol de canela (espiral de glaseado en lugar de costuras). */
export function CinnaLogo({ size = 40, className }: { size?: number; className?: string }) {
  const id = `cp-bun-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} className={className} aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0.1" y1="0.1" x2="0.9" y2="0.9">
          <stop offset="0" stopColor="#f2b679" />
          <stop offset="0.55" stopColor="#d9783f" />
          <stop offset="1" stopColor="#a9502a" />
        </linearGradient>
      </defs>
      <g transform="rotate(-32 24 24)">
        <ellipse cx="24" cy="24" rx="20.5" ry="13.5" fill={`url(#${id})`} />
        <path d="M10.2 14.6 Q7.6 24 10.2 33.4" fill="none" stroke="#fff7ee" strokeOpacity="0.9" strokeWidth="2" strokeLinecap="round" />
        <path d="M37.8 14.6 Q40.4 24 37.8 33.4" fill="none" stroke="#fff7ee" strokeOpacity="0.9" strokeWidth="2" strokeLinecap="round" />
        <path d="M22.5 24 A1.5 1.5 0 0 1 25.5 24 A3 3 0 0 1 19.5 24 A4.5 4.5 0 0 1 28.5 24 A6 6 0 0 1 16.5 24 A7.5 7.5 0 0 1 31.5 24"
          fill="none" stroke="#fff7ee" strokeWidth="2.4" strokeLinecap="round" />
      </g>
      <path d="M8 4.6c1.2-1.6 3.8-.7 3.4 1.4-.3 1.6-2.2 2.7-3.4 3.7-1.2-1-3.1-2.1-3.4-3.7-.4-2.1 2.2-3 3.4-1.4z" fill="#ef8fa9" />
    </svg>
  );
}

export type Mood = "happy" | "think" | "sleepy" | "wow";

/** Cinna: la mascota (un rol de canela con cara). mood cambia ojos y boca; parpadea sola. */
export function CinnaBun({ size = 72, mood = "happy", className }: { size?: number; mood?: Mood; className?: string }) {
  const id = `cb-body-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 80 80" width={size} height={size} className={className} aria-hidden="true">
      <defs>
        <radialGradient id={id} cx="0.4" cy="0.35" r="0.75">
          <stop offset="0" stopColor="#f6c48e" />
          <stop offset="0.6" stopColor="#e09456" />
          <stop offset="1" stopColor="#b8612f" />
        </radialGradient>
      </defs>
      <ellipse cx="40" cy="72" rx="22" ry="3.5" fill="#3a2318" opacity="0.12" />
      <path d="M12 44c0-17 12.5-30 28-30s28 13 28 30c0 13-12 24-28 24S12 57 12 44z" fill={`url(#${id})`} />
      {/* espiral de canela */}
      <path d="M40 32 A2.4 2.4 0 0 1 44.8 32 A4.2 4.2 0 0 1 36.4 32 A6 6 0 0 1 48.4 32 A7.8 7.8 0 0 1 32.8 32 A9.6 9.6 0 0 1 52 32"
        fill="none" stroke="#9b4a22" strokeOpacity="0.55" strokeWidth="2.6" strokeLinecap="round" />
      {/* glaseado */}
      <path d="M20 26c4-7 12-11 20-11s16 4 20 11c-2 3-4 1-6 4-2 3-5 0-7 3-2 2-5-1-7 1-2 2-5-2-7 0-3 2-5-2-7-1-3 1-4-4-6-7z"
        fill="#fff6ee" opacity="0.92" />
      {/* cara */}
      {mood === "sleepy" ? (
        <>
          <path d="M28 49q3 2.5 6 0" stroke="#3a2318" strokeWidth="2.2" fill="none" strokeLinecap="round" />
          <path d="M46 49q3 2.5 6 0" stroke="#3a2318" strokeWidth="2.2" fill="none" strokeLinecap="round" />
        </>
      ) : (
        <g className="blink">
          <ellipse cx="31" cy="48" rx={mood === "wow" ? 3 : 2.6} ry={mood === "wow" ? 3.6 : 3.1} fill="#3a2318" />
          <ellipse cx="49" cy="48" rx={mood === "wow" ? 3 : 2.6} ry={mood === "wow" ? 3.6 : 3.1} fill="#3a2318" />
          <circle cx="32" cy="46.8" r="0.9" fill="#fff" />
          <circle cx="50" cy="46.8" r="0.9" fill="#fff" />
        </g>
      )}
      <ellipse cx="24.5" cy="54" rx="4" ry="2.4" fill="#ef8fa9" opacity="0.75" />
      <ellipse cx="55.5" cy="54" rx="4" ry="2.4" fill="#ef8fa9" opacity="0.75" />
      {mood === "think" ? (
        <path d="M37 56.5h6" stroke="#3a2318" strokeWidth="2.2" strokeLinecap="round" />
      ) : mood === "wow" ? (
        <ellipse cx="40" cy="56.5" rx="3" ry="3.4" fill="#3a2318" />
      ) : (
        <path d="M36 54.5q4 4 8 0" stroke="#3a2318" strokeWidth="2.2" fill="none" strokeLinecap="round" />
      )}
    </svg>
  );
}

/** Nombre de la marca con tipografía display. */
export function Wordmark({ className, small }: { className?: string; small?: boolean }) {
  return (
    <span className={clsx("font-display font-semibold leading-none tracking-tight", small ? "text-lg" : "text-[22px]", className)}>
      <span className="text-ink">Cinna</span><span className="text-brand">Parleys</span>
    </span>
  );
}

/** Espiral de canela girando (para cargas). */
export function SwirlSpinner({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className="swirl-spin" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="var(--brand-soft)" />
      <path d="M16 16 A1.8 1.8 0 0 1 19.6 16 A3.2 3.2 0 0 1 13.2 16 A4.6 4.6 0 0 1 22.4 16 A6 6 0 0 1 10.4 16 A7.4 7.4 0 0 1 25.2 16"
        fill="none" stroke="var(--brand)" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}
