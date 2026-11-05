// Genera los íconos Phosphor (duotono, con la paleta de CinnaParleys) como SVG para la presentación UML.
// Uso: node iconos.cjs   (los SVG quedan en ./assets; luego build_deck.py los pasa a PNG)
const path = require("path");
const fs = require("fs");
const { createRequire } = require("module");

const web = path.resolve(__dirname, "../../web/package.json");
const req = createRequire(web);
const React = req("react");
const { renderToStaticMarkup } = req("react-dom/server");
const { pathToFileURL } = require("url");
const SSR = path.resolve(__dirname, "../../web/node_modules/@phosphor-icons/react/dist/ssr");

// tono -> [contorno, relleno]  (los mismos de la app)
const TONOS = {
  canela: ["#a8501f", "#f6c99c"], rosa: ["#c0436c", "#f9b8ca"], cielo: ["#2a6fb0", "#b5d8f5"],
  menta: ["#1f7a4d", "#aee3c4"], miel: ["#946200", "#f7d78a"], lila: ["#6d4fb8", "#d2c4f4"],
  crema: ["#fff3e6", "#e9a35f"],
};

const ICONOS = [
  ["UsersThree", "rosa"], ["TreeStructure", "canela"], ["FlowArrow", "menta"], ["ArrowsLeftRight", "cielo"],
  ["ArrowsClockwise", "lila"], ["Target", "rosa"], ["Ticket", "miel"], ["Popcorn", "lila"], ["ChatsCircle", "cielo"],
  ["Browser", "cielo"], ["AppWindow", "rosa"], ["PlugsConnected", "miel"], ["CookingPot", "canela"],
  ["Database", "menta"], ["CloudArrowDown", "lila"], ["Football", "canela"], ["Heart", "rosa"],
  ["UsersThree", "crema"], ["TreeStructure", "crema"], ["FlowArrow", "crema"], ["ArrowsLeftRight", "crema"],
  ["ArrowsClockwise", "crema"],
];

const out = path.join(__dirname, "assets");
fs.mkdirSync(out, { recursive: true });
(async () => {
for (const [name, tono] of ICONOS) {
  const [ink, fill] = TONOS[tono];
  const mod = await import(pathToFileURL(path.join(SSR, `${name}.es.js`)).href);
  const Comp = mod[name] || mod[`${name}Icon`] || mod.default;
  let svg = renderToStaticMarkup(React.createElement(Comp, { size: 256, weight: "duotone", color: ink }));
  svg = svg.replace(/opacity="0\.2"/g, `fill="${fill}" opacity="1"`);
  if (!svg.includes("xmlns=")) svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ');
  fs.writeFileSync(path.join(out, `${name}_${tono}.svg`), svg);
}
console.log("iconos:", ICONOS.length);
})();
