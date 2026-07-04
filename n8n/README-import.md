# Importar el workflow de n8n — FADUA WooCommerce → Google Sheets

Este workflow hace lo mismo que las versiones de Python y Prefect: cada 5 minutos lee los productos publicados de WooCommerce, los compara por `ID` contra la pestaña `n8n` de la planilla y clasifica cada producto como alta (ID nuevo) o cambio (ID existente con Producto, Precio o Imagen distintos). Agrega las altas y actualiza en su misma fila los que cambiaron (sin duplicar), y manda un mail resumen si hubo al menos una alta o un cambio.

La URL de WooCommerce ya viene puesta dentro del workflow (n8n bloquea el acceso a `$env` por defecto, por eso va escrita directo). El ID de la planilla es un placeholder que reemplazás en los dos nodos de Google Sheets. Además tenés que cargar las tres credenciales.

## 1. Importar el JSON

Por la interfaz: **Workflows** → **Add workflow** → menú de tres puntos → **Import from File** → elegí `workflow.json`.

Aparece como **"FADUA - WooCommerce to Google Sheets Sync (n8n)"**, inactivo.

## 2. Crear las tres credenciales

Cada nodo referencia una credencial **por nombre**. Creá estas tres con el nombre **exacto**, si no el nodo queda marcado como "credencial no encontrada".

| Nombre exacto | Tipo de credencial | Qué cargar |
|---|---|---|
| `WooCommerce API` | **Basic Auth** (HTTP Basic Auth) | Usuario = tu `ck_...`, Contraseña = tu `cs_...` |
| `Google Sheets - FADUA` | **Google Service Account API** | Service Account Email y Private Key, sacados del `service-account.json` (ver abajo) |
| `SMTP - FADUA` | **SMTP** | Host `smtp.gmail.com`, puerto `587`, usuario = tu Gmail, contraseña = App Password de 16 caracteres |

### La credencial de Google (Service Account)

Abrí el `service-account.json` y copiá dos campos a la credencial:

- `client_email` → va en el campo **Service Account Email**.
- `private_key` → va en el campo **Private Key** (pegá todo el bloque, incluido `-----BEGIN PRIVATE KEY-----` y los saltos de línea).

**Y lo más importante:** compartí la planilla (botón Compartir, como Editor) con ese `client_email`. Sin ese paso, Google devuelve 403 y el workflow falla.

## 3. Asignar las credenciales a los nodos

Después de crear las credenciales, abrí cada nodo y confirmá que quedó seleccionada la credencial correcta (n8n las suele enganchar por nombre, pero conviene verificar):

- **Get WooCommerce Products** → `WooCommerce API`
- **Get Existing Sheet Rows** → `Google Sheets - FADUA`
- **Append or Update Products** → `Google Sheets - FADUA`
- **Send Email Summary** → `SMTP - FADUA`

## 3b. Poner el ID de tu planilla

En los nodos **Get Existing Sheet Rows** y **Append or Update Products**, en el campo **Document ID** reemplazá `YOUR_GOOGLE_SHEET_ID` por el ID de tu planilla (la parte de la URL entre `/d/` y `/edit`).

## 4. Ajustar el remitente del mail

En el nodo **Send Email Summary**, el campo **From Email** trae `REPLACE_WITH_SENDER_GMAIL_ADDRESS@gmail.com`. Reemplazalo por la misma casilla Gmail de la credencial SMTP (Gmail exige que el remitente coincida con la cuenta autenticada). El destinatario ya viene fijo en `tejada.ca23@gmail.com`.

## 5. Confirmar la pestaña

La planilla tiene que tener una pestaña llamada exactamente `n8n`, con los encabezados en la fila 1: `ID | Producto | Precio | Imagen | Sincronizado`.

## 6. Probar y activar

1. Con el workflow abierto, tocá **Execute workflow** para una corrida manual. Si la pestaña `n8n` está vacía, debería agregar los productos publicados y mandarte el mail.
2. Si sale todo bien, activá el workflow con el toggle **Active**. A partir de ahí corre solo cada 5 minutos: el Schedule Trigger vive dentro de n8n, no necesita cron externo.

## Levantar n8n con Docker

En el VPS, con el `docker-compose.yml` de esta carpeta:

```bash
cd n8n
# creá un .env al lado del compose con:
#   N8N_ENCRYPTION_KEY=una-clave-larga-inventada-que-no-cambies-nunca
docker compose up -d
```

La UI queda en `http://IP-DEL-VPS:5678`.

## Checklist antes de activar

- [ ] Las tres credenciales existen con el nombre exacto de la tabla.
- [ ] La planilla está compartida con el `client_email` del service account.
- [ ] Cada nodo tiene su credencial asignada.
- [ ] El **From Email** del nodo de correo fue editado.
- [ ] La pestaña `n8n` existe con sus encabezados.
- [ ] Una corrida manual (**Execute workflow**) terminó sin errores.
