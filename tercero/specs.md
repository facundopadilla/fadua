# Agente Autónomo de Carga de Formularios
## Especificación Técnica (v1)

---

# Objetivo

Desarrollar un agente autónomo que lea registros desde varias hojas de un Google Sheets y complete, paso a paso, dos formularios web alojados en sitios distintos, replicando el comportamiento humano de navegación, validación y envío.

El agente debe:

- Extraer dinámicamente los registros de cada hoja del Google Sheets.
- Navegar e interactuar con dos Google Forms situados en URLs diferentes.
- Completar cada campo respetando su tipo (texto, desplegable, opción, casilla).
- Manejar situaciones imprevistas: campos requeridos vacíos, errores de validación del sitio, tiempos de carga excesivos.
- Garantizar que cada registro se cargó correctamente antes de avanzar.
- No inventar datos: si un dato requerido falta o es ambiguo, se omite el registro y se reporta.

---

# Principios de Arquitectura

- **La hoja de cálculo es la única fuente de verdad.** Todo valor cargado en un formulario proviene de una celda real. El agente nunca genera datos.
- **Playwright determinista conduce el navegador. El LLM no.** La automatización de UI es código explícito y reproducible. El modelo de IA no ejecuta acciones de navegación.
- **El LLM solo asiste donde aporta.** Su único uso es resolver el mapeo de una columna a un campo cuando la coincidencia determinista falla. Ve esquemas y etiquetas, nunca valores de filas.
- **El acceso a la hoja es de solo lectura.** Se usa el export público `gviz` en CSV. El agente no puede mutar la fuente.
- **El éxito solo se declara con confirmación observada.** Un envío se registra como exitoso únicamente cuando se detecta la página de confirmación. Sin confirmación, el resultado es `SUBMIT_UNCONFIRMED`.
- **El proveedor de IA es reemplazable.** Los modelos se consumen detrás de una abstracción; ningún código específico de proveedor se filtra al agente.
- **Los formularios reales solo se envían con autorización explícita.** El envío contra los Google Forms de FADUA requiere el flag `--live`. El desarrollo usa formularios clon y `--dry-run`.

---

# Stack Tecnológico y Criterios de Selección ✦

> Responde a FADUA 4.4: *¿qué factores determinaron el stack?*

## Stack elegido

- **Lenguaje**: Python 3.12
- **Gestor de entorno / dependencias**: uv
- **Automatización de navegador**: Playwright (Python)
- **Motor de IA**: modelos de OpenCode GO (Qwen, GLM, …) detrás de una abstracción reemplazable
- **Empaquetado**: Docker

## Playwright vs Selenium vs Puppeteer

| Factor | Playwright | Selenium | Puppeteer |
|--------|-----------|----------|-----------|
| Auto-waiting | Integrado: espera visibilidad y accionabilidad antes de cada acción | Manual: requiere `WebDriverWait` explícito | Parcial |
| Aislamiento por registro | `BrowserContext` liviano por registro, sin proceso nuevo | Una sesión de driver por instancia | Contexto por página |
| Depuración post-mortem | Trace viewer nativo (DOM, red, capturas por paso) | Requiere andamiaje externo | Limitado |
| Localizadores accesibles | `get_by_role`, `get_by_label` de primera clase | Selectores CSS/XPath | CSS/XPath |
| Ecosistema | Python + Node | Multi-lenguaje maduro | Node únicamente |

El auto-waiting es determinante: Google Forms renderiza controles de forma asíncrona y el trato de "tiempos de carga excesivos" del enunciado se resuelve con la espera integrada de Playwright, no con `sleep` frágiles. El `BrowserContext` por registro habilita el escalado sin reescritura. El trace viewer cubre la validación de integridad y la demostración en vivo.

## Por qué híbrido y no un framework de agente de IA completo

Un framework de agente autónomo que "mira la pantalla y decide" (visión + planificación por LLM sobre el DOM) es no determinista y costoso por token, y su modo de fallo es inventar clics o valores plausibles. En un formulario de cobranzas eso es inaceptable. La navegación es un problema resuelto por código: el esquema del formulario es conocido y estable. Se reserva el LLM para la única tarea semántica real —mapear vocabulario de columna a campo cuando la heurística no basta— y se mantiene todo lo demás determinista.

---

# Fuentes de Datos

## Google Sheets (solo lectura)

