"""
Bot de Telegram para registrar gastos, ingresos y transferencias en Notion.
Cris y Mari le escriben en lenguaje natural, Groq (Llama) interpreta el mensaje
(incluyendo qué tipo de movimiento es), y el bot crea la fila correspondiente
en la base de Notion que aplique — dentro del workspace "Hogar - Cris & Mari".
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
GROQ_API_KEY = os.environ["GROQ_API_KEY"]  # gratis en console.groq.com/keys
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
    "Nequi Cris": "3366cb1b-5b1d-80db-977c-d8abfe5b8422",
    "Nu Mari": "3366cb1b-5b1d-806a-aad8-c55a93da30f5",
    "RappiCuenta Cris": "3366cb1b-5b1d-80b5-8bb4-ecb9df3762ce",
    "RappiCard Cris": "3366cb1b-5b1d-80bc-8977-cc7942e9a44b",
    "Cash": "3366cb1b-5b1d-80d1-9b4c-ff40ed8b4cd5",
    "GZero": "3366cb1b-5b1d-8017-b72d-fa41548e30cc",
    "RappiCard Mari": "3366cb1b-5b1d-804e-8ae7-f3cbd67fd898",
}

# Categorías válidas para gastos.
CATEGORIAS_GASTOS = {
    "Mesada Cris": "37b6cb1b-5b1d-80d9-b437-dcbad1d49071",
    "Salud": "37b6cb1b-5b1d-8004-a2eb-f48868ed50ef",
    "Mesada Mari": "3b16cb1b-5b1d-80f3-b05b-c54104e4dccf",
    "Entretenimiento": "2d56cb1b-5b1d-8156-b032-dbedd0429c54",
    "Trabajo": "2d56cb1b-5b1d-8144-bf97-fbb361459dc8",
    "Compras de Casa": "2d56cb1b-5b1d-8131-b599-f209de1a7a8a",
    "Comer por Fuera": "2d56cb1b-5b1d-81e6-9361-da42d8a71de6",
    "Belleza": "35a6cb1b-5b1d-802a-a86e-cac4dcf431ee",
    "Arriendo / Admin de la casa": "2d56cb1b-5b1d-81f9-9476-ec82972f0213",
    "Viajes y Vacaciones": "2d56cb1b-5b1d-8124-a721-fe6b0c99ee0a",
    "Inversiones": "2d56cb1b-5b1d-81f9-a1e5-eeed7a2c10a0",
    "Transporte": "2d56cb1b-5b1d-8175-aaf5-dc47831ba5df",
    "Facturas y Utilidades": "2d56cb1b-5b1d-81bc-8185-cd23e263a0e2",
    "Educación": "2d56cb1b-5b1d-818a-a718-f180ee17ce78",
    "Comida y Mercado": "2d56cb1b-5b1d-81bd-8ea9-e3335298c8b8",
}

# Categorías válidas para ingresos (llamadas "Fuente" en el prompt para no confundir con las de gastos).
CATEGORIAS_INGRESOS = {
    "Ventas": "2d56cb1b-5b1d-8153-9099-f0d59a50a199",
    "Freelance": "2d56cb1b-5b1d-81ae-9bf1-e5dc8a1e6324",
    "Vacas": "35a6cb1b-5b1d-807e-b2ea-eb689a3d48c2",
    "Ingreso de Negocio": "2d56cb1b-5b1d-8161-afaa-e6ad6981c3f7",
    "Regalos / Donaciones": "2d56cb1b-5b1d-8172-bb45-caa4dc474704",
    "Salario": "2d56cb1b-5b1d-81bb-a204-e4657d4b747e",
    "Ingreso de Inversiones": "2d56cb1b-5b1d-81d4-92b6-db285c5cdea6",
    "Ingreso de Rentas": "2d56cb1b-5b1d-8100-b59c-dd874ccba73d",
    "Otros Trabajos": "2d56cb1b-5b1d-816e-adb5-d7c30db74d7a",
}

# Estado en memoria: si el modelo necesita una aclaración, guardamos el mensaje original
# por chat_id hasta que la persona responda.
pending_entries: dict[int, str] = {}


# ----------------------------------------------------------------------------
# PASO 1: interpretar el mensaje con Groq (gratis, modelo Llama)
# ----------------------------------------------------------------------------
def parse_message_with_groq(message_text: str, sender_name: str, today: str) -> dict:
    dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    hoy_dt = datetime.strptime(today, "%Y-%m-%d")
    hoy_nombre_dia = dias_semana[hoy_dt.weekday()]

    system_prompt = f"""Eres un asistente que convierte mensajes en español sobre finanzas domésticas
en datos estructurados para tres bases de datos de Notion: Gastos, Ingresos y Transferencias.

Primero decide el "tipo" de movimiento:
- "gasto": compras, pagos, salidas de dinero.
- "ingreso": dinero que entra (pago, venta, regalía, ayuda, etc.)
- "transferencia": mover dinero de una cuenta propia a otra (ej. "pasé 100 mil de mi Nequi a mi Nu").

Cuentas válidas (usa el nombre EXACTO): {", ".join(CUENTAS.keys())}

Quien escribe el mensaje se llama: {sender_name}. Los nombres de cuenta ya incluyen "Cris" o "Mari"
según de quién son (ej. "Nequi Cris", "Nu Mari"). Si el mensaje no aclara la cuenta pero sí el método
de pago (ej. "pagué con Rappi" sin decir la tarjeta), asume la cuenta de tipo Rappi de {sender_name}
("RappiCard {sender_name}" o "RappiCuenta {sender_name}", prioriza "RappiCard" si no hay más contexto).
Si no hay ninguna pista de cuenta, usa "Cash" solo si el mensaje sugiere efectivo, si no pide aclaración.

