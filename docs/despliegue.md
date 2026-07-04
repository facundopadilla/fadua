# Despliegue

Guía para dejar el sistema andando en el VPS (Ubuntu 22.04 con Docker). Antes de tocar el servidor hay que preparar las credenciales de afuera, que es la parte más tediosa pero se hace una sola vez.

## 1. Google: cuenta de servicio y planilla

La cuenta de servicio es un "usuario robot" de Google que el script usa para entrar a la planilla sin la contraseña de nadie.

1. Entrá a [Google Cloud Console](https://console.cloud.google.com/) y creá un proyecto (o usá uno que ya tengas).
2. Habilitá la **Google Sheets API** y la **Google Drive API** en ese proyecto.
3. Creá una **cuenta de servicio** y, dentro de ella, una clave de tipo JSON. Se descarga un archivo: ese es tu `service-account.json`.
4. Abrí ese JSON y copiá el valor de `client_email` (algo como `nombre@proyecto.iam.gserviceaccount.com`).

Ahora la planilla:

1. Creá una planilla nueva en Google Sheets.
2. Hacé dos pestañas: una llamada `python` y otra `n8n`. En la fila 1 de cada una poné los encabezados: `ID`, `Producto`, `Precio`, `Imagen`, `Sincronizado`.
3. Compartila con **acceso de editor** con dos direcciones: el `client_email` de la cuenta de servicio y `tejada.ca23@gmail.com`.
4. El ID de la planilla es la parte de la URL entre `/d/` y `/edit`. Guardalo, lo vas a necesitar como `GOOGLE_SHEET_ID`.

## 2. Gmail: App Password

Los mails salen por SMTP de Gmail. No se usa la contraseña normal de la cuenta sino una clave de aplicación.

1. La cuenta de Gmail que va a mandar los avisos tiene que tener la **verificación en dos pasos** activada.
2. Entrá a [App Passwords](https://myaccount.google.com/apppasswords) y generá una. Son 16 caracteres.
3. Esa clave es tu `SMTP_APP_PASSWORD`, y el mail de esa cuenta es tu `SMTP_USER`.

## 3. WooCommerce

Las claves ya están generadas para este challenge (`ck_...` y `cs_...`). Si hiciera falta rehacerlas, se crean en WooCommerce, en Ajustes → Avanzado → API REST, con permiso de lectura.

## 4. Versión Python en el servidor

```bash
# instalar uv (si no está)
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone <repo> fadua-woo-sheets-sync
cd fadua-woo-sheets-sync/python
uv sync

cp .env.example .env      # completá las credenciales reales
chmod 600 .env            # solo tu usuario lo lee
# copiá el service-account.json a esta carpeta
chmod 600 service-account.json
```

El `.env` (y su plantilla `.env.example`) tienen estas variables:

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
```

Probá una corrida a mano antes de programar nada:

```bash
uv run python -m sync
```

Si vuelve sin errores y la fila aparece en la pestaña `python`, ya está. Programá el cron con `crontab -e` (ajustá las rutas):

```cron
*/5 * * * * /usr/bin/flock -n /tmp/fadua-sync.lock -c 'cd /home/USUARIO/fadua-woo-sheets-sync/python && /home/USUARIO/.local/bin/uv run python -m sync'
```

## 5. Versión n8n en el servidor

```bash
cd fadua-woo-sheets-sync/n8n
```

Creá un `.env` al lado del `docker-compose.yml` con estas dos variables:

```
GOOGLE_SHEET_ID=el-id-de-tu-planilla
N8N_ENCRYPTION_KEY=una-clave-larga-e-inventada-que-no-cambies-nunca
```

Levantá el contenedor:

```bash
docker compose up -d
```

Entrá a `http://IP-DEL-VPS:5678`, importá `workflow.json` y seguí los pasos de [`../n8n/README-import.md`](../n8n/README-import.md) para cargar las tres credenciales y activar el workflow.

## Ensayo antes de la prueba con FADUA

Conviene ensayar el escenario exacto que van a hacer ellos. Las claves de WooCommerce tienen permiso de escritura, así que se puede crear un producto de prueba, esperar a que aparezca en las dos pestañas y llegue el mail, y después borrarlo. Así llegás a la demo sabiendo que las dos versiones responden como tienen que responder.
