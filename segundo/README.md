# AI Analytics Chatbot

Un chatbot conversacional que actúa como "Analista de Datos Comercial". Se le pueden hacer preguntas en español, en lenguaje natural, sobre campañas publicitarias y ventas de vehículos (KPIs, comparaciones, pronósticos, gráficos) y responde siempre a partir de datos reales en MySQL, sin inventar números. Tiene dos modos de funcionamiento: un agente LLM con tool-calling cuando hay una key configurada, o un planificador determinístico basado en reglas cuando no la hay.

## Stack

| Capa | Tecnología |
|-------|------|
| Backend | FastAPI, PydanticAI, SQLAlchemy, pandas, Prophet, sqlglot — dependencias gestionadas con `uv` |
| Frontend | React 19, Vite, Tailwind v4, Recharts, TanStack Query, react-markdown |
| LLM | [OpenCode GO](https://opencode.ai/zen/go/v1) (compatible con OpenAI), 20 modelos seleccionables |
| Datos | MySQL 8, con datos sintéticos de ejemplo que se cargan solos en el primer arranque |
| Memoria | Redis, por conversación, TTL de 14 días |

## Requisitos previos

- Docker + Docker Compose
- [`uv`](https://docs.astral.sh/uv/) (gestor de paquetes de Python)
- Node.js 20+

## Camino rápido

### 1. Levantar la infraestructura

Desde la raíz del repo:

```bash
docker compose up
```

Esto levanta MySQL y Redis. MySQL carga automáticamente los datos de ejemplo (`db/init.sql`, unas 547 filas diarias que cubren cerca de 18 meses) la primera vez que se crea su volumen.

> El servicio `api` también está definido en `docker-compose.yml` y puede levantar el backend en un contenedor: ver [Puertos](#puertos) si se usa esta opción en lugar del paso 2. Para desarrollo local conviene correr el backend directamente (paso 2), porque el reload es más rápido.

### 2. Configurar y correr el backend

```bash
cd backend
cp env.example .env
# editar .env: configurar LLM_API_KEY (ver Configuración más abajo)
uv sync
uv run uvicorn app.main:app --reload --env-file .env
```

### 3. Correr el frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Abrir la app

Ir a la URL que imprime Vite (por defecto `http://localhost:5173`) y empezar a chatear.

## Configuración

Copiar la plantilla y completar la key:

```bash
cp backend/env.example backend/.env
```

El único valor que hace falta configurar es `LLM_API_KEY`, que se obtiene desde la cuenta de OpenCode GO. El resto de las variables en `env.example` ya trae un valor por defecto que funciona para desarrollo local.

Sin `LLM_API_KEY` configurada, el backend sigue funcionando: cae al planificador determinístico (ver [Cómo funciona](#cómo-funciona) más abajo). Con la key configurada se habilita el tool-calling conversacional completo.

## Puertos

La referencia real es `docker-compose.yml`; si algo de acá queda desactualizado, ese archivo manda.

| Servicio | Puerto en el host | Notas |
|---------|-----------|-------|
| `api` (backend, en contenedor) | `8010` | Mapeado desde el puerto `8000` del contenedor, porque el `8000` del host ya estaba ocupado. Si en cambio se corre el backend con `uvicorn` directamente (paso 2), escucha en `8000`. |
| `mysql` | `3306` | Usuario/contraseña/base: `analytics` / `analytics` / `analytics` |
| `redis` | `6379` | Con persistencia AOF habilitada |
| frontend (servidor de Vite) | `5173` | Puerto por defecto de Vite; se imprime al correr `npm run dev` |

## Despliegue en producción

Producción usa una topología distinta a la de desarrollo. Hay un único punto de entrada público, el **nginx del frontend**, que sirve la SPA compilada y además hace de proxy reverso de `/api/` hacia el backend interno. **MySQL queda afuera** (una instancia gestionada o un servidor propio, no un contenedor); el backend se conecta a través de `DATABASE_URL`. Redis se mantiene en un contenedor, con persistencia AOF. Archivos involucrados: `docker-compose.prod.yml`, `frontend/Dockerfile`, `frontend/nginx.conf`, `.env.production.example`.

Desde este directorio (`segundo/`):

```bash
# 1. Crear el .env de producción a partir de la plantilla y completarlo
cp .env.production.example .env
#    - DATABASE_URL  -> el MySQL de producción EXTERNO (no un contenedor)
#    - LLM_API_KEY   -> la key de OpenCode GO

# 2. Cargar los datos de ejemplo en el MySQL externo (en producción no hay contenedor que monte el seed)
mysql -h YOUR_PROD_MYSQL_HOST -u USER -p DBNAME < db/init.sql

# 3. Compilar y levantar (el primer build es lento porque el backend instala Prophet)
docker compose -f docker-compose.prod.yml up -d --build
```

La app queda expuesta en el **puerto 80** (`http://<tu-host>/`). Para usar otro puerto en el host, cambiar `ports: ["80:80"]` por, por ejemplo, `"8080:80"` en `docker-compose.prod.yml`.

Cómo se resuelve la ruta de la API: la SPA se compila con `VITE_API_URL=/api`, así que el navegador llama a `/api/chat`, `/api/health`, `/api/models`, todo bajo el mismo origen. nginx (`frontend/nginx.conf`) redirige `location /api/` hacia `http://api:8000/` con una barra final, lo que **elimina el prefijo `/api`**, así que el backend recibe `/chat`, `/health`, `/models` (sus rutas reales). Como todo queda en el mismo origen, no hace falta configurar `CORS_ORIGINS` salvo que el frontend se sirva desde un origen distinto.

Nota sobre SSE: el bloque `/api/` de nginx desactiva el buffering y el caché, y fija `proxy_read_timeout 300s` para que las respuestas en streaming largas (deepseek puede tardar 60s o más) no se corten.

Redis corre en un contenedor por defecto, con persistencia mediante un volumen nombrado más AOF. Para apuntar a una instancia externa o gestionada, configurar `REDIS_URL` en `.env` con esa instancia y, si se quiere, sacar el servicio `redis` de `docker-compose.prod.yml`.

Lo que no cubre este documento (queda fuera del alcance del MVP, según `CLAUDE.md`): terminación TLS/HTTPS, autenticación de la API y rate-limiting. Hay que agregar esto antes de exponer el proyecto públicamente de verdad.

## Cómo funciona

Cada request de chat intenta primero el agente LLM con tool-calling (cuando `LLM_API_KEY` está configurada): un agente de PydanticAI decide qué tool controlada invocar (`run_sql`, `compute_kpis`, `forecast` con Prophet, `make_chart`) y redacta la respuesta final sobre los resultados reales que esas tools devuelven. Si ese camino falla por cualquier motivo (falta la key, error de red, problema del proveedor), el backend cae de forma transparente a un planificador determinístico basado en reglas, más un motor de templates, que responde de la misma manera pero sin ningún LLM de por medio.

En los dos modos, ni el LLM ni el planificador **tocan MySQL directamente**. Todo acceso a datos pasa por `run_sql`, validado por un guard de SQL basado en AST: solo `SELECT`, una única tabla autorizada (`metricas_campanas_ventas`), una lista blanca de columnas y otra de funciones bloqueadas. Esta es la garantía central del proyecto: el chatbot no puede inventar cifras.

Las respuestas viajan por SSE: los eventos `token` renderizan la respuesta en vivo, y al final llega un evento `done` con la respuesta estructurada completa (texto, SQL usado, configuración del gráfico, métricas, sugerencias, confianza, tiempo de ejecución).

Desde el selector de modelos en la interfaz se puede elegir, request a request, entre los 20 modelos disponibles de OpenCode GO. `deepseek-v4-pro` (el que viene por defecto) es el más confiable a la hora de efectivamente ejecutar los tool calls. Otros modelos, como kimi o minimax, tienden a narrar el plan en vez de llevarlo a cabo.

## Para saber más

- [`specs.md`](./specs.md) — especificación técnica original (en español)
- [`CLAUDE.md`](./CLAUDE.md) — arquitectura, invariantes y decisiones de diseño ya cerradas
