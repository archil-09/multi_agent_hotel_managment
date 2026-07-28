from groq import Groq
import os
from dotenv import load_dotenv
load_dotenv()
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
    sql = response.choices[0].message.content.strip()
    return sql




def is_safe_select(sql: str) -> bool:
    sql_clean = sql.strip().rstrip(";")
    if ";" in sql_clean:
        return False  # multiple statements = reject
    lowered = sql_clean.lower()
    if not lowered.startswith("select"):
        return False
    banned = ["insert", "update", "delete", "drop", "alter", "truncate", "grant"]
    return not any(word in lowered for word in banned)


import json

def extract_action(user_text: str) -> dict:
    prompt = f"""You are a hotel booking assistant. Given this user request:
"{user_text}"

Decide which single action applies, and output ONLY valid JSON, nothing else:

{{"action": "create_booking", "room_number": "101", "guest_name": "John Doe", "check_in": "2026-07-10", "check_out": "2026-07-12"}}

or

{{"action": "cancel_booking", "booking_id": 5}}

or if unclear:

{{"action": "unknown"}}
"""
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    return json.loads(raw)
