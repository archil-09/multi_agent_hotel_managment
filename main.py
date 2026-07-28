import os
import json
import asyncpg
from datetime import datetime, timedelta
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

app = FastAPI(title="Hotel SQL Agent")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your actual frontend origin for production
    allow_methods=["*"],
    allow_headers=["*"],
)
import os
print(os.path.abspath(__file__))

STAFF_API_KEY = os.getenv("STAFF_API_KEY")
MANAGER_API_KEY = os.getenv("MANAGER_API_KEY")


def require_staff(x_staff_key: str = Header(default=None), x_manager_key: str = Header(default=None)):
    """Shared-secret check for staff-only endpoints. Accepts EITHER the staff
    key or the manager key — a manager can always do what staff can, but
    salary/HR endpoints still require the manager key specifically
    (see require_manager below)."""
    staff_ok = STAFF_API_KEY and x_staff_key == STAFF_API_KEY
    manager_ok = MANAGER_API_KEY and x_manager_key == MANAGER_API_KEY
    if not (staff_ok or manager_ok):
        raise HTTPException(status_code=401, detail="Invalid or missing staff key.")


def require_manager(x_manager_key: str = Header(default=None)):
    """Separate, stricter key for HR/salary endpoints. A valid staff key is
    NOT enough here on purpose — salary data needs its own credential."""
    if not MANAGER_API_KEY or x_manager_key != MANAGER_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing manager key.")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "6543")
DB_NAME = os.getenv("DB_NAME", "postgres")

DB_USER = os.getenv("DB_USER")                    # read-only role, e.g. agent_readonly.<project_ref>
DB_PASSWORD = os.getenv("DB_PASSWORD")

DB_USER_WRITER = os.getenv("DB_USER_WRITER")       # write role, e.g. agent_writer.<project_ref>
DB_PASSWORD_WRITER = os.getenv("DB_PASSWORD_WRITER")

DB_USER_HR_WRITER = os.getenv("DB_USER_HR_WRITER")         # agent_hr_writer.<project_ref>
DB_PASSWORD_HR_WRITER = os.getenv("DB_PASSWORD_HR_WRITER")

DB_USER_HR_READER = os.getenv("DB_USER_HR_READER")         # agent_hr_reader.<project_ref>
DB_PASSWORD_HR_READER = os.getenv("DB_PASSWORD_HR_READER")

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SCHEMA_DESCRIPTION = """
Tables:
- hotels(id, name, address)
- room_types(id, hotel_id, name, base_price, max_occupancy)
- rooms(id, hotel_id, room_type_id, room_number, status)
- guests(id, full_name, email, phone)
- bookings(id, room_id, guest_id, check_in, check_out, status, total_price)
- payments(id, booking_id, amount, method, paid_at)
"""

# Pending write actions are now stored in the `pending_actions` Postgres
# table (see setup.sql) instead of an in-memory dict, so they survive
# server restarts and work correctly across multiple server instances.


# ---------------------------------------------------------------------------
# DB connections
# ---------------------------------------------------------------------------
async def get_connection():
    """Read-only connection, used for /hotels, /bookings, /ask."""
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        ssl="require",
        statement_cache_size=0,   # required for Supabase's pooler
    )


async def get_writer_connection():
    """Write connection, used only inside /action/confirm, and only ever
    calls pre-defined Postgres functions — never raw INSERT/UPDATE/DELETE."""
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER_WRITER,
        password=DB_PASSWORD_WRITER,
        ssl="require",
        statement_cache_size=0,
    )


async def get_hr_reader_connection():
    """Read-only connection for salary/employee data. Deliberately separate
    from get_connection() — this role has NO access to bookings/guests/etc,
    and regular staff can never reach this path."""
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER_HR_READER,
        password=DB_PASSWORD_HR_READER,
        ssl="require",
        statement_cache_size=0,
    )


async def get_hr_writer_connection():
    """Write connection for HR actions (hire/fire/salary/payroll). Can only
    call the four HR security-definer functions — no direct table access,
    and no access to hotel/booking tables at all."""
    return await asyncpg.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER_HR_WRITER,
        password=DB_PASSWORD_HR_WRITER,
        ssl="require",
        statement_cache_size=0,
    )


