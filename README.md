# Bot de Gastos - Cris & Mari

Bot de Telegram que registra gastos, ingresos y transferencias en sus bases de
Notion a partir de mensajes en lenguaje natural.

**Ya tienes listos:**
- ✅ Token del bot de Telegram
- ✅ API key de Notion, ya conectada a las 3 bases
- ⬜ API key gratis de Google Gemini (falta crearla, sin tarjeta)
- ⬜ IDs de Telegram de Cris y Mari (falta conseguirlos)

## 1. Conectar tu integración de Notion a las 3 bases (2 min) — PENDIENTE

Tu API key de Notion ya la tengo puesta en `.env`, pero una integración solo puede
leer/escribir en las páginas donde la conectes explícitamente. Tienes que hacer esto
**una vez por cada una** de las 3 bases:

1. Abre en Notion la base **"Gastos"** → botón "···" (arriba a la derecha) →
   "Conexiones" (Connections) → busca tu integración y conéctala.
2. Repite lo mismo en la base **"Ingresos"**.
3. Repite lo mismo en la base **"Transferencias"**.

Si te da pereza buscarlas, dime y te paso el link directo a cada una.

## 2. Obtener tu API key GRATIS de Google (Gemini) — PENDIENTE

1. Ve a https://aistudio.google.com/apikey (entra con cualquier cuenta de Gmail).
2. Dale clic a **"Create API key"**. No pide tarjeta de crédito.
3. Copia la clave y pégala en `.env` donde dice `GOOGLE_API_KEY=`.

El plan gratis permite hasta 1.500 mensajes al día — muchísimo más de lo que ustedes van a necesitar.

## 3. Obtener los IDs de Telegram de Cris y Mari — PENDIENTE

Cada uno le escribe a **@userinfobot** en Telegram y les da su ID numérico (algo como `987654321`).
Ponlos en `.env` en `ALLOWED_TELEGRAM_USER_IDS=123123123,987654321` (sin espacios, separados por coma).
Si lo dejas vacío, cualquier persona que encuentre el bot podrá usarlo — no recomendado.

## 4. Desplegar en Railway (gratis, recomendado)

1. Crea una cuenta en https://railway.app (puedes entrar con GitHub).
2. Sube esta carpeta a un repositorio de GitHub (o usa "Deploy from local directory" si Railway te lo permite).
3. En Railway: "New Project" → "Deploy from GitHub repo" → selecciona el repo.
4. En la pestaña **Variables**, agrega el contenido completo de tu archivo `.env`
   (Railway te deja pegar un bloque tipo `.env` completo de una vez, busca el botón
   "Raw Editor" o "Import from .env").
5. Railway detectará que es un proyecto Python e instalará `requirements.txt` solo.
6. En "Settings" → "Deploy", asegúrate que el **Start Command** sea `python bot.py`.
7. Dale deploy. En los logs deberías ver "Bot iniciado, escuchando mensajes...".

Alternativa: **Render.com** funciona igual de bien, como "Background Worker" (no "Web Service",
porque este bot no expone un puerto HTTP).

## 6. Probarlo

Abre Telegram, busca tu bot por el username que le pusiste, dale "Start", y prueba los tres tipos:

> Gasté 45.000 en mercado, tarjeta de Cris
> Me pagaron 800.000 de branding, a mi Bancolombia
> Pasé 100.000 de mi Bancolombia a mi Nu

Debería responder confirmando el registro y crear la fila en la base de Notion correspondiente.

## Notas

- El bot solo entiende texto (no fotos de recibos, por ahora).
- Detecta automáticamente si el mensaje es un gasto, un ingreso o una transferencia entre cuentas.
- Si mencionas una cuenta, categoría o fuente ambigua, el bot te va a preguntar antes de guardar.
- Si agregan una cuenta, categoría o fuente nueva en Notion más adelante, hay que agregarla también
  en los diccionarios `CUENTAS`, `CATEGORIAS` o `FUENTES` dentro de `bot.py` (el ID de página se ve
  en la URL de la página en Notion).
- El bot corre por *polling* (pregunta a Telegram cada pocos segundos), así que no necesita
  un dominio ni HTTPS — funciona en el plan gratuito de Railway/Render sin configuración extra.