ID del documento: `1y6aREOjFrbDd5bKlpt72UBc6svk_pr2wBsAqv_xb_2Y`. Se accede por hoja mediante el export público `gviz/tq?tqx=out:csv&sheet=<nombre>`. Dos hojas, cuatro registros cada una (`FIAT-001` … `FIAT-004`).

Hoja **VENTAS**:

| Columna | Observación |
|---------|-------------|
| `ID_Cliente` | Clave del registro |
| `Nombre_Cliente` | |
| `Email` | |
| `Telefono` | |
| `Modelo_Auto` | Alimenta un desplegable en el form |
| ` Valor_Vehiculo` | Header con espacio inicial; valor con formato de moneda sucio |
| `Tipo_Financiacion` | |

Hoja **MORA**:

| Columna | Observación |
|---------|-------------|
| `ID_Cliente` | Clave del registro |
| `Nombre_Cliente` | |
| ` Valor_Vehiculo` | Header con espacio inicial |
| `Tipo_Financiacion` | Alimenta un desplegable en el form |
| `Estado_Pago` | Valor `Al Día` no coincide literal con la opción `Al día` del form |
| `Dias_Atraso` | |
| ` Ultimo_Pago_Monto` | Header con espacio inicial; `FIAT-002` trae `" $ -   "` (vacío) |
| `Requiere_Cobranza` | `Sí` / `No` → casilla de opción única |

Los nombres de columna se transcriben **exactamente** como aparecen, incluidos los espacios iniciales. La normalización de headers ocurre en la ingesta (`.strip()`), no en la especificación.

## Formularios web

| # | Título | URL | Estructura |
|---|--------|-----|-----------|
| 1 | Registro de Ventas | `https://forms.gle/oqjtULJ6iGBT7HFR7` | Multi-página (secciones con "Siguiente") |
| 2 | Control de Morosidad y Pagos | `https://forms.gle/JQTABscuZxn2S6Dh7` | Una página |

Ambos son públicos, sin login de Google y sin captura de correo.

## Esquema como dato en vivo: `FB_PUBLIC_LOAD_DATA_`

Cada Google Form expone su definición en una variable JavaScript `FB_PUBLIC_LOAD_DATA_` embebida en el HTML. El agente la parsea **en cada corrida** y deriva de allí el esquema real: item IDs (ancla en el DOM), entry IDs (nombre del campo en el POST), tipos de campo, flags de requerido, opciones y saltos de sección. Esto convierte cualquier cambio del formulario en un cambio de datos detectado automáticamente (drift), no en un cambio de código. Los JSON capturados en `fixtures/` (`form_ventas_fb.json`, `form_mora_fb.json`) son fixtures de test, no la fuente en runtime.

### Códigos de tipo de campo (`FB_PUBLIC_LOAD_DATA_`)

| Código | Tipo | Handler |
|--------|------|---------|
| 0 | Texto corto | `fill` |
| 2 | Opción única (radio) | click de opción + verificación `aria-checked` |
| 3 | Desplegable (listbox ARIA) | abrir → click opción → verificar texto |
| 4 | Casilla (checkbox) | marcar solo si el booleano es verdadero |
| 8 | Encabezado de sección / salto de página | delimita páginas; no es un campo |

### Esquema Form 1 — Registro de Ventas

| item ID (ancla DOM) | entry ID (nombre POST) | Etiqueta | Tipo | Requerido | Opciones |
|---------------------|------------------------|----------|------|-----------|----------|
| — | — | DATOS DEL CLIENTE | 8 (sección) | — | — |
| `999998362` | `entry.814069894` | ID del Cliente | 0 | Sí | — |
| `1400945540` | `entry.657237802` | Nombre Completo | 0 | Sí | — |
| `1881411619` | `entry.1855970967` | Correo Electrónico | 0 | Sí | — |
| `146186431` | `entry.136415275` | Teléfono de Contacto | 0 | Sí | — |
| — | — | DATOS DE LA UNIDAD | 8 (sección) | — | — |
| `667185096` | `entry.2099080465` | Modelo de Automóvil | 3 | Sí | Fiat Cronos · 600 · Fiat Strada · Fiat Fastback · Fiat Pulse |
| `1583087190` | `entry.1493778692` | Valor Total del Vehículo | 0 | Sí | — |
| — | — | DATOS DE COMPRA | 8 (sección) | — | — |
| `34738716` | `entry.487326979` | Tipo de Financiación | 2 | Sí | Crédito Prendario · Plan de Ahorro · Contado / Directo |

