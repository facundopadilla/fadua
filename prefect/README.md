# Versión con Prefect

La misma sincronización que `python/`, pero orquestada con Prefect en lugar de un cron plano. Lo que cambia es la observabilidad: cada corrida queda registrada en una UI con su estado, sus logs y sus reintentos, y podés pausar el schedule desde el navegador sin tocar el servidor.

Es una carpeta autónoma. Trae su propia copia de la lógica del sync en `sync/`, así que se levanta sola sin depender de `python/`.

## Cómo se estructura

```
sync/
  woocommerce.py   cliente de la API con reintentos
  diff.py          detección de productos nuevos por ID
  sheets.py        lectura y escritura en Google Sheets
  notifier.py      email de resumen por SMTP
  config.py        carga de credenciales desde el entorno
  prefect_flow.py  el flow: orquesta los pasos como tasks
Dockerfile         imagen del runner
docker-compose.yml server de Prefect + runner
```

El flow envuelve cada adaptador en una task, así en la UI ves el recorrido paso a paso: traer productos, leer la planilla, detectar nuevos, agregar filas, avisar por mail.

## Cómo levantarlo

```bash
cp .env.example .env      # completá las credenciales reales
# dejá el service-account.json en esta carpeta
docker compose up -d --build
```

Arranca dos contenedores: el server de Prefect (UI y API en el `:4200`) y el runner que corre el flow cada 5 minutos. La UI queda en `http://localhost:4200`. Para exponerla en un dominio y ver cómo pausar el schedule, mirá `../docs/despliegue.md`.

## Variables (en `.env`)

```
WC_BASE_URL=https://fadua.ar/pruebas
WC_CONSUMER_KEY=ck_tu_consumer_key
WC_CONSUMER_SECRET=cs_tu_consumer_secret
GOOGLE_SHEET_ID=id_de_tu_planilla
GOOGLE_SHEET_TAB=python
GOOGLE_SA_JSON=./service-account.json
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu_gmail_remitente@gmail.com
SMTP_APP_PASSWORD=tu_app_password_de_gmail
NOTIFY_TO=tejada.ca23@gmail.com
PREFECT_UI_API_URL=http://localhost:4200/api
```

## Seguridad

Cada task carga las credenciales desde el entorno en vez de recibirlas como argumento. Prefect registra los argumentos de las tasks, así que pasarle el `config` con el App Password lo dejaría visible en la UI. Entre tasks solo viajan los datos de los productos, que son públicos.
