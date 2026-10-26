# Jam de doblaje

## Nuevo: Studio con backend real local

Ya se puede **cargar un archivo de video, intentar quitar sus voces con IA, comparar y descargar el MP4 procesado** en `/#/studio`. Incluye cuenta real del equipo, sesión y almacenamiento privado fuera del repositorio. Instalación y uso: **[backend/README.md](backend/README.md)**.

Esta primera etapa real es independiente del catálogo y las suscripciones demo documentados abajo. Studio no graba el nuevo doblaje ni publica para suscriptores todavía; los pagos y el acceso comercial siguen simulados. La calidad de separación debe evaluarse con escenas reales.

El catálogo demo de **doblajes terminados publicados por el equipo** permite probar suscripciones con Vue 3, TypeScript y Vite. **Modo demostración: sin cobros reales.** En ese catálogo, el pago, el rol de equipo y los permisos siguen siendo simulados; las cuentas reales del backend se usan por ahora solo en Studio.

## Ejecutar

Requiere Node.js 22 y npm:

```sh
npm ci
npm run dev
```

Abrí la dirección informada por Vite (normalmente `http://localhost:5173`). Para validar y compilar:

```sh
npm run typecheck
npm test
npm run build
npm run preview
```

`preview` sirve `dist`, normalmente en `http://localhost:4173`. Los servidores escuchan en la red local, sujeto al firewall. Se recomienda localhost o HTTPS para las APIs del navegador.

## Supabase y Vercel

La aplicación puede usar Supabase como catálogo, autenticación y fuente de suscripciones. Sin las variables de entorno continúa funcionando como demo local para desarrollo.

1. Creá un proyecto en Supabase y ejecutá `supabase/schema.sql` en el SQL Editor.
2. Registrá una cuenta desde `Cuenta y planes` y promovela manualmente a administradora con el `UPDATE` indicado al final del esquema.
3. Copiá `.env.example` como `.env.local` y completá `VITE_SUPABASE_URL` y `VITE_SUPABASE_ANON_KEY`.
4. En Vercel agregá las mismas variables para los entornos Preview y Production.
5. Publicá con `npm run build`.

Google Drive es el proveedor activo: cada video se registra con su identificador y se reproduce mediante la vista previa oficial de Drive. Los archivos deben tener permisos de visualización en Drive. HTML5 directo, almacenamiento propio y Studio con IA se muestran como funciones en desarrollo. Drive no ofrece URLs temporales ligadas a la suscripción; para protección completa del contenido, la siguiente etapa debe migrar los videos a Cloudflare Stream o un servicio equivalente.

## Planes y popularidad

Se implementó la propuesta de **cuotas mensuales fijas y planes acumulativos**, sin cargos por reproducción. Los precios y la moneda comercial **están a definir**: no se muestran importes inventados ni se solicita información de pago.

| Popularidad asignada por el equipo | Plan mínimo | Quién puede verlo |
| --- | --- | --- |
| Baja | Básico | Básico, Estándar y Premium activos |
| Media | Estándar | Estándar y Premium activos |
| Alta | Premium | Solo Premium activo |

La popularidad es una decisión editorial, no una métrica calculada ni un cambio automático de precio. El equipo puede editarla. El plan mínimo se deriva de ese valor para evitar combinaciones contradictorias.

- **No hay reproducción gratuita:** sin suscripción, con suscripción vencida o con nivel insuficiente no se monta el iframe ni el reproductor HTML5.
- Las fichas y miniaturas pueden verse para conocer el catálogo; no incluyen avances gratuitos.
- Se puede volver a reproducir un video las veces que se quiera mientras la suscripción lo incluya.
- Favoritos y lista no conceden acceso. Cada selección comprueba el plan y la fecha de vencimiento.
- “Solo disponibles en mi suscripción activa” filtra el catálogo por los permisos actuales.
- La suscripción dura un mes calendario desde la activación simulada. Si el día no existe el mes siguiente, vence el último día disponible a la misma hora local.
- Al cambiar o renovar un plan en la demo se reemplaza el anterior por un mes nuevo desde ese momento, con confirmación. No hay prorrateo, facturación ni renovación automática.
- Se persiste la fecha absoluta de vencimiento; se recalcula cada segundo, al recargar, recuperar foco o volver a la pestaña. Al vencer, bajar de plan o cambiar la popularidad del video, se vuelve a evaluar el acceso y se desmonta el reproductor si corresponde.
- “Simular vencimiento” y “Reiniciar demo” permiten probar los bloqueos. Reiniciar solo quita la suscripción, no el catálogo, los favoritos ni la lista.

