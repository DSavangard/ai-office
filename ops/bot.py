import asyncio
import os
import re
import json
import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv(dotenv_path="/opt/ai-office/ops/.env")

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUGILE_KEY = os.getenv("YOUGILE_KEY")
GEMINI_KEY = os.getenv("GEMINI_KEY")
PROXY_URL = os.getenv("PROXY_URL")
API = "https://ru.yougile.com/api-v2"
GROUP_ID = -1004316299083

CRM_PROJECT_ID = "10b374ff-1aaa-4671-bdba-e88af5c0b21e"
DESIGN_PROJECT_ID = "a1c30686-2725-49da-a214-ea108db56046"

CRM_COLUMNS = {
    "первое касание": "51dca98c-0101-4898-a5ee-fb1668fb975c",
    "кп":             "e11d5f19-a052-47ba-bd7b-5830d0aee60c",
    "оплата":         "f6f149bf-9091-4a27-aa60-5be04b8e2d8b",
    "в работе":       "2558970b-bffd-44b1-98c4-c14b0122864d",
    "успех":          "022045f4-800d-4e0f-953b-946dafbeb532",
    "отказ":          "69b304fb-375c-4d40-adaa-75a8207291eb",
}
SOURCES = {
    "529c5b3e5925": "Яндекс",
    "50b23e208901": "Авито",
    "040635de1556": "Телеграмм",
    "37230fede7c4": "Сарафан",
    "b545d6402340": "Вконтакте",
}
STICKER_SOURCE = "e05f8137-1d8f-49c7-8494-e39e3e8f2171"

HEADERS = lambda: {"Authorization": f"Bearer {YOUGILE_KEY}", "Content-Type": "application/json"}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ═══════════════════════════════════════════
# ИНСТРУМЕНТЫ — YouGile API
# ═══════════════════════════════════════════

async def yougile_get(path):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{API}{path}", headers=HEADERS())
        return r.json() if r.status_code == 200 else {"error": r.text}

async def yougile_post(path, data):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{API}{path}", headers=HEADERS(), json=data)
        return r.json() if r.status_code == 201 else {"error": r.text}

async def yougile_put(path, data):
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.put(f"{API}{path}", headers=HEADERS(), json=data)
        return {"ok": r.status_code == 200}

# Инструменты которые видит ИИ
TOOLS = {
    "get_crm_leads": {
        "desc": "Получить список активных лидов из CRM",
        "params": {}
    },
    "move_crm_lead": {
        "desc": "Переместить лид в CRM в другую колонку",
        "params": {"lead_id": "ID лида", "column": "название колонки: первое касание, кп, оплата, в работе, успех, отказ"}
    },
    "set_lead_amount": {
        "desc": "Установить сумму сделки для лида",
        "params": {"lead_id": "ID лида", "amount": "сумма в рублях"}
    },
    "get_design_boards": {
        "desc": "Получить список досок в проекте Avangard Design (доски дизайнеров)",
        "params": {}
    },
    "get_board_columns": {
        "desc": "Получить колонки конкретной доски",
        "params": {"board_id": "ID доски"}
    },
    "create_design_task": {
        "desc": "Создать задачу на доске дизайнера",
        "params": {"column_id": "ID колонки", "title": "название задачи", "description": "описание задачи (опционально)"}
    },
    "get_company_users": {
        "desc": "Получить список сотрудников компании",
        "params": {}
    },
    "answer": {
        "desc": "Ответить пользователю текстом",
        "params": {"text": "текст ответа"}
    },
    "ask_user": {
        "desc": "Задать уточняющий вопрос пользователю",
        "params": {"question": "вопрос пользователю"}
    },
    "get_board_tasks": {
        "desc": "Получить все задачи на доске дизайнера (по всем колонкам)",
        "params": {"board_id": "ID доски"}
    }
}

async def execute_tool(tool_name, params):
    print(f"TOOL: {tool_name} {params}")
    
    if tool_name == "get_crm_leads":
        leads = []
        for col_name, col_id in CRM_COLUMNS.items():
            if col_name in ["успех", "отказ"]:
                continue
            data = await yougile_get(f"/tasks?columnId={col_id}")
            for t in data.get("content", []):
                sid = t.get("stickers", {}).get(STICKER_SOURCE, "")
                leads.append({
                    "id": t["id"],
                    "title": t["title"],
                    "column": col_name,
                    "amount": t.get("deal", {}).get("dealAmount", 0),
                    "source": SOURCES.get(sid, "—"),
                    "code": t.get("idTaskProject", ""),
                })
        return {"leads": leads}

    elif tool_name == "move_crm_lead":
        col_id = CRM_COLUMNS.get(params.get("column", "").lower())
        if not col_id:
            return {"error": f"Колонка не найдена: {params.get('column')}"}
        result = await yougile_put(f"/tasks/{params['lead_id']}", {"columnId": col_id})
        return result

    elif tool_name == "set_lead_amount":
        result = await yougile_put(f"/tasks/{params['lead_id']}", {"deal": {"dealAmount": int(params.get("amount", 0))}})
        return result

    elif tool_name == "get_design_boards":
        data = await yougile_get(f"/boards?projectId={DESIGN_PROJECT_ID}")
        boards = [{"id": b["id"], "title": b["title"]} for b in data.get("content", [])]
        return {"boards": boards}

    elif tool_name == "get_board_columns":
        data = await yougile_get(f"/columns?boardId={params['board_id']}")
        columns = [{"id": c["id"], "title": c["title"]} for c in data.get("content", [])]
        return {"columns": columns}

    elif tool_name == "create_design_task":
        payload = {
            "title": params["title"],
            "columnId": params["column_id"],
        }
        if params.get("description"):
            payload["description"] = params["description"]
        result = await yougile_post("/tasks", payload)
        return result

    elif tool_name == "get_company_users":
        data = await yougile_get("/users")
        users = [{"id": u["id"], "name": u.get("name", u.get("email", ""))} for u in data.get("content", [])]
        return {"users": users}

    elif tool_name == "get_board_tasks":
        cols = await yougile_get(f"/columns?boardId={params['board_id']}")
        all_tasks = []
        for col in cols.get("content", []):
            tasks = await yougile_get(f"/tasks?columnId={col['id']}")
            for t in tasks.get("content", []):
                all_tasks.append({
                    "id": t["id"],
                    "title": t["title"],
                    "column": col["title"],
                    "completed": t.get("completed", False),
                })
        return {"tasks": all_tasks, "total": len(all_tasks)}

    elif tool_name in ["answer", "ask_user"]:
        return {"text": params.get("text") or params.get("question")}

    return {"error": f"Неизвестный инструмент: {tool_name}"}

