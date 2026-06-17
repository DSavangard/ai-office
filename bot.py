import asyncio
import os
import re
import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUGILE_KEY = os.getenv("YOUGILE_KEY")
API = "https://ru.yougile.com/api-v2"
LEADS_GROUP_ID = -1004316299083

HEADERS = lambda: {"Authorization": f"Bearer {YOUGILE_KEY}", "Content-Type": "application/json"}

COLUMNS = {
    "первое касание": "51dca98c-0101-4898-a5ee-fb1668fb975c",
    "кп":             "e11d5f19-a052-47ba-bd7b-5830d0aee60c",
    "оплата":         "f6f149bf-9091-4a27-aa60-5be04b8e2d8b",
    "в работе":       "2558970b-bffd-44b1-98c4-c14b0122864d",
    "успех":          "022045f4-800d-4e0f-953b-946dafbeb532",
    "отказ":          "69b304fb-375c-4d40-adaa-75a8207291eb",
}
COLUMNS_RU = {v: k for k, v in COLUMNS.items()}
ACTIVE_COLUMNS = {k: v for k, v in COLUMNS.items() if k not in ["успех", "отказ"]}
SOURCES = {
    "529c5b3e5925": "Яндекс",
    "50b23e208901": "Авито",
    "040635de1556": "Телеграмм",
    "37230fede7c4": "Сарафан",
    "b545d6402340": "Вконтакте",
}
SOURCES_BY_NAME = {v: k for k, v in SOURCES.items()}
STICKER_SOURCE = "e05f8137-1d8f-49c7-8494-e39e3e8f2171"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def get_leads(column_name=None, include_archive=False):
    results = []
    cols = {column_name: COLUMNS[column_name]} if column_name and column_name in COLUMNS else (COLUMNS if include_archive else ACTIVE_COLUMNS)
    async with httpx.AsyncClient(timeout=30.0) as client:
        for col_name, col_id in cols.items():
            r = await client.get(f"{API}/tasks?columnId={col_id}", headers=HEADERS())
            if r.status_code == 200:
                for t in r.json().get("content", []):
                    source_id = t.get("stickers", {}).get(STICKER_SOURCE, "")
                    results.append({
                        "id": t["id"], "title": t["title"], "column": col_name,
                        "amount": t.get("deal", {}).get("dealAmount", 0),
                        "source": SOURCES.get(source_id, "—"),
                        "code": t.get("idTaskProject", ""),
                        "timestamp": t.get("timestamp", 0),
                    })
    return results

async def create_lead(title, source=None, amount=0, description=None):
    stickers = {}
    if source:
        sid = SOURCES_BY_NAME.get(source)
        if sid:
            stickers[STICKER_SOURCE] = sid
    payload = {"title": title, "columnId": COLUMNS["первое касание"], "stickers": stickers, "deal": {"dealAmount": amount}}
    if description:
        payload["description"] = description
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{API}/tasks", headers=HEADERS(), json=payload)
    return r.json() if r.status_code == 201 else {"error": r.text}

async def move_lead(task_id, column_name):
    col_id = COLUMNS.get(column_name.lower())
    if not col_id:
        return False
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.put(f"{API}/tasks/{task_id}", headers=HEADERS(), json={"columnId": col_id})
    return r.status_code == 200

async def find_full_id(task_id):
    leads = await get_leads(include_archive=True)
    return next((l["id"] for l in leads if l["id"].startswith(task_id)), None)

def parse_cf7(text):
    result = {}
    for field, pattern in [("name", r"Имя:\s*(.+)"), ("phone", r"Телефон:\s*(.+)"), ("topic", r"Тема:\s*(.+)")]:
        m = re.search(pattern, text)
        if m:
            result[field] = m.group(1).strip()
    return result

# ── КОМАНДЫ ──────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 *CRM Avangard*\n\n/leads — активные лиды\n/add Клиент | Источник | Сумма\n/move ID колонка\n/lead ID\n/stats — сводка за неделю", parse_mode="Markdown")

