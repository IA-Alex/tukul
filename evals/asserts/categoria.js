// Al menos uno de los hallazgos cae en las categorías esperadas del caso.
// Las categorías salen de `parse_findings`, que solo devuelve las cinco
// permitidas por review.ALLOWED_CATEGORIES. Se pasan en `config.categorias`.
module.exports = (output, context) => {
  const meta = JSON.parse(output || '{}').metadata || {};
  const esperadas = (context.config || {}).categorias || [];
  const encontradas = meta.parse_findings_categories || [];
  return encontradas.some((categoria) => esperadas.includes(categoria));
};
