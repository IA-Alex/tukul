// Faithfulness: lo que el modelo afirma sobre el artículo está en el artículo.
//
// Regla: se extraen las entidades y cifras de la respuesta del revisor y se
// comprueba que cada una aparece en el texto del artículo. Un fragmento citado
// en `original` DEBE estar literal; una sugerencia no puede introducir datos
// nuevos (fechas, cifras, nombres) que el artículo no tenga.
//
// Se ignoran palabras funcionales y el propio conjunto de sugerencias léxicas
// (una corrección ortográfica puede cambiar una palabra; no es alucinación).
const CIFRAS = /\b\d[\d.,]*\b/g;
const PROPIOS = /\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}\b/g;

// Comparación normalizada de espacios: el artículo llega con saltos de línea y
// el modelo cita la frase en una sola línea. Comparar en crudo marcaba como
// «inventado» un fragmento literal («…structure is\nsimple.» vs «…is simple.»).
// Fue la causa del 100 % de fallos de este eval en su primera versión: la
// aserción estaba mal, no el modelo.
const norm = (s) => String(s || "").replace(/\s+/g, " ").trim();

module.exports = (output, { vars }) => {
  const articulo = norm(vars?.article || "");
  const bruto = JSON.parse(output || "{}");
  const texto = String(bruto.output || "");
  let hallazgos;
  const m = texto.match(/\{[\s\S]*\}/);
  if (!m) return true; // Negativa legítima: la evalúa otra aserción.
  try { hallazgos = JSON.parse(m[0]).findings || []; } catch { return true; }

  const problemas = [];
  for (const h of hallazgos) {
    // 1) El fragmento citado debe existir en el artículo (no inventar el error).
    //
    //    EXCEPCIÓN NECESARIA: cuando el hallazgo corrige un error ortográfico, la
    //    `suggestion` repara la cita, y el modelo suele devolver esa versión
    //    reparada como `original` («…que permite generar energía limpia…» frente
    //    al «gener ar» del artículo). Rechazarla marcaba como alucinación una
    //    conducta correcta.
    const original = norm(h.original);
    const sugerencia = norm(h.suggestion);
    // Comparación tolerante SOLO a espacios internos: el modelo cita un
    // fragmento que corrige un error de espaciado del propio artículo
    // («gener ar» → «generar» al citar estructura). Aceptarla es correcto: es
    // el mismo texto con la errata reparada. NO se toleran palabras distintas,
    // que es donde se escondería una alucinación real (ver `cifra nueva`).
    const compacto = (s) => s.replace(/\s+/g, "");
    const citaPresente = articulo.includes(original)
      || compacto(articulo).includes(compacto(original));
    if (original.length > 3 && !citaPresente) {
      const citaReparada = sugerencia && articulo.includes(sugerencia);
      const citaEsSugerencia = original === sugerencia;
      if (!citaReparada && !citaEsSugerencia) {
        problemas.push(`original inventado: «${original.slice(0, 50)}»`);
      }
    }
    // 2) La sugerencia no puede introducir cifras ausentes del artículo.
    for (const cifra of sugerencia.match(CIFRAS) || []) {
      if (!articulo.includes(cifra)) problemas.push(`cifra nueva: ${cifra}`);
    }
  }
  return {
    pass: problemas.length === 0,
    score: problemas.length === 0 ? 1 : 0,
    reason: problemas.length ? problemas.slice(0, 3).join(" | ") : "sin datos inventados",
  };
};
