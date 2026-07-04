# Importar el workflow de n8n — FADUA WooCommerce → Google Sheets

Este workflow replica en n8n la misma lógica que el script Python: cada 5 minutos
lee los productos publicados en WooCommerce, los compara por `ID` contra la
pestaña `n8n` de la planilla, agrega solo los nuevos y manda un mail resumen si
hubo al menos uno. El archivo `workflow.json` no trae ninguna credencial cargada
— eso se resuelve en 3 pasos abajo.

## Paso a paso rápido

1. Importá `workflow.json` en tu instancia de n8n.
2. Creá las 3 credenciales (nombres exactos más abajo).
3. Definí las 2 variables de entorno en el contenedor de n8n.
4. Editá el remitente del mail y activá el workflow.

### 1. Importar el JSON

Por la interfaz web:

1. Entrá a tu instancia de n8n → **Workflows**.
2. Botón **Add workflow** → menú de tres puntos (arriba a la derecha) → **Import from File**.
3. Seleccioná `n8n/workflow.json`.
4. El workflow aparece como **"FADUA - WooCommerce to Google Sheets Sync (n8n)"**, inactivo (`active: false`).

Si preferís la CLI (útil si corrés n8n en Docker):

```bash
docker cp n8n/workflow.json <contenedor_n8n>:/tmp/workflow.json
docker exec <contenedor_n8n> n8n import:workflow --input=/tmp/workflow.json
```

### 2. Crear las 3 credenciales

En n8n cada nodo referencia una credencial **por nombre**. Tenés que crear estas
tres con el nombre **exacto** que se muestra, si no el nodo va a quedar marcado
como "credencial no encontrada" y vas a tener que reasignarla manualmente.

| # | Nodo que la usa | Tipo de credencial en n8n | Nombre exacto a usar | Qué cargar |
|---|---|---|---|---|
| 1 | Get WooCommerce Products | **HTTP Basic Auth** | `WooCommerce API` | Usuario = tu `ck_...` (Consumer Key), Contraseña = tu `cs_...` (Consumer Secret). Se generan en WooCommerce → Ajustes → Avanzado → API REST. |
| 2 | Get Existing Sheet Rows / Append New Products | **Google Sheets OAuth2 API** (o Service Account) | `Google Sheets - FADUA` | OAuth2: iniciá sesión con la cuenta Google dueña o invitada a la planilla. Service Account: subís el JSON de la cuenta de servicio y le das acceso de Editor a la planilla. |
| 3 | Send Email Summary | **SMTP** | `SMTP - FADUA` | Host `smtp.gmail.com`, puerto `587`, usuario = tu Gmail, contraseña = **App Password** de 16 caracteres (no la contraseña normal de la cuenta — requiere 2FA activado). |

Notas:

- El workflow usa **OAuth2** por defecto en los nodos de Google Sheets
  (`authentication: "oAuth2"`). Si vas a usar Service Account en su lugar, abrí
  cada nodo de Google Sheets y cambiá el campo **Authentication** a
  **Service Account**, después seleccioná la credencial `Google Sheets - FADUA`
  ahí.
- El campo **Consumer Secret** de WooCommerce va en el campo **Password** de la
  credencial HTTP Basic Auth (no hay campos separados de "key"/"secret" en ese
  tipo de credencial genérica).

### 3. Variables de entorno del contenedor de n8n

El workflow lee estas dos variables con `{{ $env.NOMBRE }}`. Si tu n8n corre en
Docker, se definen en el `docker-compose.yml` del servicio `n8n`:

```yaml
services:
  n8n:
    environment:
      - WC_BASE_URL=https://fadua.ar/pruebas
      - GOOGLE_SHEET_ID=<id-de-tu-planilla-de-google-sheets>
```

| Variable | Ejemplo | Dónde se usa |
|---|---|---|
| `WC_BASE_URL` | `https://fadua.ar/pruebas` | URL base del nodo **Get WooCommerce Products** (se le agrega `/wp-json/wc/v3/products`) |
| `GOOGLE_SHEET_ID` | ID de la planilla (parte de la URL entre `/d/` y `/edit`) | Nodos **Get Existing Sheet Rows** y **Append New Products** |

Después de definirlas, reiniciá el contenedor para que n8n las tome:

```bash
docker compose restart n8n
```

### 4. Un ajuste manual: remitente del mail

El nodo **Send Email Summary** trae el campo **From Email** con un valor de
relleno: `REPLACE_WITH_SENDER_GMAIL_ADDRESS@gmail.com`. Abrí el nodo y
reemplazalo por la misma casilla Gmail que configuraste en la credencial SMTP
(Gmail exige que el remitente coincida con la cuenta autenticada).

El destinatario (`tejada.ca23@gmail.com`) ya viene fijo en el nodo, tal como pide
el challenge.

## Checklist antes de activar

- [ ] Las 3 credenciales existen con el nombre exacto de la tabla.
- [ ] `WC_BASE_URL` y `GOOGLE_SHEET_ID` están definidas en el contenedor de n8n.
- [ ] El campo **From Email** del nodo Send Email Summary fue editado.
- [ ] La planilla de Google Sheets tiene una pestaña llamada exactamente `n8n`
      con encabezados `ID | Producto | Precio | Imagen | Sincronizado`.
- [ ] Corriste una ejecución manual (**Execute workflow**) para confirmar que
      no tira errores antes de activar el Schedule Trigger.

## Siguiente paso

Activá el workflow (toggle **Active** arriba a la derecha). A partir de ahí
corre solo cada 5 minutos — no hace falta cron externo, el Schedule Trigger
vive dentro de n8n.
