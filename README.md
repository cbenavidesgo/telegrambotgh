# 🏠 Bot de Gastos — Cris & Mari

Bot de Telegram que registra **gastos, ingresos y transferencias** directo en Notion,
a partir de mensajes escritos en lenguaje natural. Sin formularios, sin abrir Notion:
solo le escriben al bot como si le escribieran a una persona.

> "Gasté 45.000 en mercado, Nequi de Cris" → queda registrado en Notion en segundos.

---

## 📐 Cómo funciona

```
Cris o Mari (Telegram)
        │
        ▼
   bot.py (Railway, corriendo 24/7)
        │
        ├──► Groq API (gratis) — interpreta el mensaje y lo convierte en JSON:
        │     tipo, título, monto, cuenta, categoría, fecha
        │
        └──► Notion API — crea la fila en la base correcta
              (Gastos / Ingresos / Transferencias)
```

El bot detecta automáticamente si el mensaje es un **gasto**, un **ingreso** o una
**transferencia** entre cuentas propias, y resuelve fechas relativas ("ayer", "el
lunes pasado", "hace 3 días") sin que el usuario tenga que escribir la fecha exacta.

---

## 🗂️ Estructura de Notion

El bot trabaja sobre 5 bases de datos del workspace **"Hogar - Cris & Mari"**:

| Base | Para qué |
|---|---|
| **Gastos** | Cada gasto registrado |
| **Ingresos** | Cada ingreso registrado |
| **Transferencias** | Movimientos entre cuentas propias |
| **Cuentas** | Catálogo de cuentas (Nequi Cris, Nu Mari, RappiCuenta Cris, RappiCard Cris, RappiCard Mari, Cash, GZero) |
| **Categorías de Gastos / Categorías de Ingreso** | Catálogo de categorías |

⚠️ **Importante:** la integración de Notion necesita acceso a las **5 bases**, no solo
a Gastos/Ingresos/Transferencias. Como estas últimas guardan relaciones (`Account`,
`Category`, `Cuenta`, `Desde`, `Hacia`) que apuntan a páginas de Cuentas y Categorías,
Notion rechaza la escritura con un error `404` si esas bases auxiliares no están
también conectadas a la integración.

---

## ⚙️ Configuración inicial

### 1. Bot de Telegram
1. Habla con **@BotFather** en Telegram.
2. `/newbot` → nombre → username.
3. Guarda el **token** que te da (`TELEGRAM_BOT_TOKEN`).

### 2. Integración de Notion
1. Crea una integración en https://www.notion.so/profile/integrations.
2. Copia su **token de acceso** (`NOTION_API_KEY`).
3. Conéctala a las **5 bases** mencionadas arriba: abre cada una → "···" → Conexiones
   → busca el nombre de tu integración → agrégala.
   - Truco: si tienes bases duplicadas con el mismo nombre, conéctalas **desde dentro
     de cada página específica** (no desde el buscador genérico de la integración),
     así no hay riesgo de conectar la base equivocada.

### 3. API key de Groq (gratis, sin tarjeta)
1. Ve a https://console.groq.com/keys → "Create API Key".
2. Copia la clave (`GROQ_API_KEY`, empieza con `gsk_...`).

### 4. IDs de Telegram de los usuarios autorizados
Cada uno le escribe a **@userinfobot** en Telegram y les da su ID numérico.

---

## 🔑 Variables de entorno

| Variable | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot (@BotFather) |
| `GROQ_API_KEY` | API key gratis de Groq |
| `NOTION_API_KEY` | Token de la integración de Notion |
| `GASTOS_DATA_SOURCE_ID` | ID del data source "Gastos" |
| `INGRESOS_DATA_SOURCE_ID` | ID del data source "Ingresos" |
| `TRANSFERENCIAS_DATA_SOURCE_ID` | ID del data source "Transferencias" |
| `ALLOWED_TELEGRAM_USER_IDS` | IDs de Telegram autorizados, separados por coma |

Ver `.env.example` para el formato exacto. **Nunca subas tu `.env` real a GitHub** —
solo va como variables de entorno en Railway.

---

## 🚀 Desplegar en Railway (gratis)

1. Crea cuenta en https://railway.app (con GitHub, así quedan conectadas).
2. **New Project** → **Deploy from GitHub repo** → selecciona este repositorio.
3. Pestaña **Variables** → **Raw Editor** → pega el contenido completo de tu `.env`.
4. En **Settings → Source**, confirma que:
   - El repo y la rama (`main`) son correctos.
   - **"Auto Deploy"** está activado (⚠️ ver sección de problemas comunes abajo).
5. Verifica en **Settings** que el comando de arranque sea `python bot.py`.

El bot corre por **polling** (no webhook), así que no necesita dominio ni puerto
HTTP expuesto — funciona tal cual en el plan gratuito.

---

## 💬 Ejemplos de uso

```
Gasté 45.000 en mercado, Nequi de Cris
Pagué el recibo de la luz, 8.390 desde RappiCuenta Cris
Me pagaron 800.000 de freelance, a mi Nu de Mari
Pasé 100.000 de mi Nequi a mi Nu
Gasté 20.000 en transporte el lunes pasado, RappiCard Cris
```

Si el bot no tiene información suficiente (por ejemplo no sabe de qué cuenta hablas),
te va a preguntar antes de guardar nada.

---

## 🛠️ Problemas comunes (y cómo se resolvieron)

Estos son errores reales que salieron durante la construcción de este bot — quedan
documentados para el futuro:

### `404` al crear la página en Notion
**Causa más común:** la integración no tiene acceso a la base específica (revisa que
sea la base correcta si hay duplicados con el mismo nombre), **o** le falta acceso a
la base de **Cuentas** / **Categorías** (las bases "auxiliares" de las relaciones).
**Cómo diagnosticarlo:** el bot loggea el mensaje de error completo de Notion
(`Notion respondió 404: ...`) — casi siempre dice exactamente qué página no encuentra.

### `404` al llamar a Groq
Los proveedores de IA gratis van retirando modelos con el tiempo. Si ves un 404
apuntando a `api.groq.com`, entra a https://console.groq.com/docs/models y revisa
cuál es el modelo vigente — hay que actualizar el nombre del modelo en `bot.py`
(variable dentro de `parse_message_with_groq`).

### El bot sigue fallando aunque ya subiste el código nuevo a GitHub
Revisa en Railway → **Deployments** si aparece un aviso de **"Update available"** —
a veces el auto-deploy no se dispara solo con cada commit y hay que forzarlo
manualmente dándole clic a ese aviso (o "Redeploy").

### `Conflict: terminated by other getUpdates request`
Significa que hay dos instancias del bot corriendo al mismo tiempo con el mismo
token. Revisa que no haya más de un proyecto o servicio desplegado en Railway usando
las mismas variables.

### Cambiaste de proveedor de IA (Anthropic → Gemini → Groq)
El proyecto empezó con la API de Anthropic (de pago), se probó con Gemini (los
API keys nuevos de Google con prefijo `AQ.` tuvieron un bug conocido de compatibilidad
en 2026), y terminó en **Groq**, que ofrece un plan gratis con claves estables
(`gsk_...`) sin ese problema.

---

## 🔔 Notificación de estado

El bot manda un mensaje "🟢 Bot reiniciado y en línea" a los usuarios autorizados
cada vez que arranca — útil para notar si Railway lo reinició por una caída.
Complementario: activa las notificaciones de "Deployment failed" en la configuración
de tu cuenta de Railway para recibir un correo si el servicio se cae.

---

## 🔐 Seguridad

- Las credenciales (`NOTION_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`) viven
  **solo** en las variables de entorno de Railway — nunca en el repositorio.
- Solo los IDs de Telegram listados en `ALLOWED_TELEGRAM_USER_IDS` pueden usar el bot.
- Si alguna credencial se expone por accidente, rótala de inmediato:
  - Notion: integración → "Actualizar el token de acceso".
  - Telegram: @BotFather → `/revoke`.
  - Groq: console.groq.com/keys → eliminar y crear una nueva.