# ---------------------------------------------------------------------------
# Basic read endpoints
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Hotel SQL Agent is running"}


@app.get("/hotels")
async def get_hotels(_: None = Depends(require_staff)):
    conn = await get_connection()
    try:
        rows = await conn.fetch("SELECT id, name, address FROM hotels;")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@app.get("/bookings")
async def get_bookings(_: None = Depends(require_staff)):
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT
                b.id AS booking_id,
                g.full_name AS guest_name,
                r.room_number,
                h.name AS hotel_name,
                b.check_in,
                b.check_out,
                b.status
            FROM bookings b
            JOIN rooms r ON b.room_id = r.id
            JOIN hotels h ON r.hotel_id = h.id
            JOIN guests g ON b.guest_id = g.id
            ORDER BY b.check_in;
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@app.get("/rooms")
async def get_rooms(_: None = Depends(require_staff)):
    """Used to populate the room dropdown in the booking form."""
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT r.id, r.room_number, r.status,
                   h.name AS hotel_name,
                   rt.name AS room_type_name, rt.base_price
            FROM rooms r
            JOIN hotels h ON r.hotel_id = h.id
            JOIN room_types rt ON r.room_type_id = rt.id
            ORDER BY h.name, r.room_number;
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@app.get("/room-types")
async def get_room_types(_: None = Depends(require_staff)):
    """Used to populate the room-type dropdown for the update-room-type form."""
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT rt.id, rt.name, rt.base_price, rt.max_occupancy, h.name AS hotel_name
            FROM room_types rt
            JOIN hotels h ON rt.hotel_id = h.id
            ORDER BY h.name, rt.name;
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Natural language -> SQL (read-only agent)
# ---------------------------------------------------------------------------
def clean_sql(raw: str) -> str:
    """Strip markdown code fences the LLM sometimes adds despite instructions
    not to (e.g. ```sql ... ``` or plain ``` ... ```)."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1] if s.count("```") >= 2 else s.lstrip("`")
        s = s.strip()
        if s.lower().startswith("sql"):
            s = s[3:].strip()
    return s.strip()


def is_safe_select(sql: str) -> bool:
    sql_clean = sql.strip().rstrip(";")
    if ";" in sql_clean:
        return False  # multiple statements = reject
    lowered = sql_clean.lower()
    if not lowered.startswith("select"):
        return False
    banned = ["insert", "update", "delete", "drop", "alter", "truncate", "grant"]
    return not any(word in lowered for word in banned)


def generate_sql(question: str) -> str:
    prompt = f"""You are a PostgreSQL expert. Given this schema:
{SCHEMA_DESCRIPTION}

Write ONE read-only SQL SELECT query that answers this question:
"{question}"

Rules:
- Only output the raw SQL query, nothing else. No explanation, no markdown, no backticks.
- Only use SELECT statements. Never write INSERT, UPDATE, DELETE, or DROP.
"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return clean_sql(response.choices[0].message.content)