El anterior pase de minutos fue reemplazado por estos tres planes mensuales. Una activación antigua no se convierte en una suscripción: hay que elegir un nuevo plan demo.

## Cargar un doblaje como equipo

1. Prepará el video con el doblaje terminado. Podés usar Studio para obtener una base con las voces reducidas; la grabación y mezcla del nuevo doblaje se realizan externamente por ahora.
2. Subilo manualmente a Google Drive y esperá que termine de procesarse. Usá material que tengas permiso de distribuir.
3. En **Compartir**, configurá los permisos según los destinatarios. Los archivos restringidos requieren cuentas autorizadas; el acceso por enlace permite ver a quien posea ese enlace. Probalo con la cuenta destinataria, o en ventana privada si elegiste acceso por enlace.
4. En el pie de la aplicación pulsá **Simular vista del equipo** y entrá en **Carga del equipo**.
5. Completá título del doblaje, película, género y **popularidad**. Elegí Google Drive y pegá el enlace del archivo o su identificador. La miniatura HTTPS es opcional.
6. Pulsá **Agregar doblaje**. Desde la lista podés editar, eliminar y abrir su página para compartir.
7. Volvé a **vista suscriptor**, elegí una suscripción simulada y probá el video.

El modo equipo se reinicia al recargar; no modifica los permisos de reproducción. Es una separación visual para probar roles, **no autenticación ni una administración segura**. En producción solo cuentas autorizadas del equipo deberán poder publicar.

Drive se incrusta con `https://drive.google.com/file/d/ID/preview`. No se transforma en una URL directa de streaming. “Abrir en Google Drive” está disponible como alternativa dentro del reproductor autorizado. Los permisos de Drive siguen aplicándose: incrustar no evita autenticación, cookies, procesamiento, cuotas o restricciones organizacionales. No se detecta ni controla el primer play dentro del iframe.

Como alternativa, **HTML5** admite una URL HTTPS de un archivo de video compatible, no una página web. La validación comprueba el formato del enlace, no la existencia del archivo ni los códecs. Esa compatibilidad debe probarse al reproducir.

## Compartir

Cada doblaje tiene una ruta hash `#/doblaje/ID` con un enlace copiable. Compartir no transfiere la suscripción: se vuelve a comprobar el plan del destinatario. Un ID inexistente muestra “Doblaje no disponible”. La página puede recargarse manteniendo la selección.

**Límites de la demo local:** un enlace a `localhost` solo apunta a la computadora de quien lo abre. Para otro dispositivo hace falta una dirección accesible y el mismo catálogo. El enlace solo contiene el ID, no transporta videos ni el catálogo. Para compartir un catálogo actualizado, exportalo, reemplazá el JSON inicial y volvé a desplegar; o importá el JSON en el navegador de prueba destinatario.

## Catálogo y datos locales

`src/data/catalog.json` es el catálogo inicial, vacío. Las tarjetas ficticias de ejemplo no tienen videos ni enlaces reales. El formato es:

```json
{
  "version": 1,
  "videos": []
}
```

Cada `Video` tiene `id`, `titulo`, `pelicula`, `genero`, `popularidad` (`baja`, `media`, `alta`), `proveedor` (`google-drive`, `html5`), `fuente` (URL HTTPS o identificador externo) y `miniatura` HTTPS opcional. `src/domain.ts` contiene la validación, las reglas de suscripción y los adaptadores de proveedores.

Importar admite hasta 5 MB y 5000 registros, valida todos los datos y rechaza IDs duplicados, popularidades inválidas y protocolos no esperados. Pide confirmación antes de reemplazar el catálogo; un archivo inválido no modifica los datos existentes. Exportar genera el JSON descargable. Eliminar limpia las referencias de favoritos y lista.

