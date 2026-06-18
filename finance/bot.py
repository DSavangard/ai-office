import asyncio
import os
import json
import re
import base64
import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, PhotoSize, Document
from dotenv import load_dotenv
import tbank

load_dotenv(dotenv_path="/opt/ai-office/finance/.env")

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dialogs = {}

# ═══════════════════════════════════════════
# ИНСТРУМЕНТЫ
# ═══════════════════════════════════════════

TOOLS = {
    "get_accounts": {"desc": "Получить балансы всех счетов"},
    "get_summary": {"desc": "Финансовая сводка за период", "params": {"days": "количество дней (7, 30, 90)"}},
    "get_statement": {"desc": "Детальная выписка операций", "params": {"days": "дней", "limit": "макс операций"}},
    "send_invoice": {"desc": "Выставить счёт клиенту", "params": {
        "amount": "сумма в рублях",
        "description": "назначение платежа",
        "inn": "ИНН клиента (опционально)",
        "name": "имя/название клиента (опционально)",
        "phone": "телефон клиента (опционально)",
        "email": "email клиента (опционально)",
        "comment": "комментарий (опционально)"
    }},
    "get_invoice_status": {"desc": "Статус выставленного счёта", "params": {"invoice_id": "ID счёта"}},
    "create_sbp_link": {"desc": "Создать ссылку СБП для оплаты", "params": {
        "amount": "сумма в рублях",
        "description": "назначение",
        "one_time": "одноразовая ссылка (true/false)"
    }},
    "get_sbp_link_status": {"desc": "Статус оплаты СБП ссылки", "params": {"qr_id": "ID ссылки"}},
    "get_cards": {"desc": "Список бизнес-карт компании"},
    "get_card_limits": {"desc": "Лимиты по карте", "params": {"ucid": "ID карты"}},
    "get_terminals": {"desc": "Список терминалов эквайринга"},
    "get_terminal_operations": {"desc": "Операции по терминалу", "params": {"terminal_id": "ID терминала", "days": "дней"}},
    "answer": {"desc": "Ответить пользователю", "params": {"text": "текст"}},
    "ask_user": {"desc": "Уточнить у пользователя", "params": {"question": "вопрос"}}
}

async def execute_tool(tool, params):
    print(f"TOOL: {tool} {params}")
    try:
        if tool == "get_accounts":
            return await tbank.get_accounts()
        elif tool == "get_summary":
            return await tbank.get_summary(days=int(params.get("days", 7)))
        elif tool == "get_statement":
            return await tbank.get_statement(days=int(params.get("days", 7)), limit=int(params.get("limit", 50)))
        elif tool == "send_invoice":
            return await tbank.send_invoice(
                amount=float(params["amount"]),
                description=params["description"],
                inn=params.get("inn"),
                name=params.get("name"),
                phone=params.get("phone"),
                email=params.get("email"),
                comment=params.get("comment")
            )
        elif tool == "get_invoice_status":
            return await tbank.get_invoice_status(params["invoice_id"])
        elif tool == "create_sbp_link":
            return await tbank.create_sbp_link(
                amount=float(params["amount"]),
                description=params["description"],
                one_time=params.get("one_time", True)
            )
        elif tool == "get_sbp_link_status":
            return await tbank.get_sbp_link_status(params["qr_id"])
        elif tool == "get_cards":
            return await tbank.get_cards()
        elif tool == "get_card_limits":
            return await tbank.get_card_limits(int(params["ucid"]))
        elif tool == "get_terminals":
            return await tbank.get_terminals()
        elif tool == "get_terminal_operations":
            return await tbank.get_terminal_operations(params["terminal_id"], int(params.get("days", 7)))
        elif tool in ["answer", "ask_user"]:
            return {"text": params.get("text") or params.get("question")}
        return {"error": f"Неизвестный инструмент: {tool}"}
    except Exception as e:
        return {"error": str(e)}

# ═══════════════════════════════════════════
# ИИ АГЕНТ
# ═══════════════════════════════════════════

