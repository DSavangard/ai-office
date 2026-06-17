import asyncio
import os
import httpx
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
YOUGILE_KEY = os.getenv("YOUGILE_KEY")
API = "https://ru.yougile.com/api-v2"

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

# Активные колонки — без отказов и успехов для обычного вывода
ACTIVE_COLUMNS = {
    "первое касание": "51dca98c-0101-4898-a5ee-fb1668fb975c",
    "кп":             "e11d5f19-a052-47ba-bd7b-5830d0aee60c",
    "оплата":         "f6f149bf-9091-4a27-aa60-5be04b8e2d8b",
    "в работе":       "2558970b-bffd-44b1-98c4-c14b0122864d",
}

SOURCES = {
    "529c5b3e5925": "Яндекс",
    "50b23e208901": "Авито",
    "040635de1556": "Телеграмм",
    "37230fede7c4": "Сарафан",
    "b545d6402340": "Вконтакте",
}

STICKER_SOURCE = "e05f8137-1d8f-49c7-8494-e39e3e8f2171"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ─── CORE FUNCTIONS ───────────────────────────────────────────────

async def get_leads(column_name: str = None, include_archive: bool = False) -> list:
    """Получить лиды — активные или все включая отказы"""
    results = []
    if column_name and column_name in COLUMNS:
        cols = {column_name: COLUMNS[column_name]}
    elif include_archive:
        cols = COLUMNS
    else:
        cols = ACTIVE_COLUMNS
    async with httpx.AsyncClient() as client:
        for col_name, col_id in cols.items():
            r = await client.get(f"{API}/tasks?columnId={col_id}", headers=HEADERS())
            if r.status_code == 200:
                for t in r.json().get("content", []):
                    source_id = t.get("stickers", {}).get(STICKER_SOURCE, "")
                    results.append({
                        "id": t["id"],
                        "title": t["title"],
                        "column": col_name,
                        "amount": t.get("deal", {}).get("dealAmount", 0),
                        "source": SOURCES.get(source_id, "—"),
                        "code": t.get("idTaskProject", ""),
                        "timestamp": t.get("timestamp", 0),
                    })
    return results

async def create_lead(title: str, source: str = None, amount: int = 0) -> dict:
    """Создать лид в Первое касание"""
    stickers = {}
    if source:
        source_id = next((k for k, v in SOURCES.items() if v.lower() == source.lower()), None)
        if source_id:
            stickers[STICKER_SOURCE] = source_id
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API}/tasks", headers=HEADERS(), json={
            "title": title,
            "columnId": COLUMNS["первое касание"],
            "stickers": stickers,
            "deal": {"dealAmount": amount}
        })
    return r.json() if r.status_code == 201 else {"error": r.text}

async def move_lead(task_id: str, column_name: str) -> bool:
    """Переместить лид в другую колонку"""
    col_id = COLUMNS.get(column_name.lower())
    if not col_id:
        return False
    async with httpx.AsyncClient() as client:
        r = await client.put(f"{API}/tasks/{task_id}", headers=HEADERS(), json={"columnId": col_id})
    return r.status_code == 200

async def get_lead_details(task_id: str) -> dict:
    """Получить детали лида"""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API}/tasks/{task_id}", headers=HEADERS())
    if r.status_code != 200:
        return {}
    t = r.json()
    source_id = t.get("stickers", {}).get(STICKER_SOURCE, "")
    return {
        "id": t["id"],
        "title": t["title"],
        "amount": t.get("deal", {}).get("dealAmount", 0),
        "source": SOURCES.get(source_id, "—"),
        "code": t.get("idTaskProject", ""),
        "column": COLUMNS_RU.get(t.get("columnId", ""), "—"),
        "timestamp": t.get("timestamp", 0),
    }

# ─── HELPERS ──────────────────────────────────────────────────────

def format_lead(lead: dict) -> str:
    amount = f"{lead['amount']:,}".replace(",", " ") if lead["amount"] else "—"
    return (
        f"*{lead['title']}* ({lead['code']})\n"
        f"  💰 {amount} ₽  |  📍 {lead['source']}\n"
        f"  `{lead['id'][:8]}`"
    )

async def find_full_id(task_id: str) -> str | None:
    leads = await get_leads(include_archive=True)
    return next((l["id"] for l in leads if l["id"].startswith(task_id)), None)

