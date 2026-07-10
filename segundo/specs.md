# AI Analytics Chatbot
## Especificación Técnica (v2)

---

# Objetivo

Desarrollar un chatbot conversacional basado en Inteligencia Artificial capaz de responder consultas en lenguaje natural sobre métricas comerciales, campañas publicitarias y ventas utilizando información almacenada en una base de datos MySQL.

El sistema deberá:

- Consultar datos reales.
- Calcular KPIs dinámicamente.
- Realizar análisis comparativos.
- Detectar tendencias.
- Generar proyecciones.
- Mostrar gráficos cuando corresponda.
- Mantener contexto durante la conversación.
- Nunca inventar información.

La IA actuará como un **Analista de Datos Comercial**.

---

# Principios de Arquitectura

- La base de datos es la única fuente de verdad.
- El LLM nunca consulta MySQL directamente.
- Todas las consultas pasan por herramientas controladas (Tools).
- Toda respuesta debe poder justificarse mediante datos reales.
- El modelo estadístico realiza las predicciones.
- El LLM únicamente interpreta y explica los resultados.

---

# Stack Tecnológico

## Frontend

- React
- Vite
- Typescript
- TailwindCSS
- shadcn/ui
- TanStack Query
- React Markdown
- Recharts

---

## Backend

- FastAPI
- PydanticAI
- SQLAlchemy
- Pandas
- Prophet
- sqlglot
- Pydantic
- Docker
- uv

---

## Base de datos

MySQL

---

## Modelo LLM

