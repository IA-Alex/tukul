# Verificación del binario Windows en un equipo real (DF-C3)

> **Estado: Windows se retiró del soporte el 2026-11-12** (ver `CHANGELOG.md`
> 0.4.3 y `docs/audit/cierre-2026-11-12.md`). Este documento se conserva como
> referencia para una eventual reincorporación: es el procedimiento que habría
> que ejecutar **antes** de volver a publicar un binario Windows. No se mantiene
> un target que no se puede validar en su sistema destino.

Procedimiento para cerrar el hallazgo **DF-C3** de la auditoría de cierre
(`docs/audit/cierre-2026-11-12.md`): el binario `tukul-windows-x86_64.exe`
pasa el smoke `--health` en el runner de CI (`windows-2022`), pero no se ha
ejecutado en una sesión Windows real fuera de ese runner.

## Qué ya está verificado (sin Windows)

Análisis estático sobre el `.exe` de `v0.4.2`
(`CArchiveReader` + lectura del PE):

- Es un `PE32+` x86-64, subsistema `CUI` (consola), OS mínimo 6.0.
- El bootloader importa **solo** `USER32.dll`, `KERNEL32.dll` y `ADVAPI32.dll`
  (DLL del núcleo de Windows, presentes desde Windows 2000/XP). No depende de
  ninguna DLL externa adicional.
- Empaqueta su propio runtime: `python312.dll`, `VCRUNTIME140.dll`,
  `ucrtbase.dll`, los API sets `api-ms-win-crt-*`, `tcl86t.dll`, `tk86t.dll`,
  `libssl-3.dll`/`libcrypto-3.dll`, `sqlite3.dll`, etc. No exige que el equipo
  tenga Python, Tcl/Tk ni el VC++ Redistributable instalados.
- `SHA256SUMS` del Release coincide.

Conclusión estática: el binario **debería** ejecutarse en Windows 10/11 x64. Lo
que el análisis estático no puede demostrar —y lo que este procedimiento
verifica— es el comportamiento en ejecución real: apertura de la ventana Tk,
llavero, rutas y autosave con las API nativas.

## Requisitos

- Un equipo **Windows 10 o 11 x64** (preferible uno limpio o sin Python
  instalado, para probar el escenario «instalar sin Python»).
- PowerShell 5.1 o superior.
- Permiso para ejecutar un `.exe` descargado (puede que haya que marcar
  «Desbloquear» si Windows lo bloquea por venir de Internet).

## Pasos

### 1. Descargar el Release y verificar la integridad

```powershell
# Ajusta la versión si no es 0.4.2
$version = "0.4.2"
$dir = "$env:USERPROFILE\Downloads\tukul-verify"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Set-Location $dir

# Descarga el binario y el SHA256SUMS del Release
Invoke-WebRequest "https://github.com/IA-Alex/tukul/releases/download/v$version/tukul-windows-x86_64.exe" -OutFile "tukul-windows-x86_64.exe"
Invoke-WebRequest "https://github.com/IA-Alex/tukul/releases/download/v$version/SHA256SUMS" -OutFile "SHA256SUMS"

# Verifica el checksum contra SHA256SUMS
$esperado = (Select-String -Path SHA256SUMS -Pattern "tukul-windows-x86_64\.exe" |
    ForEach-Object { ($_ -split '\s+')[0] })
$real = (Get-FileHash .\tukul-windows-x86_64.exe -Algorithm SHA256).Hash.ToLower()
if ($real -eq $esperado) { "✓ Checksum OK: $real" } else { "✗ Checksum NO coincide"; }
```

### 2. Ejecutar el diagnóstico (`--health`)

```powershell
.\tukul-windows-x86_64.exe --health
"Codigo de salida: $LASTEXITCODE"
```

**Esperado:** imprime `Salud: OK` (o `ISSUES` con avisos si es un equipo virgen:
carpeta de config ausente y sin perfiles, que es normal), indica versión
(`Tukul 0.4.2`) y sale con código `0`.

### 3. Abrir la ventana (prueba real de la GUI)

```powershell
.\tukul-windows-x86_64.exe
```

**Esperado:**
- Abre una ventana con el editor a la izquierda y el asistente a la derecha.
- No aparece una consola negra extra (o aparece y se puede cerrar sin matar la
  app).
- Se puede minimizar, redimensionar y cerrar con la X.

Comprueba en la ventana:
1. **Tema**: se ve el tema oscuro cálido (madera/bambú), no el gris por defecto
   de Tk.
2. **Scrollbars**: las barras del editor y del historial son oscuras (DF-002 del
   cierre no es específico de Windows, pero conviene confirmar que se ve igual).
3. **Menús**: **Recientes**, **Configurar modelo…**, **Contexto de artículos…**
   abren sin error.
4. **Atajos**: `Ctrl+O` abre un diálogo de archivo; `F6` oculta el panel del
   asistente; `F11` entra en modo foco; `Ctrl++`/`Ctrl+-` cambian el zoom.

### 4. Confirmar el llavero (keyring)

Abre **Configurar modelo…**, activa «recordar la key» y guarda una key de
prueba (puede ser ficticia). **Esperado:** no hay error; si el backend del
Credential Manager falla, la app debe degradar al aviso y permitir usar la key
solo en sesión (ver `docs/OPERATIONS.md`, «keyring falla»).

Luego revisa que **no** se escribió la key en el TOML:

```powershell
Select-String -Path "$env:USERPROFILE\.config\tukul\config.toml" -Pattern "api_key|sk-|key-" -ErrorAction SilentlyContinue
# No debe devolver ninguna key
```

> Tukul no usa `%APPDATA%`: guarda config y estado bajo el perfil del usuario,
> `C:\Users\<usuario>\.config\tukul\` y `C:\Users\<usuario>\.local\state\tukul\`
> (ver `tukul_core/storage.py` y `logging_config.py`). Es el mismo esquema que en
> Linux.

### 5. Probar guardar, reabrir y autosave

1. Escribe texto en el editor, `Ctrl+S`, guarda un `.md`.
2. Cierra la app; vuelve a abrir el `.md` con **Recientes**.
3. Cierra de forma abrupta (o mata el proceso) tras editar sin guardar y vuelve
   a abrir: debe ofrecer restaurar desde autosave.

**Esperado:** el artículo persiste, la conversación por documento se recupera, y
las rutas se resuelven correctamente con separadores de Windows.

### 6. Registrar el resultado

Adjunta al informe: versión de Windows (`winver`), salida de `--health`, y el
resultado de cada paso. Si algo falla, captura el mensaje exacto y
`C:\Users\<usuario>\.local\state\tukul\tukul.log` (ver
`docs/OPERATIONS.md#locations`).

## Criterio de cierre de DF-C3

- **Cumple** si: checksum OK, `--health` exit 0, la ventana abre y se opera, el
  llavero no escribe la key en el TOML, y guardar/reabrir/autosave funcionan.
- **No cumple** si alguno falla → se abre un hallazgo nuevo con la evidencia.
- Si no hay acceso a un Windows real, DF-C3 se mantiene **No verificado** (no se
  convierte en defecto confirmado), pero la evidencia estática de arriba rebaja
  el riesgo a «bajo».

## Por qué no se puede automatizar aquí

CI ya ejecuta `--health` del binario en `windows-2022`, pero eso corre en el
mismo SO del build y sin sesión interactiva: no prueba la GUI ni el llavero del
usuario. Un runner de Windows no sustituye la prueba en un equipo real, del
mismo modo que el smoke de Linux no detectó DF-C1.
