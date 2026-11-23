// Cinna · escucha (corre dentro de la página). Sólo se activa en Playdoit / Team Mexico (o en sus marcos internos):
// cuando la página recibe los datos de un partido, guarda una copia y se la pasa a puente.js. No hace ninguna
// petición por su cuenta: la casa ya mandó esos datos a tu navegador para mostrártelos.
(() => {
  const CASAS = /playdoit|teammexico|biahosted|altenar/i;
  const anc = Array.from((location.ancestorOrigins && location.ancestorOrigins) || []);
  if (!CASAS.test(location.hostname) && !anc.some((o) => /playdoit|teammexico/i.test(o))) return;

  // cualquier respuesta del módulo de apuestas que traiga partidos de NFL (3281 = NFL en Playdoit)
  const interesa = (u) => /\/api\/widget\/|GetEventDetails|GetEvents/i.test(String(u || ""));
  const mandar = (url, txt) => {
    if (typeof txt !== "string" || txt.length < 50 || txt[0] !== "{" || txt.indexOf("3281") < 0) return;
    try { window.postMessage({ __cinna__: true, url: String(url), txt }, "*"); } catch (e) { /* nada */ }
  };

  const f0 = window.fetch;
  if (f0) {
    window.fetch = async function (...args) {
      const r = await f0.apply(this, args);
      try {
        const u = args[0] && typeof args[0] === "object" && "url" in args[0] ? args[0].url : args[0];
        if (interesa(u)) r.clone().text().then((t) => mandar(u, t)).catch(() => {});
      } catch (e) { /* nada */ }
      return r;
    };
  }

  const open0 = XMLHttpRequest.prototype.open;
  const send0 = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u, ...resto) {
    this.__cinnaUrl = u;
    return open0.call(this, m, u, ...resto);
  };
  XMLHttpRequest.prototype.send = function (...a) {
    if (interesa(this.__cinnaUrl)) {
      this.addEventListener("load", () => {
        try {
          const t = this.responseType === "" || this.responseType === "text" ? this.responseText : JSON.stringify(this.response);
          mandar(this.__cinnaUrl, t);
        } catch (e) { /* nada */ }
      });
    }
    return send0.apply(this, a);
  };
})();