- Modelos de OpenCode GO (a través de las API's), como Qwen, Minimax, GLM, etc...

El proveedor deberá poder reemplazarse fácilmente.

---

# Arquitectura

```
                React

                   │

             REST / SSE

                   │

                FastAPI

                   │

           PydanticAI Agent

                   │

         Intent Planner Layer

                   │

     ┌─────────────┼─────────────┐

     ▼             ▼             ▼

 SQL Tool     Analytics Tool   Forecast Tool

     │             │             │

     └─────────────┼─────────────┘

                   ▼

                MySQL
```

---

# Arquitectura del Proyecto

```
backend/

app/

    api/

    agent/

    planner/

    database/

    models/

    prompts/

    services/

    tools/

    forecasting/

    analytics/

    charts/

    schemas/

    utils/

frontend/

src/

    pages/

    components/

    services/

    hooks/

    types/

    layouts/

```

---

# Flujo General

```
Usuario

↓

React

↓

FastAPI

↓

Planner

↓

Selecciona herramienta

↓

Ejecuta herramienta

↓

Obtiene datos

↓

LLM redacta respuesta

↓

Frontend
```

---

# Planner (Clasificador de Intención)

Antes de llamar al modelo principal, el sistema clasificará automáticamente el tipo de consulta.

Tipos soportados:

- SQL
- KPI
- Comparación
- Forecast
- Visualización
- Conversación

Ejemplos

```
¿Cuántas ventas hubo?

↓

SQL
```

```
¿Cuál fue el ROAS?

↓

KPI
```

```
Compará Google Ads con Meta Ads

↓

Analytics
```

```
¿Cuántas ventas habrá el próximo mes?

↓

Forecast
```

```
Mostrame la evolución de ingresos

↓

Chart
```

Esto evita ejecutar lógica innecesaria y mejora la precisión.

---

# Base de Datos

Tabla

```
metricas_campanas_ventas
```

Campos

- fecha
- google_ads_impresiones
- google_ads_clics
- google_ads_costo_usd
- google_ads_leads
- meta_ads_impresiones
- meta_ads_clics
- meta_ads_costo_usd
- meta_ads_leads
- total_leads
- cantidad_ventas
- vehiculo_tipo_principal
- vehiculo_modelo_principal
- ingresos_ventas_usd

---

# Business Dictionary

El sistema tendrá una capa semántica que traducirá conceptos del negocio.

Ejemplo

```python
{
    "clientes": "cantidad_ventas",
    "ventas": "cantidad_ventas",
    "facturación": "ingresos_ventas_usd",
    "ingresos": "ingresos_ventas_usd",
    "gasto": "google_ads_costo_usd + meta_ads_costo_usd",
    "inversión": "google_ads_costo_usd + meta_ads_costo_usd",
    "ads": [
        "google_ads",
        "meta_ads"
    ]
}
```

Esto permite entender consultas sin depender del nombre exacto de las columnas.

---

# Capacidades

## Consultas

- ventas
- leads
- ingresos
- inversión
- impresiones
- clics
- costos
- modelos
- vehículos
- mejores meses
- peores meses

---

## Comparaciones

- Google Ads vs Meta Ads
- Mes contra mes
- Año contra año
- Modelos de vehículos
- Tipo de vehículo
- Inversión
- Conversión

---

## KPIs

CTR

CPC

CPL

CPA

ROAS

ROI

Conversion Rate

Costo por Venta

Costo Total

Ingresos Totales

---

# KPIs Calculados

CTR

```
Clicks / Impresiones
```

---

CPC

```
Costo / Clicks
```

---

CPL

```
Costo / Leads
```

---

CPA

```
Costo Total / Ventas
```

---

ROAS

```
Ingresos / Costo Total
```

---

ROI

```
(Ingresos - Costos)
/ Costos
```

---

Conversion Rate

```
Ventas / Leads
```

---

# Tipos de Herramientas

## execute_sql()

Ejecuta consultas SQL.

Solo permite

- SELECT

Nunca

- UPDATE
- DELETE
- DROP
- ALTER
- INSERT
- TRUNCATE

---

## calculate_kpis()

Calcula indicadores comerciales.

---

## forecast_sales()

Predicción de ventas.

---

## forecast_leads()

Predicción de leads.

---

## forecast_income()

Predicción de ingresos.

---

## create_chart()

Genera visualizaciones.

Tipos

- line
- bar
- pie
- area

---

## summarize_dataset()

Resume datasets grandes antes de enviarlos al LLM.

Reduce consumo de tokens.

---

# SQL Security Layer

Antes de ejecutar una consulta

```
LLM

↓

SQL

↓

sqlglot

↓

Parser AST

↓

Validación

↓

MySQL
```

Validaciones

- Solo SELECT
- Solo tabla autorizada
- Columnas válidas
- Sin subconsultas peligrosas
- Sin funciones prohibidas

---

# Prompt del Agente

El agente conocerá

- Nombre de la tabla
- Columnas
- Definición de KPIs
- Reglas comerciales
- Ejemplos SQL
- Restricciones
- Buenas prácticas

Nunca deberá inventar datos.

---

# Few Shot Learning

Ejemplos incluidos

Pregunta

¿Cuántas ventas hubo este año?

↓

SQL esperado

---

Pregunta

¿Cuál fue el mejor mes?

↓

SQL esperado

---

Pregunta

¿Cuál fue el ROAS?

↓

SQL esperado

---

Pregunta

¿Cuál fue el mejor modelo?

↓

SQL esperado

---

# Forecast

Motor

Prophet

Series

- ventas
- leads
- ingresos
- inversión

El modelo genera la predicción.

El LLM únicamente redacta la explicación.

---

# Visualizaciones

Consulta temporal

↓

Gráfico Línea

---

Ranking

↓

Gráfico Barra

---

Distribución

↓

Pie Chart

---

Comparaciones

↓

Grouped Bar

---

# Memoria Conversacional

Mantendrá contexto.

Ejemplo

Usuario

```
¿Cuál fue el mejor mes?
```

↓

Febrero

↓

Usuario

```
¿Y cuál fue el peor?
```

El sistema comprenderá que continúa hablando de ventas.

---

# Respuesta Estructurada

Todas las respuestas del backend utilizarán modelos Pydantic.

```python
class ChatResponse(BaseModel):

    answer: str

    sql: str | None

    chart: ChartConfig | None

    metrics: dict[str, float]

    suggestions: list[str]

    execution_time: float

    confidence: float
```

Esto permitirá al frontend renderizar automáticamente:

- gráficos
- tarjetas KPI
- métricas
- sugerencias
- historial

Sin necesidad de interpretar texto libre.

---

# Frontend

Características

- Chat tipo ChatGPT
- Streaming
- Markdown
- Gráficos
- Historial
- Dark Mode
- Copiar respuesta
- Mostrar SQL (modo debug)
- Tiempo de ejecución
- Indicador de carga

---

# Logging

Registrar

- SQL generado
- Tiempo
- Tokens
- Costo
- Errores
- Herramienta utilizada
- Tipo de consulta
- Modelo utilizado

---

# Manejo de Errores

Casos

- Error SQL
- Timeout
- Sin resultados
- Error LLM
- Error Forecast
- Error conexión MySQL

Todos deberán devolver respuestas amigables al usuario.

---

# Escalabilidad

Preparado para incorporar

- múltiples tablas
---

# Objetivo Final

Construir un **AI Analytics Assistant** capaz de interpretar lenguaje natural, consultar datos reales, calcular indicadores de negocio, generar análisis y proyecciones, y responder de manera conversacional con una arquitectura modular, segura, escalable y desacoplada del proveedor de LLM.