### Esquema Form 2 — Control de Morosidad y Pagos

| item ID (ancla DOM) | entry ID (nombre POST) | Etiqueta | Tipo | Requerido | Opciones |
|---------------------|------------------------|----------|------|-----------|----------|
| `88995149` | `entry.1568255357` | ID de Cliente Asociado | 0 | Sí | — |
| `158888317` | `entry.1088714979` | Nombre del Cliente | 0 | No | — |
| `888542449` | `entry.230995405` | Valor del Vehículo | 0 | Sí | — |
| `169419756` | `entry.191355245` | Tipo Financiación | 3 | Sí | Plan de Ahorro · Crédito Prendario · Contado / Directo |
| `101891614` | `entry.1430363473` | Estado de Cuenta Actual | 2 | Sí | Al día · Moroso |
| `250795746` | `entry.1824761040` | Días de Atraso (Si aplica) | 0 | Sí | — |
| `1075955762` | `entry.1373856247` | Monto del Último Pago Registrado | 0 | Sí | — |
| `1137417183` | `entry.76508310` | Requiere Acción de Cobranza Legal | 4 | No | Sí, activar protocolo de cobranza legal |

Cruce de tipos entre formularios: en Form 1 el Modelo es desplegable y la Financiación es radio; en Form 2 la Financiación es desplegable y el Estado es radio. El handler se elige siempre desde el tipo del esquema, nunca por el nombre del campo.

---

# Arquitectura del Proyecto

```
tercero/
  app/
    config.py        # .env: URLs, sheet ID, proveedor, flags
    llm.py           # abstracción de proveedor de IA (OpenCode GO, reemplazable)
    sheets.py        # gviz CSV por hoja → list[dict]; headers limpios
    normalize.py     # parsers deterministas: moneda, Sí/No, match de opciones
    forms_schema.py  # FB_PUBLIC_LOAD_DATA_ → FormSchema (campos, tipos, requeridos, opciones, páginas)
    mapper.py        # mapeo determinista columna→campo; LLM solo como fallback; cache
    filler.py        # Playwright: handlers por tipo, listbox, "Siguiente", ritmo humano
    validator.py     # tres compuertas: completitud, read-back, confirmación
    errors.py        # taxonomía de errores + evidencia (captura + trace) por fallo
    runner.py        # orquesta un registro de punta a punta
    results.py       # JSONL append-only: resultado + idempotencia
    main.py          # CLI: run | --watch | --dry-run | --headed | --slow-mo | --only <ID> | --live
  clones/            # formularios clon propios para tests de envío real
  tests/
  fixtures/          # form_ventas_fb.json, form_mora_fb.json, tab_VENTAS.csv, tab_MORA.csv
  pyproject.toml
  Dockerfile
  .env.example
  README.md          # guía de ejecución y entrega
```

| Módulo | Rol |
|--------|-----|
| `config.py` | Carga configuración y flags desde `.env` |
| `llm.py` | Envuelve el proveedor de IA; interfaz única, proveedor intercambiable |
| `sheets.py` | Descarga cada hoja por CSV; limpia headers; entrega registros como diccionarios |
| `normalize.py` | Convierte valores sucios a valores limpios de forma 100% determinista |
| `forms_schema.py` | Parsea `FB_PUBLIC_LOAD_DATA_` al modelo `FormSchema` |
| `mapper.py` | Resuelve columna→campo por tokens; delega al LLM solo lo no mapeado; cachea |
| `filler.py` | Ejecuta las acciones de Playwright por tipo de campo y la navegación entre secciones |
| `validator.py` | Aplica las tres compuertas de integridad |
| `errors.py` | Define la taxonomía y adjunta evidencia a cada fallo |
| `runner.py` | Orquesta el flujo completo de un registro |
| `results.py` | Persiste resultados en JSONL y hace de checkpoint de idempotencia |
| `main.py` | Punto de entrada y parseo de modos de CLI |

---

# Lógica de Navegación entre Formularios ✦

> Responde a FADUA 4.4: *¿cómo se estructura la transición entre formularios?*

No hay dos rutas de código: hay **un bucle genérico** que recorre `schema.pages`. El mismo `filler` procesa Form 1 (multi-página) y Form 2 (una página) porque la estructura se lee del esquema, no se codifica.

