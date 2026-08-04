"""
Bot de Telegram para registrar gastos, ingresos y transferencias en Notion.
Cris y Mari le escriben en lenguaje natural, Claude interpreta el mensaje
(incluyendo qué tipo de movimiento es), y el bot crea la fila correspondiente
en la base de Notion que aplique.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# CONFIGURACIÓN (se toma de variables de entorno, ver .env.example)
# ----------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]  # gratis en aistudio.google.com/apikey
NOTION_API_KEY = os.environ["NOTION_API_KEY"]

GASTOS_DATA_SOURCE_ID = os.environ["GASTOS_DATA_SOURCE_ID"]
INGRESOS_DATA_SOURCE_ID = os.environ["INGRESOS_DATA_SOURCE_ID"]
TRANSFERENCIAS_DATA_SOURCE_ID = os.environ["TRANSFERENCIAS_DATA_SOURCE_ID"]

# IDs de Telegram autorizados a usar el bot (tú y Mari). Vacío = cualquiera puede usarlo.
ALLOWED_USER_IDS = {
    int(uid) for uid in os.environ.get("ALLOWED_TELEGRAM_USER_IDS", "").split(",") if uid.strip()
}

BOGOTA_TZ = timezone(timedelta(hours=-5))

# Cuentas reales (usadas por los tres tipos de movimiento).
CUENTAS = {
    "Mari Bancolombia": "2e96cb1b-5b1d-8054-a4bf-ddfa1b74f32c",
    "Mari Nu": "2e96cb1b-5b1d-8099-bab4-ce52b3649611",
    "Cris Bancolombia": "2e96cb1b-5b1d-805c-912e-db9d80a83302",
    "Rappi Cris": "2e96cb1b-5b1d-8012-a1e4-cdc05f03d2c0",
    "Rappi Mari": "3426cb1b-5b1d-800f-bcb3-daf71679ff5d",
}

# Categorías (solo para gastos).
CATEGORIAS = {
    "Diezmo": "3b16cb1b-5b1d-80e3-8740-eeb8c1cc12dd",
    "Seguridad Social": "2e96cb1b-5b1d-8051-a716-e77abd786b47",
    "Suscripciones": "2e96cb1b-5b1d-8058-9f52-c7b5e3a975b9",
    "Salarios": "2e96cb1b-5b1d-80f5-9976-e0c2b8b8b962",
    "Impuestos": "2e96cb1b-5b1d-8075-8d57-c218e9afd374",
    "Gastos": "2fe6cb1b-5b1d-80f3-bb3b-e54c306bbd26",
    "Crédito Bombotá": "2fe6cb1b-5b1d-8069-bd7b-cfec500fca21",
}

# Fuentes válidas (solo para ingresos). Ninguna es obligatoria: si no aplica, se deja null.
FUENTES = ["Branding", "Artista Mensual", "Música", "Redes Sociales", "Asesorías", "Ayudas"]

# Estado en memoria: si Claude necesita una aclaración, guardamos el mensaje original
# por chat_id hasta que la persona responda.
pending_entries: dict[int, str] = {}


# ----------------------------------------------------------------------------
# PASO 1: interpretar el mensaje con Gemini (gratis)
# ----------------------------------------------------------------------------
def parse_message_with_gemini(message_text: str, sender_name: str, today: str) -> dict:
    system_prompt = f"""Eres un asistente que convierte mensajes en español sobre finanzas domésticas
en datos estructurados para tres bases de datos de Notion: Gastos, Ingresos y Transferencias.

Primero decide el "tipo" de movimiento:
- "gasto": compras, pagos, salidas de dinero.
- "ingreso": dinero que entra (pago, venta, regalía, ayuda, etc.)
- "transferencia": mover dinero de una cuenta propia a otra (ej. "pasé 100 mil de mi Bancolombia a mi Nu").

Cuentas válidas (usa el nombre EXACTO): {", ".join(CUENTAS.keys())}

Quien escribe el mensaje se llama: {sender_name}. Si el mensaje no aclara de quién es la
cuenta (ej. "pagué con Bancolombia" sin decir de quién), asume que es la cuenta de {sender_name}.
Si menciona Rappi sin aclarar de quién, usa "Rappi {sender_name}".

La fecha de hoy es {today}. Si el mensaje no menciona fecha, usa hoy. Si dice "ayer", "anteayer"
o un día específico, calcula la fecha correspondiente en formato YYYY-MM-DD.

--- Si tipo es "gasto" ---
Categorías válidas (usa el nombre EXACTO): {", ".join(CATEGORIAS.keys())}
Categoriza según contexto (mercado/comida/hogar -> "Gastos", Netflix/Spotify/streaming ->
"Suscripciones", salud/EPS -> "Seguridad Social", impuestos/predial -> "Impuestos",
diezmo/iglesia -> "Diezmo", pago de tarjeta de crédito -> "Crédito Bombotá").
Campos a llenar: titulo, cantidad, cuenta, categoria, fecha.

--- Si tipo es "ingreso" ---
Fuentes válidas (opcional, usa el nombre EXACTO si aplica claramente, si no null):
{", ".join(FUENTES)}
Campos a llenar: titulo, cantidad, cuenta, fuente (puede ser null), fecha.

--- Si tipo es "transferencia" ---
Campos a llenar: titulo, cantidad, cuenta_origen, cuenta_destino, fecha.

Responde ÚNICAMENTE con un JSON válido, sin texto adicional, sin backticks, con esta forma exacta
(usa null en los campos que no apliquen al tipo):
{{
  "needs_clarification": false,
  "clarification_question": null,
  "tipo": "gasto",
  "titulo": "descripción corta, 3-6 palabras",
  "cantidad": 45000,
  "cuenta": "nombre exacto de la lista de cuentas",
  "categoria": "nombre exacto de la lista de categorías",
  "fuente": null,
  "cuenta_origen": null,
  "cuenta_destino": null,
  "fecha": "YYYY-MM-DD"
}}