**Compatibilidad:** los catálogos antiguos sin `popularidad` se asignan a **alta/Premium** hasta revisión del equipo. El campo heredado `artista` se acepta como `pelicula`; las exportaciones usan `pelicula`. Se conservan las claves locales originales y un alias de la antigua ruta personal para no perder datos. No se borran los videos ya cargados.

Los cambios se guardan solo en `localStorage` de ese navegador y origen. No hay sincronización entre usuarios. Para compartir:

1. Exportá `catalog.json` y revisá sus datos.
2. Reemplazá `src/data/catalog.json` por el archivo exportado.
3. Volvé a compilar y desplegar cuando corresponda.

Un navegador con catálogo local conserva su versión: debe importar la nueva. Un navegador sin catálogo local usa el archivo del proyecto. Para vaciarlo importá `{ "version": 1, "videos": [] }`. Exportá como respaldo si el almacenamiento del navegador falla.

Nunca incluyas videos, base64, credenciales o enlaces con tokens secretos dentro del repositorio. `.gitignore` excluye dependencias, compilados, multimedia, secretos y temporales.

## Lo que falta para cobrar y proteger contenido

**El reloj y el almacenamiento locales son manipulables.** La demo solo simula el bloqueo de la interfaz. Las fuentes del catálogo son visibles y los enlaces de Drive o HTML5 pueden abrirse por fuera; no están protegidos por la suscripción. Un cambio de vista no es autorización real.

Antes de ofrecer suscripciones de pago hacen falta:

- Backend con cuentas, roles del equipo y validación del plan y vencimiento en cada solicitud.
- Procesador de pagos con notificaciones verificadas y reglas de renovación, cancelación y cambio de plan.
- Almacenamiento/distribución de video con acceso controlado y URLs de corta duración, reemplazando Drive mediante los adaptadores.
- Catálogo, favoritos y listas centralizados; controles de publicación y respaldos.
- Pruebas de televisores, mandos y casting real; futura aplicación móvil con autenticación y reproducción adecuada.

## Pantallas grandes

Interfaz adaptable, foco de teclado, botones grandes y modo de pantalla grande. La pantalla completa depende del navegador. No hay botones ficticios de Chromecast/AirPlay ni sincronización prometida con Drive. Pendientes: Smart TV, mandos, autenticación/cookies del iframe, códecs HTML5, pantalla completa en iOS/Safari y Android y legibilidad a distancia.

## GitHub Pages — publicación posterior

No se ha creado un repositorio ni publicado nada. `.github/workflows/pages.yml` está preparado para ejecución manual (`workflow_dispatch`).

Cuando se decida publicar:

1. Creá el repositorio y subí el código y `package-lock.json`, sin videos, dependencias ni secretos.
2. En **Settings → Pages → Build and deployment**, seleccioná **GitHub Actions**.
3. Ejecutá **Publicar demo en Pages (manual)** desde **Actions**. Comprueba tipos, pruebas de lógica, compila y publica `dist`.
4. Abrí la dirección del despliegue y verificá recursos, rutas y enlaces compartidos.

Se usa hash routing, compatible con Pages sin redirecciones. Vite usa `BASE_PATH`, por defecto `/`. El workflow calcula `/<repositorio>/` y usa `/` si el repositorio es `usuario.github.io`. Para dominio propio en la raíz, ajustá el workflow a `BASE_PATH=/`.

Prueba local con subruta en PowerShell:

```powershell
$env:BASE_PATH = '/doblaje-demo/'
npm run build
npm run preview
# http://localhost:4173/doblaje-demo/
Remove-Item Env:BASE_PATH
```

**Un repositorio privado no garantiza que Pages sea privado.** Para privacidad, continuar localmente o usar alojamiento con control de acceso. Pages puede servir la interfaz, pero no el backend de suscripciones ni protección real de videos.

## Pruebas

```sh
npm run typecheck
npm test
npm run build
npx playwright install chromium --no-shell
npm run test:e2e
```

Playwright inicia y detiene un servidor independiente. Drive se intercepta con una respuesta ficticia y HTML5 usa URLs sintéticas bloqueadas: se prueba montaje/desmontaje y permisos de interfaz, no reproducción externa. Resultados y pendientes en `VERIFICACION.md`.