```
para cada formulario (Ventas, Mora):
    schema = forms_schema(descargar_html(url))
    registros = sheets(hoja_del_formulario)
    para cada registro:
        runner(registro, schema, url)
```

Transición entre secciones dentro de un formulario:

- Antes de completar una sección se afirma que la sección esperada está en pantalla (por su encabezado tipo 8).
- Se completan solo los campos de esa sección.
- Se hace click en "Siguiente".
- Después del click se afirma que la nueva sección esperada está en pantalla. Si no aparece, es `NavigationError`.
- En la última sección el botón es "Enviar", no "Siguiente".

La transición **entre** formularios es secuencial y aislada: se termina Ventas para los cuatro registros y luego Mora. Cada registro corre en su propio `BrowserContext`, de modo que ningún estado (cookies, autocompletado, campos residuales) se filtra entre registros ni entre formularios.

---

# Proceso de Llenado Paso a Paso ✦

> Responde a FADUA 4.4: *¿cómo se ejecutó la carga "paso a paso"?*

Cada campo se completa según su tipo, con verificación antes de avanzar. Los localizadores nunca dependen de clases ofuscadas de Google.

## Estrategia de localización

| Objetivo | Localizador primario | Fallback |
|----------|---------------------|----------|
| Campo | Contenedor de la pregunta por `[data-params*="[<item ID>,"]`; la acción se ejecuta por rol dentro del contenedor | Etiqueta accesible (`get_by_role` / `get_by_label`, matching normalizado) |
| Sección | Encabezado de sección (texto tipo 8) | — |
| Botón | `get_by_role("button", name="Siguiente" \| "Enviar")` | — |

Verificado contra el DOM real (2026-07-10): los inputs del `viewform` **no** llevan `name="entry.<ID>"`. Ambos IDs viven en el atributo `data-params` del contenedor de cada pregunta (primero el item ID, anidado el entry ID). El entry ID es el nombre del campo en el POST (`formResponse`) y en URLs de prefill — sirve para tests y verificación, no para localizar en el DOM.

## Handlers por tipo

- **Texto (0)**: `fill` con el valor normalizado.
- **Desplegable (3)**: es un **listbox ARIA**, no un `<select>`. Se abre con click, se clickea la opción por su texto y se **verifica el texto renderizado** en el control. Nunca se usa `select_option`.
- **Opción única (2)**: `get_by_role("radio", name=<opción>)`, click y verificación de `aria-checked`.
- **Casilla (4)**: `get_by_role("checkbox")`; se marca **solo si** el booleano es verdadero; se verifica `aria-checked`. Un valor falso no toca el control.

## Ritmo humano

Se aplican esperas cortas y variables (jitter) entre acciones y el modo `--slow-mo` en la demostración. El objetivo es reproducir el patrón de interacción humana y no saturar el sitio, no evadir controles.

---

# Validación de Integridad ✦

> Responde a FADUA 4.4: *¿cómo asegura el agente que los datos fueron cargados correctamente antes de avanzar?*

Tres compuertas secuenciales. Un registro solo se declara exitoso si supera las tres.

## Compuerta 1 — Completitud (antes de abrir el navegador)

Se comparan los requeridos del esquema contra los valores normalizados del registro. Si falta algún requerido, el registro se omite con `SKIPPED_REQUIRED_EMPTY` **sin abrir el navegador**. No se envía un formulario parcial ni se inventa un valor de relleno.

## Compuerta 2 — Read-back por campo (durante el llenado)

Tras completar cada campo se **lee el valor efectivo del DOM** y se afirma que es igual al valor esperado antes de avanzar. Para desplegables se verifica el texto renderizado; para radio y checkbox, `aria-checked`. Una discrepancia detiene el registro con `ValidationError`.

## Compuerta 3 — Confirmación (después de enviar)

El éxito se declara solo al detectar la página de confirmación: transición de URL/vista más frases conocidas de confirmación de Google Forms. No se compara contra un string exacto (el texto varía). Sin confirmación observada, el resultado es `SUBMIT_UNCONFIRMED`; nunca se asume éxito.

---

# Normalización y Trampas de Datos

Los datos de origen contienen inconsistencias deliberadas —el test real de "manejo de errores" del enunciado—. Cada una tiene un tratamiento definido y determinista.

