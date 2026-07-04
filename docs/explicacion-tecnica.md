# Explicación técnica

Este documento responde las cuatro preguntas de la evaluación de FADUA. Está pensado para acompañar la charla por Meet, así que va directo a cada una.

## Cómo se estructuró la integración

Hay tres piezas: WooCommerce como origen, la planilla de Google como destino, y el correo como aviso. En el medio va la lógica de sincronización, que armé dos veces con la misma cabeza pero distinta herramienta.

La versión Python es un paquete chico (`python/sync/`) donde cada archivo hace una sola cosa:

- `woocommerce.py` habla con la API y devuelve los productos ya limpios.
- `sheets.py` lee los IDs que hay en la planilla y agrega filas.
- `diff.py` compara y decide qué es nuevo. Es una función pura, sin efectos, y es lo único que tiene tests.
- `notifier.py` arma y manda el mail.
- `config.py` carga las credenciales desde el `.env`.
- `__main__.py` es el director de orquesta: llama a los demás en orden y decide qué pasa si algo falla.

Separé así por una razón práctica: `diff.py` es la parte que tiene que estar bien sí o sí, y al aislarla puedo probarla con datos de mentira sin tocar WooCommerce ni Google. El resto son adaptadores hacia servicios externos.

La versión n8n es el mismo recorrido en nodos: un disparador cada 5 minutos, un nodo HTTP que pega a WooCommerce, la lectura de la planilla, un nodo de código que hace el diff, el agregado de filas y el mail. Elegí que las dos escriban en pestañas separadas (`python` y `n8n`) para que se puedan mirar en paralelo sin que una tape lo que hizo la otra.

Las dos leen la URL de la tienda y el ID de la planilla desde variables de entorno. Nada de eso está escrito en el código.

## Qué medidas de seguridad tomé con las credenciales

La regla que me puse fue simple: ninguna credencial vive en el código ni entra al repositorio.

En Python las credenciales están en un `.env` y en un `service-account.json`. Los dos figuran en `.gitignore`, así que git no los ve. Lo que sí se versiona es un `.env.example` con los nombres de las variables y valores de relleno, para que se entienda qué hay que completar sin filtrar nada. En el servidor esos dos archivos van con permisos `600`, o sea que solo el usuario dueño los puede leer.

En n8n las credenciales se guardan en su almacén interno, que las cifra. El `workflow.json` que entrego no las lleva adentro: cada nodo referencia la credencial por nombre, y n8n las vuelve a pedir cuando importás el archivo. Lo verifiqué buscando las claves dentro del JSON antes de entregarlo y no aparece ninguna.

Después está el principio de mínimo privilegio. La cuenta de servicio de Google tiene acceso de editor a esa planilla y a ninguna otra cosa. La clave de Gmail no es la contraseña de la cuenta sino un App Password, que se puede revocar cuando quieras sin tocar el resto. Y las claves de WooCommerce viajan siempre por HTTPS.

## Con qué criterio diseñé el flujo de datos

La pregunta que definió todo fue: ¿cómo sé qué productos ya sincronicé? Tenía tres caminos.

Podía guardar en el servidor un archivo con los IDs ya vistos. Podía pedirle a WooCommerce solo los productos creados después de la última corrida. O podía usar la propia planilla como fuente de verdad y comparar contra lo que ya tiene.

Descarté el segundo enseguida, y con evidencia. Cuando sondeé la API me encontré con que los borradores tienen la fecha de creación en `null`, y un borrador que se publica más tarde conserva la fecha vieja. Un filtro por fecha se perdería esos productos, que es exactamente lo que FADUA va a cargar en la prueba. Filtrar por fecha era frágil justo donde no podía serlo.

Entre el archivo de estado y la planilla, elegí la planilla. Un archivo de estado es una segunda copia de la verdad, y toda segunda copia se termina desincronizando: si alguien edita la planilla a mano, el archivo ya no sabe lo que pasó. Usar la planilla como memoria hace que el sistema sea idempotente. Correrlo una vez o diez veces da el mismo resultado, porque siempre compara contra el estado real. Si borrás una fila, vuelve. Si se cae a la mitad, la próxima se recupera. El costo es una lectura extra a Google por corrida, que a esta escala no se nota.

El flujo entonces quedó así: traigo los publicados, leo los IDs de la planilla, me quedo con los que faltan, los agrego con un timestamp de cuándo los tomó el cron, y recién ahí, si hubo alguno nuevo, mando el mail. La primera corrida encuentra la planilla vacía y carga todo. Eso no es un caso especial que haya que programar aparte, es el mismo diff funcionando contra un conjunto vacío.

## Cómo manejo los errores

El caso que plantea la consigna, que WooCommerce no responda, lo tomé como el escenario principal, no como un extra.

Cuando pido los productos, si la API falla reintento tres veces con esperas que se van agrandando (1 segundo, después 2). Si igual no contesta, no invento nada ni sigo con datos a medias: dejo el error en el log y termino la corrida sin tocar la planilla. Acá se nota por qué el diseño idempotente ayuda tanto. Como la planilla es la fuente de verdad y no hay estado que corregir, la corrida que viene cinco minutos después arranca limpia y se pone al día sola. No se pierde ningún producto por un rato de caída.

Hay un orden que respeté a propósito: primero agrego las filas, después mando el mail. Si el mail falla cuando las filas ya se escribieron, dejo el error en el log pero no hago fallar la corrida. Prefiero que los datos queden guardados aunque el aviso no salga, y no al revés. Es una decisión consciente: la integridad de la planilla vale más que la notificación.

Un par de cosas más que protegen la corrida:

- El cron usa `flock`. Si una corrida se demora, la siguiente no arranca encima. Y le puse un timeout al envío de correo, porque sin eso un servidor SMTP colgado podía dejar el proceso trabado, y con `flock` eso frenaría también a todas las que siguen.
- Cada corrida escribe una línea en `python/logs/sync.log` con la hora y lo que pasó. Si algo sale mal, queda registrado dónde.

En n8n la idea es la misma. El nodo HTTP tiene los reintentos configurados y está puesto para cortar el flujo si falla, así no llega a escribir con datos incompletos. Y hubo dos detalles propios de n8n que tuve que resolver para que se portara igual que el script: forcé al nodo de lectura a emitir datos siempre, para que la primera corrida con la planilla vacía no cortara el flujo antes de tiempo; y junté los productos nuevos en un solo paso antes del correo, para que salga un mail resumen por corrida y no uno por cada producto.
