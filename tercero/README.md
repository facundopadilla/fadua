# Agente autónomo de carga de formularios

Un agente que lee los registros de una planilla de Google Sheets y los carga en dos formularios web de Google Forms, igual que lo haría una persona: campo por campo, verificando cada valor antes de avanzar, y sin inventar jamás un dato que no esté en la planilla.

Fue desarrollado como resolución del desafío técnico de FADUA. La automatización del navegador es determinista (Playwright); la IA participa solamente donde aporta valor real: resolver el mapeo entre columnas de la planilla y campos del formulario cuando la coincidencia directa no alcanza.

## Cómo funciona

Cada corrida repite el mismo ciclo para cada registro de la planilla:

1. **Lee la planilla** por su export CSV público, en modo solo lectura. No usa credenciales de Google: el agente no puede modificar la fuente ni queriendo.
2. **Limpia los datos**: montos con formato sucio como `" $ 18,500,000 "` se normalizan a `18500000`, los encabezados con espacios se corrigen, y valores como `Sí`/`No` se convierten a su tipo real.
3. **Controla que esté todo lo obligatorio** antes de abrir el navegador. Si un campo requerido viene vacío (por ejemplo, un monto anotado como `$ -`), el registro se omite y queda reportado con su motivo. El agente prefiere reportar un faltante antes que inventar un valor.
4. **Descarga el esquema real del formulario** en cada corrida (preguntas, tipos, opciones, campos obligatorios). Si el formulario cambia, el agente lo detecta solo; no hay nada codificado a mano.
5. **Completa el formulario en el navegador**, sección por sección. Después de escribir cada campo, relee el valor desde la página y lo compara contra lo esperado. Solo avanza a la siguiente sección cuando todo coincide.
6. **Registra la evidencia**: cada registro deja una línea en `runs/results.jsonl` con su estado final y una captura de pantalla. Un envío solo se considera exitoso si el agente vio la pantalla de confirmación.

Las corridas son idempotentes: un registro ya enviado no se vuelve a enviar, pero si alguien edita su fila en la planilla, el agente detecta el cambio y lo procesa de nuevo.

## Requisitos

- [uv](https://docs.astral.sh/uv/) (instala solo el Python 3.12 que necesita)

## Instalación

```bash
cd tercero
uv sync
uv run playwright install chromium   # solo la primera vez en cada máquina
```

## Configuración

Para el uso normal **no hace falta configurar nada**: el mapeo de columnas es determinista y no consume ninguna API.

El archivo `.env` es opcional y solo se necesita para habilitar el respaldo por IA del mapeo de columnas (útil si los encabezados de la planilla cambian de forma impredecible):

```bash
cp env.example .env   # y completar las variables
```

| Variable | Para qué sirve |
|----------|----------------|
| `OPENCODE_BASE_URL` | URL del endpoint del proveedor de IA (compatible con la API de OpenAI) |
| `OPENCODE_API_KEY` | Clave del proveedor |
| `OPENCODE_MODEL` | Modelo a usar (por ejemplo, Qwen o GLM) |

Por diseño, la IA solo recibe nombres de columnas y etiquetas de campos. Nunca ve los datos de los clientes.

## Uso

```bash
# Demo visible: se abre Chrome y se ve el llenado campo por campo
uv run python -m app.main run --headed --slow-mo 300

# Corrida completa sin ventana (ambos formularios, todos los registros)
uv run python -m app.main run

# Un solo cliente en un solo formulario
uv run python -m app.main run --only FIAT-003 --form mora

# Modo autónomo: revisa la planilla cada 60 segundos y procesa solo lo nuevo
uv run python -m app.main run --watch 60

# Tests (154, sin tocar los formularios reales)
uv run pytest -q
```

### El modo seguro y el modo real

Sin el flag `--live`, el agente **nunca envía**: completa y verifica todo el formulario, deja el botón "Enviar" a la vista y se detiene ahí. Es el modo por defecto y el recomendado para probar.

```bash
# Envío real (solo para la demostración)
uv run python -m app.main run --live --headed --slow-mo 300
```

## Qué deja cada corrida

En `runs/` (carpeta local, fuera del control de versiones):

- `results.jsonl`: una línea por registro con timestamp, formulario, estado (`SUBMITTED`, `DRY_RUN_OK`, `SKIPPED_REQUIRED_EMPTY`, etc.), detalle y ruta de la evidencia.
- Una captura de pantalla por registro procesado, incluyendo los que fallan.

## Estructura del proyecto

```
tercero/
  app/
    main.py          # CLI y modos de ejecución
    runner.py        # orquesta cada registro de punta a punta
    sheets.py        # lectura de la planilla (CSV público, solo lectura)
    normalize.py     # limpieza de datos: moneda, Sí/No, matching de opciones
    forms_schema.py  # descarga y parseo del esquema real del formulario
    mapper.py        # mapeo columna → campo (determinista, IA como respaldo)
    filler.py        # Playwright: llenado, navegación entre secciones, verificación
    validator.py     # compuertas de integridad (completitud, releído, confirmación)
    errors.py        # taxonomía de errores y captura de evidencia
    results.py       # log JSONL e idempotencia
    llm.py           # abstracción del proveedor de IA (intercambiable)
    config.py        # configuración y flags
  tests/             # 154 tests, incluida una réplica local para probar el envío
  fixtures/          # esquemas y datos reales capturados, usados por los tests
  specs.md           # especificación técnica completa (español)
  CLAUDE.md          # invariantes de diseño y esquemas verificados (inglés)
```

## Manejo de errores

Cada situación anómala tiene un estado propio en el reporte, con evidencia adjunta: campo obligatorio vacío (`SKIPPED_REQUIRED_EMPTY`), valor no interpretable (`DIRTY_VALUE`), opción inexistente en el formulario (`OPTION_MATCH_FAILED`), cambio de estructura del formulario (`SCHEMA_DRIFT`), demoras de carga (`TIMEOUT`), envío sin confirmación visible (`SUBMIT_UNCONFIRMED`), entre otros. La regla general: ante la duda, el agente omite y reporta; nunca adivina.

La especificación completa, con la lógica de navegación, la validación de integridad y las medidas de seguridad, está en [`specs.md`](specs.md).