# ─── TELEGRAM COMMANDS ────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 *CRM Avangard*\n\n"
        "Команды:\n"
        "/leads — активные лиды по этапам\n"
        "/add Клиент | Источник | Сумма — добавить лид\n"
        "/move ID колонка — переместить лид\n"
        "/lead ID — детали лида\n"
        "/stats — сводка за неделю\n\n"
        "Этапы: первое касание, кп, оплата, в работе, успех, отказ\n"
        "Источники: Авито, Яндекс, Телеграмм, Сарафан, Вконтакте",
        parse_mode="Markdown"
    )

@dp.message(Command("leads"))
async def cmd_leads(message: Message):
    args = message.text.replace("/leads", "").strip().lower() or None
    await message.answer("⏳ Загружаю...")
    leads = await get_leads(args)
    if not leads:
        await message.answer("Нет активных лидов" + (f" в «{args}»" if args else ""))
        return
    by_col = {}
    for l in leads:
        by_col.setdefault(l["column"], []).append(l)
    lines = []
    total_amount = 0
    for col, items in by_col.items():
        col_sum = sum(l["amount"] or 0 for l in items)
        col_sum_fmt = f"{col_sum:,}".replace(",", " ")
        lines.append(f"\n*{col.upper()}* ({len(items)}) — {col_sum_fmt} ₽")
        for l in items:
            lines.append(format_lead(l))
            total_amount += l["amount"] or 0
    total = f"{total_amount:,}".replace(",", " ")
    lines.append(f"\n💼 Итого: {len(leads)} лидов  |  💰 {total} ₽")
    await message.answer("\n".join(lines), parse_mode="Markdown")

@dp.message(Command("add"))
async def cmd_add(message: Message):
    text = message.text.replace("/add", "").strip()
    if not text:
        await message.answer(
            "Формат: /add Клиент | Источник | Сумма\n"
            "Пример: /add Иван Иванов | Авито | 50000"
        )
        return
    parts = [p.strip() for p in text.split("|")]
    title = parts[0]
    source = parts[1] if len(parts) > 1 else None
    amount = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    result = await create_lead(title, source, amount)
    if "error" in result:
        await message.answer(f"❌ Ошибка: {result['error']}")
    else:
        await message.answer(f"✅ Лид добавлен: *{title}*", parse_mode="Markdown")

@dp.message(Command("move"))
async def cmd_move(message: Message):
    parts = message.text.replace("/move", "").strip().split(" ", 1)
    if len(parts) < 2:
        await message.answer("Формат: /move ID колонка\nПример: /move 00ed308a кп")
        return
    task_id, col = parts[0], parts[1].lower().strip()
    full_id = await find_full_id(task_id)
    if not full_id:
        await message.answer("❌ Лид не найден")
        return
    ok = await move_lead(full_id, col)
    await message.answer(f"✅ Перемещён в «{col}»" if ok else "❌ Ошибка перемещения")

@dp.message(Command("lead"))
async def cmd_lead(message: Message):
    task_id = message.text.replace("/lead", "").strip()
    if not task_id:
        await message.answer("Укажи ID: /lead 00ed308a")
        return
    full_id = await find_full_id(task_id)
    if not full_id:
        await message.answer("❌ Лид не найден")
        return
    d = await get_lead_details(full_id)
    amount = f"{d['amount']:,}".replace(",", " ") if d.get("amount") else "—"
    await message.answer(
        f"*{d['title']}* ({d['code']})\n"
        f"Этап: {d['column']}\n"
        f"Сумма: {amount} ₽\n"
        f"Источник: {d['source']}\n"
        f"ID: `{d['id']}`",
        parse_mode="Markdown"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    import time
    await message.answer("⏳ Считаю...")
    week_ago = (time.time() - 7 * 24 * 3600) * 1000
    leads = await get_leads(include_archive=True)
    week_leads = [l for l in leads if l["timestamp"] >= week_ago]
    if not week_leads:
        await message.answer("За последнюю неделю новых лидов нет")
        return
    by_source = {}
    by_col = {}
    total = 0
    for l in week_leads:
        by_source[l["source"]] = by_source.get(l["source"], 0) + 1
        by_col[l["column"]] = by_col.get(l["column"], 0) + 1
        total += l["amount"] or 0
    lines = ["📊 *Сводка за 7 дней*\n"]
    lines.append(f"Всего лидов: {len(week_leads)}")
    lines.append(f"Сумма сделок: {total:,} ₽\n".replace(",", " "))
    lines.append("*По источникам:*")
    for src, cnt in sorted(by_source.items(), key=lambda x: -x[1]):
        lines.append(f"  {src}: {cnt}")
    lines.append("\n*По этапам:*")
    for col, cnt in by_col.items():
        lines.append(f"  {col}: {cnt}")
    await message.answer("\n".join(lines), parse_mode="Markdown")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