# ═══════════════════════════════════════════
# AI АГЕНТ — цикл рассуждений
# ═══════════════════════════════════════════

async def run_agent(user_message, history):
    tools_desc = json.dumps(TOOLS, ensure_ascii=False, indent=2)
    
    system = f"""Ты операционный ИИ-ассистент дизайн-студии Avangard.
Ты управляешь CRM (YouGile) и задачами команды.

У тебя есть инструменты:
{tools_desc}

Правила:
1. Сначала собери нужные данные через инструменты
2. Если нужна информация от пользователя — используй ask_user
3. Когда всё готово — выполни действие
4. Всегда отвечай на русском
5. При переносе лида в "в работе" — создай задачу на доске дизайнера

Отвечай ТОЛЬКО JSON:
{{"tool": "название_инструмента", "params": {{...}}}}"""

    messages = [{"role": "user", "parts": [{"text": system}]}]
    for h in history:
        messages.append(h)
    messages.append({"role": "user", "parts": [{"text": user_message}]})

    max_steps = 8
    for step in range(max_steps):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.getenv('OPENROUTER_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "anthropic/claude-sonnet-4-5",
                    "messages": [{"role": m["role"] if m["role"] != "model" else "assistant", "content": m["parts"][0]["text"]} for m in messages],
                    "max_tokens": 500,
                    "temperature": 0.1,
                    "stream": False
                }
            )
        resp = r.json()
        
        if "choices" not in resp:
            print(f"AI error: {resp}")
            return "⚠️ ИИ временно недоступен", history

        raw = resp["choices"][0]["message"]["content"] or ""
        print(f"AI step {step}: {raw[:150]}")
        
        # Добавляем ответ ИИ в историю
        messages.append({"role": "model", "parts": [{"text": raw}]})

        # Парсим JSON
        try:
            clean = re.sub(r"```json|```", "", raw).strip()
            action = json.loads(clean)
        except:
            # ИИ ответил текстом — возвращаем как есть
            return raw, history

        tool = action.get("tool")
        params = action.get("params", {})

        if tool in ["answer", "ask_user"]:
            text = params.get("text") or params.get("question", "")
            return text, messages

        # Выполняем инструмент
        result = await execute_tool(tool, params)
        print(f"RESULT: {str(result)[:200]}")

        # Добавляем результат в историю
        messages.append({
            "role": "user",
            "parts": [{"text": f"Результат инструмента {tool}: {json.dumps(result, ensure_ascii=False)}"}]
        })

    return "Не удалось выполнить задачу за отведённое количество шагов", history

# ═══════════════════════════════════════════
# ХРАНИЛИЩЕ ДИАЛОГОВ
# ═══════════════════════════════════════════

dialogs = {}

# ═══════════════════════════════════════════
# TELEGRAM ХЕНДЛЕРЫ
# ═══════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "🤖 *Операционщик Avangard*\n\n"
        "Пиши что нужно сделать:\n"
        "— «Брендинг ВБ пошёл в работу»\n"
        "— «Создай задачу Анатолию по Брендингу ВБ»\n"
        "— «Сколько активных лидов?»\n"
        "— «Переведи Иванова в КП»\n\n"
        "/reset — сбросить диалог",
        parse_mode="Markdown"
    )

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    dialogs[message.chat.id] = []
    await message.answer("🔄 Диалог сброшен")

@dp.message()
async def handle_message(message: Message):
    print(f"IN: chat={message.chat.id} user=@{message.from_user.username} text={str(message.text)[:80]}")
    
    text = message.text or ""
    if text.startswith("/"):
        return
    if message.chat.id != GROUP_ID and message.chat.type != "private":
        return

    thinking = await message.reply("🤔")
    
    history = dialogs.get(message.chat.id, [])
    
    try:
        response, new_history = await run_agent(text, history)
        dialogs[message.chat.id] = new_history[-20:]  # храним последние 20 сообщений
    except Exception as e:
        print(f"Agent error: {e}")
        await thinking.edit_text("⚠️ Ошибка агента")
        return

    await thinking.edit_text(response, parse_mode="Markdown")

async def main():
    print("Ops bot started")
    await dp.start_polling(bot, allowed_updates=["message"])

if __name__ == "__main__":
    asyncio.run(main())