| # | Trampa | Ejemplo | Tratamiento |
|---|--------|---------|-------------|
| 1 | Estado no coincide literal con la opción del form | Sheet `Al Día` vs opción `Al día` | Matching de opciones insensible a mayúsculas y acentos (determinista) |
| 2 | Requerido vacío disfrazado | `FIAT-002`: ` Ultimo_Pago_Monto` = `" $ -   "` | `SKIPPED_REQUIRED_EMPTY`. Nunca inventar un `0` en un formulario de cobranzas |
| 3 | Moneda sucia | `" $ 18,500,000 "` | Parser determinista: quita símbolo, comas de miles y padding; tolera coma decimal |
| 4 | Booleano a casilla de opción única | `Requiere_Cobranza` = `Sí` / `No` | `Sí`/`No` → bool; marcar solo si es verdadero. `No` no toca el control (no existe opción "No") |
| 5 | Headers con espacio inicial | ` Valor_Vehiculo`, ` Ultimo_Pago_Monto` | `.strip()` de headers en la ingesta |
| 6 | Estructura de formulario distinta | Form 1 multi-página vs Form 2 una página | Bucle genérico por `schema.pages`: mismo código para ambos |
| 7 | Inconsistencia lógica del negocio | `FIAT-003`: Moroso 15 días pero `Requiere_Cobranza` = `No` | Se confía en la hoja: se carga `No` y se registra la inconsistencia como observación. El agente no infiere cobranza legal |

---

# Manejo de Errores

Cada fallo tiene un código, una estrategia y evidencia asociada. Todo error de navegación adjunta captura de pantalla y traza de Playwright.

| Código | Situación | Estrategia | Evidencia |
|--------|-----------|-----------|-----------|
| `SKIPPED_REQUIRED_EMPTY` | Requerido vacío tras normalizar | Omitir el registro y reportar; no abrir navegador | Registro en JSONL |
| `DIRTY_VALUE` | Valor no parseable por el normalizador | Omitir el registro y reportar el valor crudo | Registro en JSONL |
| `OPTION_MATCH_FAILED` | Ninguna opción del form coincide con el valor | Si el campo es requerido: omitir y reportar. Nunca elegir la opción "más parecida" a ciegas | Captura + trace |
| `NAVIGATION_ERROR` | La sección esperada no aparece tras "Siguiente" | Reintento acotado; si persiste, abortar el registro | Captura + trace |
| `VALIDATION_BANNER` | El sitio muestra un banner de validación | Capturar el mensaje, abortar el registro y reportar | Captura + trace |
| `TIMEOUT` | Carga excesiva de un control o página | Espera integrada de Playwright con límite; al superarlo, abortar el registro | Captura + trace |
| `SUBMIT_UNCONFIRMED` | No se detectó la página de confirmación | No declarar éxito; marcar para revisión | Captura + trace |
| `SCHEMA_DRIFT` | El esquema en vivo difiere de lo esperado (entry ID, tipo, opción nueva) | Detener el formulario y reportar el drift; no adivinar el mapeo del campo nuevo | Diff de esquema |
| `LLM_ERROR` | El fallback de mapeo falla o devuelve baja confianza | Tratar el campo como no mapeado; si es requerido, omitir el registro y reportar | Registro en JSONL |

---

# Seguridad ✦

> Responde a FADUA 4.4: *¿qué medidas de seguridad se implementaron?*

- **Mínimo privilegio.** Acceso a la hoja por CSV público de solo lectura, sin OAuth. El agente no tiene credenciales que le permitan mutar la fuente.
- **PII fuera del LLM.** El modelo ve headers y etiquetas de campo; **nunca** valores de filas (nombres, correos, teléfonos, montos). La normalización de valores es 100% determinista.
- **Secretos solo en `.env`.** Configuración sensible en `.env` (git-ignored). Nada de secretos en el código ni en los logs.
- **Allowlist de dominios de navegación.** El navegador solo opera sobre `docs.google.com` y `forms.gle`. Ante un redirect fuera de la lista, se aborta.
- **Rate limiting y jitter.** Esperas variables entre acciones para no saturar el sitio ni disparar defensas anti-bot.
- **Evidencia sin secretos.** Capturas y trazas no contienen credenciales.
- **Guardarraíl `--live`.** El envío contra los formularios reales de FADUA requiere `--live` explícito. Sin él, el agente usa formularios clon o `--dry-run`.
- **Idempotencia como propiedad de seguridad.** La clave de idempotencia evita duplicar registros de cobranza, que en este dominio tienen consecuencias reales.

