import Link from "next/link";
import { CinnaBun } from "@/components/brand";

export default function NotFound() {
  return (
    <div className="hero grid place-items-center gap-4 px-6 py-16 text-center">
      <CinnaBun size={96} mood="think" className="bob relative z-10" />
      <div className="relative z-10">
        <h1 className="font-display text-3xl font-semibold">Esta página se quedó en el horno</h1>
        <p className="mt-2 text-sm text-ink2">No encontramos lo que buscabas. Regresa a la semana y seguimos.</p>
      </div>
      <Link href="/" className="relative z-10 rounded-full bg-brand-fill px-5 py-2.5 text-sm font-bold text-on-brand">Volver a la semana</Link>
    </div>
  );
}
