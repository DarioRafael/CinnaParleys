"use client";

import type { Icon as PIcon } from "@phosphor-icons/react";
import clsx from "clsx";

/**
 * Íconos de CinnaParleys: Phosphor Icons (MIT) en estilo duotono, pintados con la paleta de la app:
 * contorno en el tono fuerte y relleno pastel. Cada sección tiene su tono para que se reconozca de un vistazo.
 */
export type Tone = "canela" | "rosa" | "cielo" | "menta" | "miel" | "lila";
export type { PIcon };

export function Duo({ icon: I, size = 22, tone = "canela", className }: { icon: PIcon; size?: number; tone?: Tone; className?: string }) {
  return <I size={size} weight="duotone" className={clsx("duo shrink-0", `tone-${tone}`, className)} aria-hidden="true" />;
}

/** Ícono dentro de su azulejo redondeado de color suave. */
export function IconTile({ icon, tone = "canela", size = 36, iconSize, className, iconClassName }: {
  icon: PIcon; tone?: Tone; size?: number; iconSize?: number; className?: string; iconClassName?: string;
}) {
  return (
    <span className={clsx("tile grid shrink-0 place-items-center", `tone-${tone}`, className)}
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.36) }}>
      <Duo icon={icon} tone={tone} size={iconSize ?? Math.round(size * 0.6)} className={iconClassName} />
    </span>
  );
}
