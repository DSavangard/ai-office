import os
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path="/opt/ai-office/finance/.env")

TOKEN = os.getenv("TBANK_TOKEN")
ACCOUNT = os.getenv("TBANK_ACCOUNT")
URL = "https://business.tbank.ru/openapi/api"
H = lambda: {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json", "Content-Type": "application/json"}

# ─── СЧЕТА ───────────────────────────────────────────────────────

async def get_accounts():
    """Список всех счетов с балансами"""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v2/bank-accounts", headers=H())
        if r.status_code == 200:
            return [{"name": a["name"], "number": a["accountNumber"],
                     "balance": a["balance"]["otb"],
                     "currency": a["currency"]} for a in r.json()]
        return {"error": r.text}

# ─── ВЫПИСКА ─────────────────────────────────────────────────────

async def get_statement(days=7, account=None, limit=100):
    """Выписка по операциям за период"""
    acc = account or ACCOUNT
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = datetime.utcnow().strftime("%Y-%m-%dT23:59:59Z")
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v1/statement",
            params={"accountNumber": acc, "from": date_from, "to": date_to,
                    "limit": limit, "operationStatus": "Transaction"},
            headers=H())
        if r.status_code == 200:
            ops = r.json().get("operations", [])
            return [{"date": op.get("operationDate", "")[:10],
                     "type": op.get("typeOfOperation"),
                     "amount": op.get("rubleAmount"),
                     "description": op.get("description", "")[:80],
                     "category": op.get("category", ""),
                     "counterparty": op.get("counterParty", {}).get("name", "")[:50],
                     "status": op.get("operationStatus")} for op in ops]
        return {"error": r.text}

async def get_summary(days=7):
    """Сводка: доходы, расходы, топ категории"""
    ops = await get_statement(days=days, limit=500)
    if isinstance(ops, dict) and "error" in ops:
        return ops
    income = sum(op["amount"] for op in ops if op["type"] == "Credit")
    expenses = sum(op["amount"] for op in ops if op["type"] == "Debit")
    by_cat = {}
    by_counterparty = {}
    for op in ops:
        if op["type"] == "Debit":
            by_cat[op["category"]] = by_cat.get(op["category"], 0) + op["amount"]
            if op["counterparty"]:
                by_counterparty[op["counterparty"]] = by_counterparty.get(op["counterparty"], 0) + op["amount"]
    top_expenses = sorted(by_counterparty.items(), key=lambda x: -x[1])[:5]
    return {
        "period_days": days,
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "profit": round(income - expenses, 2),
        "operations_count": len(ops),
        "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])},
        "top_expenses": [{"name": k, "amount": round(v, 2)} for k, v in top_expenses]
    }

# ─── ВЫСТАВЛЕНИЕ СЧЕТОВ ──────────────────────────────────────────

async def send_invoice(amount: float, description: str, inn: str = None,
                       name: str = None, phone: str = None, email: str = None,
                       comment: str = None):
    """Выставить счёт клиенту — вернёт ссылку на оплату"""
    payload = {
        "amount": int(amount * 100),  # в копейках
        "description": description,
    }
    if inn:
        payload["customerInn"] = inn
    if name:
        payload["customerName"] = name
    if phone:
        payload["customerPhone"] = phone
    if email:
        payload["customerEmail"] = email
    if comment:
        payload["comment"] = comment

    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{URL}/v1/invoice/send", headers=H(), json=payload)
        if r.status_code == 200:
            data = r.json()
            return {
                "invoice_id": data.get("invoiceId"),
                "url": data.get("invoiceUrl"),
                "pdf_url": data.get("pdfUrl"),
                "status": data.get("invoiceStatus")
            }
        return {"error": r.text}

async def get_invoice_status(invoice_id: str):
    """Статус выставленного счёта"""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v1/invoice/{invoice_id}/info", headers=H())
        if r.status_code == 200:
            data = r.json()
            return {
                "invoice_id": invoice_id,
                "status": data.get("invoiceStatus"),
                "amount": data.get("amount", 0) / 100,
                "paid_at": data.get("paymentDate")
            }
        return {"error": r.text}

# ─── СБП ССЫЛКИ ──────────────────────────────────────────────────

async def create_sbp_link(amount: float, description: str, one_time: bool = True):
    """Создать ссылку СБП для оплаты"""
    payload = {
        "amount": int(amount * 100),
        "description": description,
        "qrType": "QRDynamic" if one_time else "QRStatic",
        "redirectUrl": "",
    }
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{URL}/v1/b2b/qr/register", headers=H(), json=payload)
        if r.status_code == 200:
            data = r.json()
            return {
                "qr_id": data.get("qrId"),
                "url": data.get("payload"),
                "image_url": data.get("qrImage"),
                "status": data.get("qrStatus")
            }
        return {"error": r.text}

async def get_sbp_link_status(qr_id: str):
    """Статус оплаты СБП ссылки"""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v1/b2b/qr/{qr_id}/info", headers=H())
        if r.status_code == 200:
            data = r.json()
            return {"qr_id": qr_id, "status": data.get("qrStatus"), "amount": data.get("amount", 0) / 100}
        return {"error": r.text}

# ─── БИЗНЕС-КАРТЫ ────────────────────────────────────────────────

async def get_cards():
    """Список бизнес-карт компании"""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v3/card", headers=H())
        if r.status_code == 200:
            return [{"ucid": card.get("ucid"), "last4": card.get("lastFour"),
                     "holder": card.get("cardHolder"), "status": card.get("cardStatus"),
                     "account": card.get("accountNumber")} for card in r.json()]
        return {"error": r.text}

async def get_card_limits(ucid: int):
    """Лимиты по конкретной карте"""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v1/card/{ucid}/limits", headers=H())
        if r.status_code == 200:
            return r.json()
        return {"error": r.text}

# ─── ЭКВАЙРИНГ ───────────────────────────────────────────────────

async def get_terminals():
    """Список терминалов торгового эквайринга"""
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v1/acquiring/terminals", headers=H())
        if r.status_code == 200:
            return r.json()
        return {"error": r.text}

async def get_terminal_operations(terminal_id: str, days: int = 7):
    """Операции по конкретному терминалу"""
    date_from = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    date_to = datetime.utcnow().strftime("%Y-%m-%dT23:59:59Z")
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{URL}/v1/acquiring/terminals/{terminal_id}/operations",
            params={"from": date_from, "to": date_to}, headers=H())
        if r.status_code == 200:
            return r.json()
        return {"error": r.text}
