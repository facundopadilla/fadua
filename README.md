# FADUA · WooCommerce → Google Sheets

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/uv-managed-DE5FE9?logo=astral&logoColor=white)
![n8n](https://img.shields.io/badge/n8n-low--code-EA4B71?logo=n8n&logoColor=white)
![WooCommerce](https://img.shields.io/badge/WooCommerce-REST%20API-96588A?logo=woocommerce&logoColor=white)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-API-34A853?logo=googlesheets&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![tests](https://img.shields.io/badge/tests-8%20passing-brightgreen)

Cada 5 minutos revisa los productos publicados de una tienda WooCommerce, agrega los nuevos a una planilla de Google Sheets y avisa por mail. Está resuelto de dos maneras que corren en paralelo, cada una en su propia pestaña: un script de Python por cron y un workflow de n8n.

## Stack

- **Python 3.10+** con [uv](https://docs.astral.sh/uv/) — `requests`, `gspread`, `google-auth`.
- **n8n** como alternativa low-code, sobre Docker.
- **WooCommerce REST API v3** como origen de los productos.
- **Google Sheets API** con cuenta de servicio como destino.
- **SMTP de Gmail** para los avisos.

## Estructura

```
python/   script Python + tests, se ejecuta por cron
n8n/      workflow.json + docker-compose
docs/     explicación técnica y guía de despliegue
```

## Cómo levantarlo

### Python

```bash
cd python
uv sync                    # instala dependencias
cp .env.example .env       # completá las credenciales reales
uv run python -m sync      # corrida de prueba
```

Para dejarlo andando cada 5 minutos (el `flock` evita corridas superpuestas):

```cron
*/5 * * * * /usr/bin/flock -n /tmp/fadua-sync.lock -c 'cd /ruta/al/repo/python && uv run python -m sync'
```

### n8n

```bash
cd n8n
docker compose up -d
```

Entrá a `http://localhost:5678`, importá `workflow.json` y cargá las credenciales. El paso a paso está en [`n8n/README-import.md`](n8n/README-import.md).

## Documentación

- [`docs/explicacion-tecnica.md`](docs/explicacion-tecnica.md) — cómo funciona por dentro y por qué se decidió así.
- [`docs/despliegue.md`](docs/despliegue.md) — setup completo de credenciales de Google, Gmail y el VPS.