class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask_agent(payload: Question, _: None = Depends(require_staff)):
    sql = generate_sql(payload.question)

    if not is_safe_select(sql):
        return {"error": "Unsafe or invalid query blocked.", "generated_sql": sql}

    conn = await get_connection()
    try:
        rows = await conn.fetch(sql)
    except Exception as e:
        return {"error": str(e), "generated_sql": sql}
    finally:
        await conn.close()

    return {
        "question": payload.question,
        "generated_sql": sql,
        "result": [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Natural language -> structured write action (propose -> confirm)
# ---------------------------------------------------------------------------
def extract_action(user_text: str) -> dict:
    prompt = f"""You are a hotel staff assistant. Given this staff request:
"{user_text}"

Decide which single action applies, and output ONLY valid JSON, nothing else.

Use "create_booking" ONLY when a guest is being booked into an existing room for specific dates:
{{"action": "create_booking", "room_number": "101", "guest_name": "John Doe", "check_in": "2026-07-10", "check_out": "2026-07-12"}}

Use "cancel_booking" ONLY when an existing booking is being cancelled by its numeric ID:
{{"action": "cancel_booking", "booking_id": 5}}

Use "add_room" when NEW room inventory is being added to a hotel — no guest, no dates involved:
{{"action": "add_room", "hotel_name": "Sunrise Hotel", "room_type_name": "Deluxe", "room_number": "301", "base_price": 4000, "max_occupancy": 2}}

Use "update_room_type" when an EXISTING room type is being renamed or having its price/occupancy changed
(not a specific room — the category, e.g. "Deluxe"). Only include the "new_*" fields that are actually
changing; omit fields that stay the same:
{{"action": "update_room_type", "hotel_name": "Sunrise Hotel", "old_type_name": "Deluxe", "new_type_name": "Premium Deluxe", "new_price": 4500, "new_max_occupancy": 2}}

If the request is ambiguous, missing required details, or doesn't match any action above, respond with:
{{"action": "unknown"}}

If the request mentions MULTIPLE rooms or bookings at once, only extract the FIRST one — the staff
member should submit each additional room/booking as a separate request. Still output only valid
JSON, no extra prose or explanation.
"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    return json.loads(raw)


class ActionRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    action_id: str


REQUIRED_FIELDS = {
    "create_booking": ["room_number", "guest_name", "check_in", "check_out"],
    "cancel_booking": ["booking_id"],
    "add_room": ["hotel_name", "room_type_name", "room_number", "base_price", "max_occupancy"],
    # only hotel_name + old_type_name are truly required — at least one "new_*"
    # field is checked separately below since any single one is a valid update
    "update_room_type": ["hotel_name", "old_type_name"],
}


def validate_intent(intent: dict) -> str | None:
    """Returns an error message if the intent is malformed, else None."""
    action = intent.get("action")
    if action not in REQUIRED_FIELDS:
        return None  # 'unknown' action, handled separately by the caller

    missing = [f for f in REQUIRED_FIELDS[action] if not intent.get(f)]
    if missing:
        return (
            f"Could not fully understand the '{action}' request — missing: {', '.join(missing)}. "
            f"Try rephrasing with all details in one sentence (e.g. include guest name and both dates "
            f"for a booking, or hotel/room type/price for a new room)."
        )

    if action == "update_room_type":
        change_fields = ["new_type_name", "new_price", "new_max_occupancy"]
        if not any(intent.get(f) for f in change_fields):
            return (
                "No change specified for update_room_type — say what should change "
                "(new name, new price, or new max occupancy)."
            )

    room_number = intent.get("room_number")
    if room_number and any(sep in str(room_number) for sep in [",", "/", "&", " and ", ";"]):
        return (
            "Only one room number is allowed per request — looks like multiple were "
            "mentioned together. Please add or book each room separately."
        )

    return None


async def queue_pending_action(conn, action_type: str, payload: dict) -> str:
    """Shared by both the NL-driven and form-driven propose endpoints —
    inserts into pending_actions and returns the new action_id as a string."""
    action_id = await conn.fetchval(
        """
        insert into pending_actions (action_type, payload)
        values ($1, $2::jsonb)
        returning id
        """,
        action_type, json.dumps(payload),
    )
    return str(action_id)


async def log_audit_event(conn, actor_key: str, action_type: str, payload: dict,
                           status: str, error_message: str = None, result: dict = None):
    """Records every confirmed write attempt — success or failure — to the
    audit log. Uses the same connection already open for the action itself,
    so this never needs a separate round trip or extra credentials."""
    try:
        await conn.execute(
            """
            insert into audit_log (actor_key, action_type, payload, status, error_message, result)
            values ($1, $2, $3::jsonb, $4, $5, $6::jsonb)
            """,
            actor_key, action_type, json.dumps(payload), status, error_message,
            json.dumps(result) if result is not None else None,
        )
    except Exception:
        # Logging must never break the actual action — if the audit insert
        # itself fails for some reason, swallow it rather than surface it
        # to the person who just booked a room.
        pass


# ---------------------------------------------------------------------------
# Structured (form-driven) action requests — no LLM involved.
# Faster and more reliable than natural language for fixed, well-known
# actions; NL stays available via /action for anything ad-hoc.
# ---------------------------------------------------------------------------
def validate_single_room_number(v: str) -> str:
    """Rejects room numbers that look like multiple values were jammed into
    one field (e.g. "301, 302", "301/302", "301 and 302")."""
    v = v.strip()
    if any(sep in v for sep in [",", "/", "&", " and ", ";"]):
        raise ValueError(
            "Only one room number is allowed here — looks like multiple were "
            "entered together. Add each room separately."
        )
    return v


class BookRoomForm(BaseModel):
    room_number: str
    guest_name: str
    check_in: str  # "YYYY-MM-DD"
    check_out: str

    @field_validator("room_number")
    @classmethod
    def _single_room(cls, v):
        return validate_single_room_number(v)


class CancelBookingForm(BaseModel):
    booking_id: int


class AddRoomForm(BaseModel):
    hotel_name: str
    room_type_name: str
    room_number: str
    base_price: float
    max_occupancy: int

    @field_validator("room_number")
    @classmethod
    def _single_room(cls, v):
        return validate_single_room_number(v)


class UpdateRoomTypeForm(BaseModel):
    hotel_name: str
    old_type_name: str
    new_type_name: str | None = None
    new_price: float | None = None
    new_max_occupancy: int | None = None


class RecordSaleForm(BaseModel):
    hotel_name: str
    amount: float
    sale_date: str  # "YYYY-MM-DD"
    category: str | None = None
    notes: str | None = None
    entered_by: str


@app.post("/action/book")
async def form_book_room(payload: BookRoomForm, _: None = Depends(require_staff)):
    conn = await get_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "create_booking", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /action/confirm to execute. Expires in 15 minutes."}


@app.post("/action/cancel")
async def form_cancel_booking(payload: CancelBookingForm, _: None = Depends(require_staff)):
    conn = await get_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "cancel_booking", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /action/confirm to execute. Expires in 15 minutes."}


@app.post("/action/add-room")
async def form_add_room(payload: AddRoomForm, _: None = Depends(require_staff)):
    conn = await get_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "add_room", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /action/confirm to execute. Expires in 15 minutes."}


@app.post("/action/update-room-type")
async def form_update_room_type(payload: UpdateRoomTypeForm, _: None = Depends(require_staff)):
    if not any([payload.new_type_name, payload.new_price, payload.new_max_occupancy]):
        return {"error": "No change specified — set a new name, price, or max occupancy."}
    conn = await get_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "update_room_type", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /action/confirm to execute. Expires in 15 minutes."}


@app.post("/action/record-sale")
async def form_record_sale(payload: RecordSaleForm, _: None = Depends(require_staff)):
    """Staff can log a day's sales here. This is intentionally one-way:
    staff get a confirmation of what THEY entered, but can never query
    totals or history — only the manager-only /hr/sales-summary can."""
    conn = await get_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "record_daily_sale", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /action/confirm to execute. Expires in 15 minutes."}


@app.post("/action")
async def propose_action(payload: ActionRequest, _: None = Depends(require_staff)):
    intent = extract_action(payload.text)

    if intent.get("action") not in ("create_booking", "cancel_booking", "add_room", "update_room_type"):
        return {"error": "Could not understand the requested action.", "raw": intent}

    validation_error = validate_intent(intent)
    if validation_error:
        return {"error": validation_error, "raw": intent}

    conn = await get_writer_connection()
    try:
        action_id = await conn.fetchval(
            """
            insert into pending_actions (action_type, payload)
            values ($1, $2::jsonb)
            returning id
            """,
            intent["action"], json.dumps(intent),
        )
    finally:
        await conn.close()

    return {
        "action_id": str(action_id),
        "preview": intent,
        "message": "Review this action and POST it to /action/confirm to execute. Expires in 15 minutes.",
    }


@app.post("/action/confirm")
async def confirm_action(payload: ConfirmRequest, _: None = Depends(require_staff)):
    conn = await get_writer_connection()
    intent, action = None, None
    try:
        row = await conn.fetchrow(
            """
            select id, action_type, payload, status, expires_at
            from pending_actions
            where id = $1::uuid
            """,
            payload.action_id,
        )

        if not row:
            return {"error": "No pending action found for that ID."}
        if row["status"] != "pending":
            return {"error": f"This action was already '{row['status']}' and cannot be run again."}
        if row["expires_at"] < datetime.utcnow().replace(tzinfo=row["expires_at"].tzinfo):
            await conn.execute(
                "update pending_actions set status = 'expired' where id = $1::uuid", payload.action_id
            )
            return {"error": "This action has expired. Please submit the request again."}

        intent = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        action = row["action_type"]

        if action == "create_booking":
            check_in_date = datetime.strptime(intent["check_in"], "%Y-%m-%d").date()
            check_out_date = datetime.strptime(intent["check_out"], "%Y-%m-%d").date()

            booking_id = await conn.fetchval(
                "select create_booking($1, $2, $3, $4)",
                intent["room_number"], intent["guest_name"], check_in_date, check_out_date,
            )
            await conn.execute(
                "update pending_actions set status = 'confirmed' where id = $1::uuid", payload.action_id
            )
            result = {"status": "success", "booking_id": booking_id}
            await log_audit_event(conn, "staff", action, intent, "success", result=result)
            return result

        elif action == "cancel_booking":
            await conn.fetchval("select cancel_booking($1)", intent["booking_id"])
            await conn.execute(
                "update pending_actions set status = 'confirmed' where id = $1::uuid", payload.action_id
            )
            result = {"status": "success", "cancelled_booking_id": intent["booking_id"]}
            await log_audit_event(conn, "staff", action, intent, "success", result=result)
            return result

        elif action == "add_room":
            room_id = await conn.fetchval(
                "select add_room($1, $2, $3, $4, $5)",
                intent["hotel_name"], intent["room_type_name"], intent["room_number"],
                intent["base_price"], intent["max_occupancy"],
            )
            await conn.execute(
                "update pending_actions set status = 'confirmed' where id = $1::uuid", payload.action_id
            )
            result = {"status": "success", "room_id": room_id}
            await log_audit_event(conn, "staff", action, intent, "success", result=result)
            return result

        elif action == "update_room_type":
            room_type_id = await conn.fetchval(
                "select update_room_type($1, $2, $3, $4, $5)",
                intent["hotel_name"], intent["old_type_name"],
                intent.get("new_type_name"), intent.get("new_price"), intent.get("new_max_occupancy"),
            )
            await conn.execute(
                "update pending_actions set status = 'confirmed' where id = $1::uuid", payload.action_id
            )
            result = {"status": "success", "room_type_id": room_type_id}
            await log_audit_event(conn, "staff", action, intent, "success", result=result)
            return result

        elif action == "record_daily_sale":
            sale_date = datetime.strptime(intent["sale_date"], "%Y-%m-%d").date()
            sale_id = await conn.fetchval(
                "select record_daily_sale($1, $2, $3, $4, $5, $6)",
                intent["hotel_name"], intent["amount"], sale_date,
                intent.get("category"), intent.get("notes"), intent.get("entered_by"),
            )
            await conn.execute(
                "update pending_actions set status = 'confirmed' where id = $1::uuid", payload.action_id
            )
            # Deliberately does NOT return any total/aggregate — staff only
            # gets confirmation that their own entry was recorded.
            result = {"status": "success", "sale_id": sale_id}
            await log_audit_event(conn, "staff", action, intent, "success", result=result)
            return result

    except Exception as e:
        if action:
            await log_audit_event(conn, "staff", action, intent or {}, "error", error_message=str(e))
        return {"error": str(e)}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# HR / salary management — manager key only, fully separate from staff paths
# ---------------------------------------------------------------------------
HR_SCHEMA_DESCRIPTION = """
Tables:
- employees(id, full_name, job_role, hotel_id, hire_date, termination_date, status)
- salary_history(id, employee_id, amount, effective_date)
- payroll_payments(id, employee_id, amount, pay_period_start, pay_period_end, method, paid_at)
- daily_sales(id, hotel_id, sale_date, amount, category, notes, entered_by, created_at)
"""

HR_REQUIRED_FIELDS = {
    "hire_employee": ["full_name", "job_role", "hotel_name", "starting_salary"],
    "terminate_employee": ["employee_id"],
    "update_salary": ["employee_id", "new_salary"],
    "record_payment": ["employee_id", "amount", "period_start", "period_end"],
}


def validate_hr_intent(intent: dict) -> str | None:
    action = intent.get("action")
    if action not in HR_REQUIRED_FIELDS:
        return None
    missing = [f for f in HR_REQUIRED_FIELDS[action] if not intent.get(f)]
    if missing:
        return f"Could not fully understand the '{action}' request — missing: {', '.join(missing)}."
    return None


def extract_hr_action(user_text: str) -> dict:
    prompt = f"""You are an HR assistant for hotel staff management. Given this manager request:
"{user_text}"

Decide which single action applies, and output ONLY valid JSON, nothing else.

{{"action": "hire_employee", "full_name": "Priya Shah", "job_role": "Front Desk", "hotel_name": "Sunrise Hotel", "starting_salary": 25000}}

{{"action": "terminate_employee", "employee_id": 3}}

{{"action": "update_salary", "employee_id": 3, "new_salary": 28000}}

{{"action": "record_payment", "employee_id": 3, "amount": 25000, "period_start": "2026-07-01", "period_end": "2026-07-31"}}

If ambiguous or missing details, respond with:
{{"action": "unknown"}}

Only extract ONE action per request. Output only JSON, no extra prose.
"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    return json.loads(raw)


class HrQuestion(BaseModel):
    question: str


class HrActionRequest(BaseModel):
    text: str


class HrConfirmRequest(BaseModel):
    action_id: str


@app.get("/hr/employees")
async def list_employees(_: None = Depends(require_manager)):
    conn = await get_hr_reader_connection()
    try:
        rows = await conn.fetch("""
            select e.id, e.full_name, e.job_role, h.name as hotel_name,
                   e.hire_date, e.termination_date, e.status,
                   (select amount from salary_history sh
                    where sh.employee_id = e.id
                    order by sh.effective_date desc limit 1) as current_salary
            from employees e
            left join hotels h on e.hotel_id = h.id
            order by e.status, e.full_name;
        """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@app.get("/hr/payroll-status")
async def payroll_status(period_start: str = None, period_end: str = None, _: None = Depends(require_manager)):
    """Shows, for each active employee, their current salary, what's been
    paid for the given period, and whether they're paid/partial/unpaid.
    Defaults to the current calendar month if no period is given."""
    conn = await get_hr_reader_connection()
    try:
        if period_start and period_end:
            start = datetime.strptime(period_start, "%Y-%m-%d").date()
            end = datetime.strptime(period_end, "%Y-%m-%d").date()
        else:
            today = datetime.utcnow().date()
            start = today.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)

        rows = await conn.fetch(
            """
            select
              e.id as employee_id,
              e.full_name,
              e.job_role,
              (select amount from salary_history sh
               where sh.employee_id = e.id
               order by sh.effective_date desc limit 1) as current_salary,
              coalesce((
                select sum(pp.amount) from payroll_payments pp
                where pp.employee_id = e.id
                  and pp.pay_period_start >= $1
                  and pp.pay_period_end <= $2
              ), 0) as paid_amount
            from employees e
            where e.status = 'active'
            order by e.full_name;
            """,
            start, end,
        )

        result = []
        for r in rows:
            salary = float(r["current_salary"] or 0)
            paid = float(r["paid_amount"] or 0)
            if paid <= 0:
                status = "unpaid"
            elif paid < salary:
                status = "partial"
            else:
                status = "paid"
            result.append({
                "employee_id": r["employee_id"],
                "full_name": r["full_name"],
                "job_role": r["job_role"],
                "current_salary": salary,
                "paid_amount": paid,
                "remaining": max(salary - paid, 0),
                "status": status,
            })

        return {
            "period_start": str(start),
            "period_end": str(end),
            "employees": result,
        }
    finally:
        await conn.close()


@app.get("/hr/audit-log")
async def get_audit_log(limit: int = 100, _: None = Depends(require_manager)):
    """Manager-only view of every write action attempted through the agent —
    staff bookings/cancellations/sales and HR changes alike, success or
    failure. Staff can never reach this; agent_readonly has no grant on it."""
    conn = await get_hr_reader_connection()
    try:
        rows = await conn.fetch(
            """
            select id, actor_key, action_type, payload, status, error_message, result, created_at
            from audit_log
            order by created_at desc
            limit $1;
            """,
            limit,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


@app.get("/hr/sales-summary")
async def sales_summary(period_start: str = None, period_end: str = None, _: None = Depends(require_manager)):
    """Manager-only view of daily sales entered by staff. Staff can enter
    sales via /action/record-sale but can never reach this endpoint —
    only the manager key can see totals."""
    conn = await get_hr_reader_connection()
    try:
        if period_start and period_end:
            start = datetime.strptime(period_start, "%Y-%m-%d").date()
            end = datetime.strptime(period_end, "%Y-%m-%d").date()
        else:
            today = datetime.utcnow().date()
            start = today.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)

        total_row = await conn.fetchrow(
            """
            select coalesce(sum(amount), 0) as total, count(*) as entry_count
            from daily_sales
            where sale_date >= $1 and sale_date <= $2;
            """,
            start, end,
        )

        by_hotel = await conn.fetch(
            """
            select h.name as hotel_name, sum(ds.amount) as total
            from daily_sales ds
            join hotels h on ds.hotel_id = h.id
            where ds.sale_date >= $1 and ds.sale_date <= $2
            group by h.name
            order by total desc;
            """,
            start, end,
        )

        entries = await conn.fetch(
            """
            select ds.id, h.name as hotel_name, ds.sale_date, ds.amount,
                   ds.category, ds.notes, ds.entered_by, ds.created_at
            from daily_sales ds
            join hotels h on ds.hotel_id = h.id
            where ds.sale_date >= $1 and ds.sale_date <= $2
            order by ds.sale_date desc, ds.created_at desc;
            """,
            start, end,
        )

        return {
            "period_start": str(start),
            "period_end": str(end),
            "total": float(total_row["total"] or 0),
            "entry_count": total_row["entry_count"],
            "by_hotel": [dict(r) for r in by_hotel],
            "entries": [dict(r) for r in entries],
        }
    finally:
        await conn.close()


@app.post("/hr/ask")
async def hr_ask(payload: HrQuestion, _: None = Depends(require_manager)):
    """Same pattern as /ask, but scoped to employees/salary/payroll only,
    using the HR-only read role so this can never see booking/guest data
    (and /ask can never see salary data)."""
    prompt = f"""You are a PostgreSQL expert. Given this schema:
{HR_SCHEMA_DESCRIPTION}

Write ONE read-only SQL SELECT query that answers this question:
"{payload.question}"

Rules:
- Only output the raw SQL query, nothing else.
- Only use SELECT statements.
"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    sql = clean_sql(response.choices[0].message.content)

    if not is_safe_select(sql):
        return {"error": "Unsafe or invalid query blocked.", "generated_sql": sql}

    conn = await get_hr_reader_connection()
    try:
        rows = await conn.fetch(sql)
    except Exception as e:
        return {"error": str(e), "generated_sql": sql}
    finally:
        await conn.close()

    return {"question": payload.question, "generated_sql": sql, "result": [dict(r) for r in rows]}


class HireForm(BaseModel):
    full_name: str
    job_role: str
    hotel_name: str
    starting_salary: float


class TerminateForm(BaseModel):
    employee_id: int


class SalaryForm(BaseModel):
    employee_id: int
    new_salary: float


class PaymentForm(BaseModel):
    employee_id: int
    amount: float
    period_start: str
    period_end: str


@app.post("/hr/action/hire")
async def form_hire(payload: HireForm, _: None = Depends(require_manager)):
    conn = await get_hr_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "hire_employee", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /hr/action/confirm to execute. Expires in 15 minutes."}


@app.post("/hr/action/terminate")
async def form_terminate(payload: TerminateForm, _: None = Depends(require_manager)):
    conn = await get_hr_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "terminate_employee", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /hr/action/confirm to execute. Expires in 15 minutes."}


@app.post("/hr/action/salary")
async def form_salary(payload: SalaryForm, _: None = Depends(require_manager)):
    conn = await get_hr_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "update_salary", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /hr/action/confirm to execute. Expires in 15 minutes."}


@app.post("/hr/action/payment")
async def form_payment(payload: PaymentForm, _: None = Depends(require_manager)):
    conn = await get_hr_writer_connection()
    try:
        action_id = await queue_pending_action(conn, "record_payment", payload.model_dump())
    finally:
        await conn.close()
    return {"action_id": action_id, "preview": payload.model_dump(),
            "message": "Review and POST to /hr/action/confirm to execute. Expires in 15 minutes."}


@app.post("/hr/action")
async def propose_hr_action(payload: HrActionRequest, _: None = Depends(require_manager)):
    intent = extract_hr_action(payload.text)

    if intent.get("action") not in HR_REQUIRED_FIELDS:
        return {"error": "Could not understand the requested HR action.", "raw": intent}

    validation_error = validate_hr_intent(intent)
    if validation_error:
        return {"error": validation_error, "raw": intent}

    conn = await get_hr_writer_connection()
    try:
        action_id = await conn.fetchval(
            """
            insert into pending_actions (action_type, payload)
            values ($1, $2::jsonb)
            returning id
            """,
            intent["action"], json.dumps(intent),
        )
    finally:
        await conn.close()

    return {
        "action_id": str(action_id),
        "preview": intent,
        "message": "Review and POST to /hr/action/confirm to execute. Expires in 15 minutes.",
    }


@app.post("/hr/action/confirm")
async def confirm_hr_action(payload: HrConfirmRequest, _: None = Depends(require_manager)):
    conn = await get_hr_writer_connection()
    intent, action = None, None
    try:
        row = await conn.fetchrow(
            "select id, action_type, payload, status, expires_at from pending_actions where id = $1::uuid",
            payload.action_id,
        )
        if not row:
            return {"error": "No pending action found for that ID."}
        if row["status"] != "pending":
            return {"error": f"This action was already '{row['status']}' and cannot be run again."}
        if row["expires_at"] < datetime.utcnow().replace(tzinfo=row["expires_at"].tzinfo):
            await conn.execute("update pending_actions set status = 'expired' where id = $1::uuid", payload.action_id)
            return {"error": "This action has expired. Please submit the request again."}

        intent = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        action = row["action_type"]

        if action == "hire_employee":
            employee_id = await conn.fetchval(
                "select hire_employee($1, $2, $3, $4)",
                intent["full_name"], intent["job_role"], intent["hotel_name"], intent["starting_salary"],
            )
            result = {"status": "success", "employee_id": employee_id}

        elif action == "terminate_employee":
            await conn.fetchval("select terminate_employee($1)", intent["employee_id"])
            result = {"status": "success", "terminated_employee_id": intent["employee_id"]}

        elif action == "update_salary":
            history_id = await conn.fetchval(
                "select update_salary($1, $2)", intent["employee_id"], intent["new_salary"]
            )
            result = {"status": "success", "salary_history_id": history_id}

        elif action == "record_payment":
            period_start = datetime.strptime(intent["period_start"], "%Y-%m-%d").date()
            period_end = datetime.strptime(intent["period_end"], "%Y-%m-%d").date()
            payment_id = await conn.fetchval(
                "select record_payment($1, $2, $3, $4)",
                intent["employee_id"], intent["amount"], period_start, period_end,
            )
            result = {"status": "success", "payment_id": payment_id}

        else:
            return {"error": f"Unknown HR action type: {action}"}

        await conn.execute("update pending_actions set status = 'confirmed' where id = $1::uuid", payload.action_id)
        await log_audit_event(conn, "manager", action, intent, "success", result=result)
        return result

    except Exception as e:
        if action:
            await log_audit_event(conn, "manager", action, intent or {}, "error", error_message=str(e))
        return {"error": str(e)}
    finally:
        await conn.close()