async def run_agent(messages_history):
    tools_desc = json.dumps(TOOLS, ensure_ascii=False, indent=2)
    system_msg = {
        "role": "user",
        "content": f"""Ты финансовый ассистент дизайн-студии Avangard.
Управляешь банковским счётом через Т-Банк API.
Можешь читать документы и изображения — извлекать реквизиты, суммы, ИНН.

Инструменты:
{tools_desc}

Правила:
1. Для выполнения задачи сначала собери нужные данные
2. Если не хватает данных — используй ask_user
3. При выставлении счёта всегда подтверди сумму и получателя перед отправкой
4. Суммы в рублях, форматируй красиво
5. Отвечай на русском

Всегда отвечай ТОЛЬКО JSON без пояснений:
{{"tool": "название", "params": {{...}}}}"""
    }

    messages = [system_msg] + messages_history

    for step in range(10):
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "anthropic/claude-sonnet-4-5",
                    "messages": messages,
                    "max_tokens": 1000,
                    "temperature": 0.1,
                    "stream": False
                }
            )
        resp = r.json()
        if "choices" not in resp:
            print(f"AI error: {resp}")
            return "⚠️ ИИ временно недоступен"

        raw = resp["choices"][0]["message"]["content"] or ""
        print(f"AI step {step}: {raw[:200]}")
        messages.append({"role": "assistant", "content": raw})

        try:
            clean = re.sub(r"```json|```", "", raw).strip()
            # Берём первый JSON блок
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if not match:
                return raw
            action = json.loads(match.group())
        except:
            return raw

        tool = action.get("tool")
        params = action.get("params", {})

        if tool in ["answer", "ask_user"]:
            return params.get("text") or params.get("question", "")

        result = await execute_tool(tool, params)
        messages.append({
            "role": "user",
            "content": f"Результат инструмента {tool}: {json.dumps(result, ensure_ascii=False)}"
        })

    return "Не удалось обработать запрос"

# ═══════════════════════════════════════════
# TELEGRAM ХЕНДЛЕРЫ
# ═══════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "💰 *Бот-бухгалтер Avangard*\n\n"
        "Умею:\n"
        "— Показывать баланс и выписку\n"
        "— Выставлять счета клиентам\n"
        "— Создавать СБП ссылки для оплаты\n"
        "— Анализировать расходы\n"
        "— Читать счета из фото и PDF\n\n"
        "Примеры:\n"
        "«Какой баланс?»\n"
        "«Выставь счёт Иванову на 50000»\n"
        "«Создай СБП ссылку на 15000 за дизайн»\n"
        "«Сколько потратил за месяц?»\n\n"
        "/reset — сбросить диалог",
        parse_mode="Markdown"
    )

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    dialogs[message.chat.id] = []
    await message.answer("🔄 Диалог сброшен")

@dp.message(F.photo)
async def handle_photo(message: Message):
    thinking = await message.reply("📷 Читаю изображение...")
    
    # Скачиваем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    
    async with httpx.AsyncClient() as c:
        img_data = (await c.get(file_url)).content
    img_b64 = base64.b64encode(img_data).decode()
    
    caption = message.caption or "Обработай этот документ и выполни нужные действия"
    history = dialogs.get(message.chat.id, [])
    
    # Добавляем изображение в историю
    history.append({
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            {"type": "text", "text": caption}
        ]
    })
    
    try:
        response = await run_agent(history)
        history.append({"role": "assistant", "content": response})
        dialogs[message.chat.id] = history[-20:]
    except Exception as e:
        print(f"Error: {e}")
        await thinking.edit_text("⚠️ Ошибка обработки")
        return

    await thinking.edit_text(response, parse_mode="Markdown")

@dp.message(F.document)
async def handle_document(message: Message):
    doc = message.document
    if not doc.mime_type in ["application/pdf", "image/jpeg", "image/png"]:
        await message.reply("Поддерживаю PDF и изображения")
        return
    
    thinking = await message.reply("📄 Читаю документ...")
    
    file = await bot.get_file(doc.file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    
    async with httpx.AsyncClient() as c:
        file_data = (await c.get(file_url)).content
    file_b64 = base64.b64encode(file_data).decode()
    
    caption = message.caption or "Обработай этот документ"
    history = dialogs.get(message.chat.id, [])
    
    if doc.mime_type == "application/pdf":
        history.append({
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": file_b64}},
                {"type": "text", "text": caption}
            ]
        })
    else:
        history.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{doc.mime_type};base64,{file_b64}"}},
                {"type": "text", "text": caption}
            ]
        })
    
    try:
        response = await run_agent(history)
        history.append({"role": "assistant", "content": response})
        dialogs[message.chat.id] = history[-20:]
    except Exception as e:
        print(f"Error: {e}")
        await thinking.edit_text("⚠️ Ошибка")
        return

    await thinking.edit_text(response, parse_mode="Markdown")

@dp.message()
async def handle_text(message: Message):
    text = message.text or ""
    if text.startswith("/"):
        return

    thinking = await message.reply("🤔")
    history = dialogs.get(message.chat.id, [])
    history.append({"role": "user", "content": text})

    try:
        response = await run_agent(history)
        history.append({"role": "assistant", "content": response})
        dialogs[message.chat.id] = history[-20:]
    except Exception as e:
        print(f"Error: {e}")
        await thinking.edit_text("⚠️ Ошибка")
        return

    await thinking.edit_text(response, parse_mode="Markdown")

async def main():
    print("Finance bot started")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())