@dp.message(Command("leads"))
async def cmd_leads(message: Message):
    await message.answer("⏳ Загружаю...")
    leads = await get_leads(message.text.replace("/leads", "").strip().lower() or None)
    if not leads:
        await message.answer("Нет активных лидов")
        return
    by_col = {}
    for l in leads:
        by_col.setdefault(l["column"], []).append(l)
    lines = []
    total = 0
    for col, items in by_col.items():
        s = sum(l["amount"] or 0 for l in items)
        lines.append(f"\n*{col.upper()}* ({len(items)}) — {s:,} ₽".replace(",", " "))
        for l in items:
            a = f"{l['amount']:,}".replace(",", " ") if l["amount"] else "—"
            lines.append(f"*{l['title']}* ({l['code']})\n  💰 {a} ₽  |  📍 {l['source']}\n  `{l['id'][:8]}`")
            total += l["amount"] or 0
    lines.append(f"\n💼 Итого: {len(leads)}  |  💰 {total:,} ₽".replace(",", " "))
    await message.answer("\n".join(lines), parse_mode="Markdown")

@dp.message(Command("add"))
async def cmd_add(message: Message):
    text = message.text.replace("/add", "").strip()
    if not text:
        await message.answer("Формат: /add Клиент | Источник | Сумма")
        return
    parts = [p.strip() for p in text.split("|")]
    result = await create_lead(parts[0], parts[1] if len(parts) > 1 else None, int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0)
    await message.answer(f"✅ Лид добавлен: *{parts[0]}*" if "error" not in result else f"❌ {result['error']}", parse_mode="Markdown")

@dp.message(Command("move"))
async def cmd_move(message: Message):
    parts = message.text.replace("/move", "").strip().split(" ", 1)
    if len(parts) < 2:
        await message.answer("Формат: /move ID колонка")
        return
    full_id = await find_full_id(parts[0])
    if not full_id:
        await message.answer("❌ Лид не найден")
        return
    ok = await move_lead(full_id, parts[1].lower().strip())
    await message.answer(f"✅ Перемещён в «{parts[1]}»" if ok else "❌ Ошибка")

@dp.message(Command("lead"))
async def cmd_lead(message: Message):
    task_id = message.text.replace("/lead", "").strip()
    full_id = await find_full_id(task_id)
    if not full_id:
        await message.answer("❌ Лид не найден")
        return
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{API}/tasks/{full_id}", headers=HEADERS())
    t = r.json()
    sid = t.get("stickers", {}).get(STICKER_SOURCE, "")
    a = t.get("deal", {}).get("dealAmount", 0)
    await message.answer(
        f"*{t['title']}* ({t.get('idTaskProject','')})\n"
        f"Этап: {COLUMNS_RU.get(t.get('columnId',''), '—')}\n"
        f"Сумма: {a:,} ₽\nИсточник: {SOURCES.get(sid,'—')}\nID: `{t['id']}`".replace(",", " "),
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    import time
    await message.answer("⏳ Считаю...")
    week_ago = (time.time() - 7 * 24 * 3600) * 1000
    leads = [l for l in await get_leads(include_archive=True) if l["timestamp"] >= week_ago]
    if not leads:
        await message.answer("За неделю лидов нет")
        return
    by_src = {}
    total = 0
    for l in leads:
        by_src[l["source"]] = by_src.get(l["source"], 0) + 1
        total += l["amount"] or 0
    lines = ["📊 *Сводка за 7 дней*\n", f"Лидов: {len(leads)}", f"Сумма: {total:,} ₽\n".replace(",", " "), "*По источникам:*"]
    for src, cnt in sorted(by_src.items(), key=lambda x: -x[1]):
        lines.append(f"  {src}: {cnt}")
    await message.answer("\n".join(lines), parse_mode="Markdown")

# ── ВСЕ ОСТАЛЬНЫЕ СООБЩЕНИЯ ──────────────────────────────────────

@dp.message()
async def handle_all(message: Message):
    text = message.text or ""
    print(f"MSG: chat={message.chat.id} user={message.from_user.username} is_bot={message.from_user.is_bot} text={text[:80]}")
    if "Заявка на сайт" in text and message.chat.id == LEADS_GROUP_ID:
        data = parse_cf7(text)
        if data.get("name"):
            name = data["name"]
            phone = data.get("phone", "")
            topic = data.get("topic", "")
            title = f"{name} — {topic}" if topic else name
            desc = f"Телефон: {phone}\nТема: {topic}"
            result = await create_lead(title, source="Яндекс", description=desc)
            if "error" not in result:
                await message.reply(f"✅ Лид создан\n*{title}*\n📞 {phone}\n📂 Первое касание", parse_mode="Markdown")

async def main():
    await dp.start_polling(bot, allowed_updates=["message", "channel_post"])

if __name__ == "__main__":
    asyncio.run(main())