---

# Escalabilidad

- **Idempotencia.** Clave `(form, ID_Cliente, content-hash)` en un log JSONL append-only que hace de resultado y checkpoint a la vez. Una fila editada (cambia el content-hash) se re-envía; una fila sin cambios no se duplica.
- **Modo `--watch`.** Pollea la hoja y procesa solo el delta contra el conjunto de idempotencia ya registrado.
- **Serial en v1, listo para paralelo.** v1 procesa los cuatro registros en serie. Como cada registro usa su propio `BrowserContext`, el paso a un pool acotado de workers es un cambio de orquestación, no de los handlers.
- **Cambios de estructura = cambios de datos.** Al derivar el esquema de `FB_PUBLIC_LOAD_DATA_` en vivo, agregar campos o cambiar opciones no requiere tocar el código: se detecta como drift.

---

# Observabilidad y Demostración

Pensado para la ejecución en vivo y las pruebas de robustez de FADUA.

- **Modo `--headed` + `--slow-mo`.** El navegador es visible y las acciones se ralentizan para que el evaluador siga el llenado paso a paso.
- **Capturas por registro.** Se guarda evidencia visual de cada registro, incluidos los que se omiten o fallan.
- **Playwright tracing.** El trace viewer permite reconstruir DOM, red y acciones de cualquier corrida post-mortem.
- **Log JSONL legible.** Cada línea es el resultado de un registro con su código de estado, listo para auditar el comportamiento del agente.

---

# CLI y Modos

```
python -m app.main run                  # corrida completa (ambos formularios)
python -m app.main run --watch          # pollea la hoja y procesa solo el delta
python -m app.main run --dry-run        # llena los formularios pero NO envía
python -m app.main run --headed         # navegador visible
python -m app.main run --slow-mo <ms>   # ralentiza cada acción
python -m app.main run --only <ID>      # procesa solo un ID_Cliente
python -m app.main run --live           # habilita el envío a los formularios reales de FADUA
```

`--dry-run` y `--live` son mutuamente excluyentes en intención: el desarrollo por defecto no envía a los formularios reales; `--live` es la única puerta a hacerlo.

---

# Entregables y Criterios de Aceptación

## Mapeo enunciado → sección

| Requisito del enunciado | Sección que lo responde |
|-------------------------|------------------------|
| 3.1 Lectura dinámica de datos | Fuentes de Datos |
| 3.1 Navegación entre 2 formularios en sitios distintos | Lógica de Navegación entre Formularios |
| 3.1 Manejo de errores | Manejo de Errores · Normalización y Trampas |
| 4.3 Código documentado: selectores y navegación | Proceso de Llenado Paso a Paso · Lógica de Navegación |
| 4.4 Criterios de selección tecnológica | Stack Tecnológico y Criterios de Selección |
| 4.4 Lógica de navegación | Lógica de Navegación entre Formularios |
| 4.4 Gestión del proceso paso a paso | Proceso de Llenado Paso a Paso |
| 4.4 Validación de integridad | Validación de Integridad |
| 4.4 Seguridad | Seguridad |

## Criterios de aceptación

- Los cuatro registros de cada hoja se procesan con su tratamiento correcto: `FIAT-001` y `FIAT-004` se cargan completos; `FIAT-002` (Mora) se omite con `SKIPPED_REQUIRED_EMPTY`; `FIAT-003` (Mora) se carga con su inconsistencia registrada como observación.
- Ningún dato cargado difiere de la celda de origen (tras normalización determinista).
- Ningún formulario se envía sin superar las tres compuertas de integridad.
- El esquema de cada formulario se deriva en vivo; un cambio en el form se detecta como `SCHEMA_DRIFT`, no rompe silenciosamente.
- El LLM nunca recibe valores de filas.
- El envío a los formularios reales solo ocurre con `--live`.

---

# Objetivo Final

Construir un agente autónomo que cargue registros reales de un Google Sheets en dos Google Forms replicando la navegación humana, con automatización determinista de Playwright, validación de integridad en tres compuertas, manejo explícito de errores y trampas de datos, esquema derivado en vivo, y una arquitectura segura, idempotente, escalable y desacoplada del proveedor de IA —sin inventar jamás un dato.
