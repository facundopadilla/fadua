# FADUA · WooCommerce → Google Sheets

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/uv-managed-DE5FE9?logo=astral&logoColor=white)
![Prefect](https://img.shields.io/badge/Prefect-orchestration-070E10?logo=prefect&logoColor=white)
![n8n](https://img.shields.io/badge/n8n-low--code-EA4B71?logo=n8n&logoColor=white)
![WooCommerce](https://img.shields.io/badge/WooCommerce-REST%20API-96588A?logo=woocommerce&logoColor=white)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-API-34A853?logo=googlesheets&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![tests](https://img.shields.io/badge/tests-8%20passing-brightgreen)

Cada 5 minutos revisa los productos publicados de una tienda WooCommerce, agrega los nuevos a una planilla de Google Sheets y avisa por mail. Está resuelto en tres carpetas independientes, cada una con su forma de ejecutarlo: un script de Python por cron, la misma lógica orquestada con Prefect (con UI), y un workflow de n8n.

## Stack

- **Python 3.11+** con [uv](https://docs.astral.sh/uv/) — `requests`, `gspread`, `google-auth`.
- **Prefect 3** para orquestar el sync con una UI donde ves cada corrida y pausás el schedule.
- **n8n** como alternativa low-code, sobre Docker.
- **WooCommerce REST API v3** como origen de los productos.
- **Google Sheets API** con cuenta de servicio como destino.
- **SMTP de Gmail** para los avisos.

## Estructura

```
python/    la lógica del sync + tests, para correr por cron
prefect/   la misma lógica orquestada con Prefect (UI + Docker)
n8n/       el mismo flujo como workflow low-code
docs/      explicación técnica y guía de despliegue
```

Las tres carpetas son autónomas: cada una se levanta sola. `python/` y `prefect/` comparten la lógica del sync (cada una con su copia); la diferencia es cómo se ejecuta y qué visibilidad da.

## Cómo levantarlo

### Python por cron

```bash
cd python
uv sync
cp .env.example .env       # completá las credenciales reales
uv run python -m sync      # corrida de prueba
```

```cron
*/5 * * * * /usr/bin/flock -n /tmp/fadua-sync.lock -c 'cd /ruta/al/repo/python && uv run python -m sync'
```

### Prefect (con UI)

```bash
cd prefect
cp .env.example .env       # completá las credenciales reales
# y dejá el service-account.json en esta carpeta
docker compose up -d --build
```

La UI queda en `http://localhost:4200`: ves cada corrida con su estado y sus logs, y podés pausar el schedule. Detalles en [`prefect/README.md`](prefect/README.md).

### n8n

```bash
cd n8n
docker compose up -d
```

Entrá a `http://localhost:5678`, importá `workflow.json` y cargá las credenciales. El paso a paso está en [`n8n/README-import.md`](n8n/README-import.md).

## Documentación

- [`docs/explicacion-tecnica.md`](docs/explicacion-tecnica.md) — cómo funciona por dentro y por qué se decidió así.
- [`docs/despliegue.md`](docs/despliegue.md) — setup completo de credenciales, el stack de Prefect y el VPS.