Si falta información crítica que no puedas inferir razonablemente (ej. no hay forma de saber
el monto, o de qué cuenta se trata), responde con "needs_clarification": true y una pregunta
corta y específica en "clarification_question", dejando el resto de campos en null.
"""

    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        params={"key": GOOGLE_API_KEY},
        headers={"content-type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": message_text}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


# ----------------------------------------------------------------------------
# PASO 2: crear la fila en la base de Notion correspondiente
# ----------------------------------------------------------------------------
def notion_create_page(data_source_id: str, properties: dict) -> str:
    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        json={"parent": {"data_source_id": data_source_id}, "properties": properties},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["url"]


def create_gasto(parsed: dict) -> str:
    properties = {
        "Gasto": {"title": [{"text": {"content": parsed["titulo"]}}]},
        "Cantidad": {"number": parsed["cantidad"]},
        "Fecha": {"date": {"start": parsed["fecha"]}},
        "Cuenta": {"relation": [{"id": CUENTAS[parsed["cuenta"]]}]},
        "Categoría": {"relation": [{"id": CATEGORIAS[parsed["categoria"]]}]},
    }
    return notion_create_page(GASTOS_DATA_SOURCE_ID, properties)


def create_ingreso(parsed: dict) -> str:
    properties = {
        "Ingreso": {"title": [{"text": {"content": parsed["titulo"]}}]},
        "Cantidad": {"number": parsed["cantidad"]},
        "Fecha": {"date": {"start": parsed["fecha"]}},
        "Cuentas": {"relation": [{"id": CUENTAS[parsed["cuenta"]]}]},
    }
    if parsed.get("fuente"):
        properties["Fuente"] = {"select": {"name": parsed["fuente"]}}
    return notion_create_page(INGRESOS_DATA_SOURCE_ID, properties)


def create_transferencia(parsed: dict) -> str:
    properties = {
        "Transacciones": {"title": [{"text": {"content": parsed["titulo"]}}]},
        "Cantidad": {"number": parsed["cantidad"]},
        "Fecha": {"date": {"start": parsed["fecha"]}},
        "De qué Cuenta": {"relation": [{"id": CUENTAS[parsed["cuenta_origen"]]}]},
        "Hacia cuál Cuenta": {"relation": [{"id": CUENTAS[parsed["cuenta_destino"]]}]},
    }
    return notion_create_page(TRANSFERENCIAS_DATA_SOURCE_ID, properties)


# ----------------------------------------------------------------------------
# HANDLERS DE TELEGRAM
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "¡Hola! Solo escríbeme tus movimientos en lenguaje natural, por ejemplo:\n\n"
        '"Gasté 45.000 en mercado, tarjeta de Cris"\n'
        '"Me pagaron 800.000 de branding, a mi Bancolombia"\n'
        '"Pasé 100.000 de mi Bancolombia a mi Nu"\n\n'
        "Yo detecto si es gasto, ingreso o transferencia, y lo registro directo en Notion. 🙂"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id

    if ALLOWED_USER_IDS and user.id not in ALLOWED_USER_IDS:
        await update.message.reply_text("No estás autorizado a usar este bot.")
        return

    message_text = update.message.text
    sender_name = user.first_name or "desconocido"
    today = datetime.now(BOGOTA_TZ).strftime("%Y-%m-%d")

    if chat_id in pending_entries:
        original = pending_entries.pop(chat_id)
        message_text = f"{original}\n(Aclaración: {message_text})"

    await update.message.chat.send_action("typing")

    try:
        parsed = parse_message_with_gemini(message_text, sender_name, today)
    except Exception:
        logger.exception("Error interpretando el mensaje")
        await update.message.reply_text("No pude interpretar ese mensaje, ¿puedes intentar de nuevo?")
        return

    if parsed.get("needs_clarification"):
        pending_entries[chat_id] = message_text
        await update.message.reply_text(parsed["clarification_question"])
        return

    tipo = parsed.get("tipo")
    try:
        if tipo == "gasto":
            url = create_gasto(parsed)
            detalle = f"💳 {parsed['cuenta']} | 🏷️ {parsed['categoria']}"
            emoji = "💸"
        elif tipo == "ingreso":
            url = create_ingreso(parsed)
            fuente = f" | 🏷️ {parsed['fuente']}" if parsed.get("fuente") else ""
            detalle = f"💳 {parsed['cuenta']}{fuente}"
            emoji = "💰"
        elif tipo == "transferencia":
            url = create_transferencia(parsed)
            detalle = f"↗️ {parsed['cuenta_origen']} → {parsed['cuenta_destino']}"
            emoji = "🔁"
        else:
            await update.message.reply_text("No entendí si era un gasto, ingreso o transferencia. ¿Puedes reformular?")
            return
    except KeyError as e:
        logger.exception("Cuenta o categoría no reconocida")
        await update.message.reply_text(f"No reconocí un valor en tu mensaje ({e}). ¿Puedes ser más específico?")
        return
    except Exception:
        logger.exception("Error creando la página en Notion")
        await update.message.reply_text("Entendí el movimiento pero no pude guardarlo en Notion. Intenta de nuevo.")
        return

    monto_fmt = f"${parsed['cantidad']:,.0f}".replace(",", ".")
    await update.message.reply_text(
        f"{emoji} Registrado ({tipo}): {parsed['titulo']} — {monto_fmt}\n"
        f"📅 {parsed['fecha']} | {detalle}\n"
        f"{url}"
    )


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot iniciado, escuchando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()
