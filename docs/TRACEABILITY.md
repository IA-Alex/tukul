# Trazabilidad crítica

| CAPABILITY | SPECIFICATION | IMPLEMENTATION | TESTS | OPERATIONAL_DOC | SECURITY_DOC |
|---|---|---|---|---|---|
| provider configuration | CONFIGURATION | `storage.py`, `models.py`, dialogs | `test_core.py`, auditoría | CONFIGURATION, OPERATIONS | SECURITY |
| endpoint validation | CONFIGURATION | `llm.validate_endpoint` | `TestSeguridadDelEndpoint` | OPERATIONS | SECURITY |
| secret handling | SECURITY | `storage.load/save/delete_key`, env/session | `TestCredenciales` | OPERATIONS | SECURITY, DATA_AND_PRIVACY |
| streaming | ARCHITECTURE / QUEUE_POLICY | `LLMClient.stream`, `LLMSessionManager`, `ChunkBuffer` | `test_cola_eventos.py`, `test_core.py` | OPERATIONS | SECURITY |
| cancellation | QUEUE_POLICY | request event, `LLMClient.cancel`, app cancel | queue/regression tests | OPERATIONS | SECURITY |
| request lifecycle | ARCHITECTURE | `ArticuladorApp`, `LLMSessionManager` | auditoría/regression | OPERATIONS | SECURITY |
| document switching | ARCHITECTURE | `DocumentScope`, `DocumentManager`, app | `TestAmbitoDelDocumento` | OPERATIONS | DATA_AND_PRIVACY |
| autosave/recovery | DATA_AND_PRIVACY | `autosave.py`, app | autosave/regression tests | OPERATIONS | SECURITY |
| persistence | ARCHITECTURE | `storage.atomic_write`, projects/UI state | storage/regression tests | OPERATIONS | DATA_AND_PRIVACY |
| logging | SECURITY | `logging_config.py` | `TestLogging` | OPERATIONS | SECURITY |
| health check | ARCHITECTURE | `health.py`, CLI | `TestSaludDeLaInstalacion` | OPERATIONS | — |
| size/token limits | CONFIGURATION | models, prompting, llm, app | core/regression tests | OPERATIONS | SECURITY |
| configuration parsing | CONFIGURATION | `storage.load_profiles` | `TestPerfilesInvalidos` | OPERATIONS | SECURITY |
