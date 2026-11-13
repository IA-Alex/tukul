# Documentación de Tukul

Este índice define qué documentos describen el estado actual. La implementación, los tests, la configuración, los scripts de calidad y los workflows son las fuentes primarias; ningún documento de `docs/archive/` es normativa vigente.

## Autoridad por tema

| Tema | Fuente canónica | Audiencia | Estado / ownership |
|---|---|---|---|
| Arquitectura y límites del sistema | [ARCHITECTURE.md](ARCHITECTURE.md) | desarrollo, revisión | NORMATIVE / mantenedores |
| Seguridad y amenazas | [SECURITY.md](SECURITY.md) | desarrollo, operaciones | NORMATIVE / mantenedores |
| Datos y privacidad | [DATA_AND_PRIVACY.md](DATA_AND_PRIVACY.md) | usuarios, operaciones | NORMATIVE / mantenedores |
| Configuración | [CONFIGURATION.md](CONFIGURATION.md) | usuarios, soporte | NORMATIVE / mantenedores |
| Operación y recuperación | [OPERATIONS.md](OPERATIONS.md) | operaciones, soporte | NORMATIVE / mantenedores |
| Tests y quality gate | [TESTING.md](TESTING.md) | desarrollo, CI | NORMATIVE / mantenedores |
| Releases | [RELEASE.md](RELEASE.md) | release managers | NORMATIVE / mantenedores |
| Contratos trazables | [TRACEABILITY.md](TRACEABILITY.md) | calidad, auditoría | SUPPORTING / mantenedores |
| Auditoría de naming | [NAMING_AUDIT.md](NAMING_AUDIT.md) | calidad, arquitectura | SUPPORTING / mantenedores |
| Canales y concurrencia | [QUEUE_POLICY.md](QUEUE_POLICY.md) | desarrollo | NORMATIVE / mantenedores |
| Decisiones significativas | [decisions/](decisions/) | arquitectura | SUPPORTING / mantenedores |
| Convenciones de docstrings | [DOCSTRING_GUIDE.md](DOCSTRING_GUIDE.md) | desarrollo | SUPPORTING / mantenedores |
| Auditorías puntuales | [audit/](audit/) (informes fechados) | calidad | HISTORICAL |
| Corpus necesario para evaluar | [INFORME_CORPUS_EVALUACION.md](INFORME_CORPUS_EVALUACION.md) | calidad | SUPPORTING / mantenedores |
| Batería de evaluación del modelo | [BATERIA_EVALUACION_MODELO.md](BATERIA_EVALUACION_MODELO.md) | calidad | SUPPORTING / mantenedores |
| Política de congelación | [POLITICA_CONGELACION.md](POLITICA_CONGELACION.md) | calidad | NORMATIVE / mantenedores |
| Dictamen de cierre vigente | [audit/cierre-2026-11-13-final.md](audit/cierre-2026-11-13-final.md) | calidad | NORMATIVE / mantenedores |
| Contratos posteriores a 0.5.2 | [contracts/contratos-0.6.md](contracts/contratos-0.6.md) | calidad | NORMATIVE / mantenedores |
| Uso rápido | [../README.md](../README.md) | usuarios | SUPPORTING / mantenedores |
| Flujo de contribución | [../CONTRIBUTING.md](../CONTRIBUTING.md) | desarrollo, revisores | NORMATIVE / mantenedores |
| Historial | [archive/README.md](archive/README.md) y `CHANGELOG.md` | contexto histórico | HISTORICAL |

## Clasificación

- **AUTHORITATIVE:** código, tests, configuración y workflows actuales.
- **NORMATIVE:** contratos actuales de `docs/` que deben seguirse y revisarse junto con el código.
- **SUPPORTING:** guías que explican o enlazan contratos, sin crear comportamiento nuevo.
- **HISTORICAL:** contexto de versiones anteriores; no define el comportamiento actual.
- **DEPRECATED:** material que identifica una práctica o símbolo retirado.
- **GENERATED:** reportes generados por herramientas; no se versionan como autoridad salvo que se indique lo contrario.

Al modificar comportamiento, actualiza la fuente primaria y el documento canónico relacionado en el mismo cambio. Si existe conflicto, prevalece la evidencia ejecutable y el conflicto se registra como deuda, no se resuelve copiando historia.
