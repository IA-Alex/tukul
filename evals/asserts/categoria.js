// Al menos uno de los hallazgos cae en las categorías esperadas del caso.
// Las categorías salen de `parse_findings`, que solo devuelve las cinco
// permitidas por review.ALLOWED_CATEGORIES.
const bruto = JSON.parse(output || '{}');
const meta = bruto.metadata || {};
const esperadas = config.categorias || [];
const encontradas = meta.parse_findings_categories || [];
return encontradas.some((categoria) => esperadas.includes(categoria));