La fecha de hoy es {today} ({hoy_nombre_dia}). Si el mensaje no menciona fecha, usa hoy.
Resuelve expresiones relativas de fecha con cuidado:
- "ayer" / "anteayer" -> resta 1 o 2 días a hoy.
- "hace N días" -> resta N días a hoy.
- "el lunes pasado", "el sábado", etc. (sin decir "próximo") -> el día de esa semana ANTERIOR
  más cercano hacia atrás desde hoy (nunca una fecha futura). Ej: si hoy es {hoy_nombre_dia}
  {today} y dicen "el lunes pasado", cuenta hacia atrás día por día desde hoy hasta el lunes
  más reciente.
- Una fecha explícita ("3 de agosto", "03/08") -> conviértela a YYYY-MM-DD, asumiendo el año
  actual salvo que digan otro.
Siempre da el resultado final en formato YYYY-MM-DD.

--- Si tipo es "gasto" ---
Categorías válidas (usa el nombre EXACTO): {", ".join(CATEGORIAS_GASTOS.keys())}
Categoriza según contexto (mercado/comida en casa -> "Comida y Mercado", restaurantes/domicilios ->
"Comer por Fuera", Uber/gasolina/parqueadero -> "Transporte", Netflix/servicios públicos/celular ->
"Facturas y Utilidades", arriendo/administración -> "Arriendo / Admin de la casa", gimnasio/EPS/médico
-> "Salud", cine/salidas -> "Entretenimiento", ropa/cortes de pelo -> "Belleza", muebles/aseo del hogar
-> "Compras de Casa", curso/colegio -> "Educación", vuelos/hotel -> "Viajes y Vacaciones", plata libre
de Cris -> "Mesada Cris", plata libre de Mari -> "Mesada Mari", relacionado al negocio -> "Trabajo",
aportes a inversiones -> "Inversiones").
Campos a llenar: titulo, cantidad, cuenta, categoria, fecha.

--- Si tipo es "ingreso" ---
Fuentes válidas (usa el nombre EXACTO si aplica claramente, si no null):
{", ".join(CATEGORIAS_INGRESOS.keys())}
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
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"]
    return json.loads(text)


# ----------------------------------------------------------------------------
# PASO 2: crear la fila en la base de Notion correspondiente
# ----------------------------------------------------------------------------
def notion_create_page(data_source_id: str, properties: dict) -> str:
    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json",
        },
        json={"parent": {"type": "data_source_id", "data_source_id": data_source_id}, "properties": properties},
        timeout=30,
    )
    if not response.ok:
        logger.error("Notion respondió %s: %s", response.status_code, response.text)
    response.raise_for_status()
    return response.json()["url"]


def create_gasto(parsed: dict) -> str:
    properties = {
        "Name": {"title": [{"text": {"content": parsed["titulo"]}}]},
        "Amount": {"number": parsed["cantidad"]},
        "Date": {"date": {"start": parsed["fecha"]}},
        "Account": {"relation": [{"id": CUENTAS[parsed["cuenta"]]}]},
        "Category": {"relation": [{"id": CATEGORIAS_GASTOS[parsed["categoria"]]}]},
    }
    return notion_create_page(GASTOS_DATA_SOURCE_ID, properties)


def create_ingreso(parsed: dict) -> str:
    properties = {
        "Name": {"title": [{"text": {"content": parsed["titulo"]}}]},
        "Cantidad": {"number": parsed["cantidad"]},
        "Fecha": {"date": {"start": parsed["fecha"]}},
        "Cuenta": {"relation": [{"id": CUENTAS[parsed["cuenta"]]}]},
    }
    if parsed.get("fuente"):
        properties["Categoría"] = {"relation": [{"id": CATEGORIAS_INGRESOS[parsed["fuente"]]}]}
    return notion_create_page(INGRESOS_DATA_SOURCE_ID, properties)


def create_transferencia(parsed: dict) -> str:
    properties = {
        "Name": {"title": [{"text": {"content": parsed["titulo"]}}]},
        "Cantidad": {"number": parsed["cantidad"]},
        "Fecha": {"date": {"start": parsed["fecha"]}},
        "Desde": {"relation": [{"id": CUENTAS[parsed["cuenta_origen"]]}]},
        "Hacia": {"relation": [{"id": CUENTAS[parsed["cuenta_destino"]]}]},
    }
    return notion_create_page(TRANSFERENCIAS_DATA_SOURCE_ID, properties)


# ----------------------------------------------------------------------------
# HANDLERS DE TELEGRAM
# ----------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "¡Hola! Solo escríbeme tus movimientos en lenguaje natural, por ejemplo:\n\n"
        '"Gasté 45.000 en mercado, Nequi de Cris"\n'
        '"Me pagaron 800.000 de branding, a mi Nu"\n'
        '"Pasé 100.000 de mi Nequi a mi Nu"\n\n'
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
        parsed = parse_message_with_groq(message_text, sender_name, today)
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


async def notify_startup(app: Application) -> None:
    for user_id in ALLOWED_USER_IDS:
        try:
            await app.bot.send_message(chat_id=user_id, text="🟢 Bot reiniciado y en línea.")
        except Exception:
            logger.exception("No pude notificar el arranque a %s", user_id)


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(notify_startup).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot iniciado, escuchando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()
