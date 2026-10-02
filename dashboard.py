"""
dashboard.py
============
เว็บแดชบอร์ดอย่างง่ายสำหรับ "เจ้าหน้าที่" ใช้ดูรายการยืม-คืนอุปกรณ์
รายการที่เลยกำหนด ค่าปรับ และสามารถกดปุ่มเพื่อสั่งให้ระบบตรวจสอบ +
ส่งแจ้งเตือน LINE ได้จากหน้าเว็บโดยตรง พร้อมระบบจองและคืนอุปกรณ์
"""

import base64
import hashlib
import hmac
import json
import os
from datetime import date, datetime
import sqlite3
from flask import Flask, render_template_string, redirect, url_for, flash, request, abort

from db_setup import init_mock_db, get_connection, DB_PATH
from fine_calculator import check_and_update_fines, mark_as_notified, DEFAULT_FINE_RATE_PER_DAY, calculate_fine
from line_notify import LineNotifier
from eligibility_checker import check_eligibility

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this-in-production")

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>แดชบอร์ดระบบยืม-คืนอุปกรณ์</title>
</head>
<body>
<p>placeholder</p>
</body>
</html>
"""


def ensure_db():
    if not os.path.exists(DB_PATH):
        conn = init_mock_db()
        conn.close()


@app.route("/")
def index():
    ensure_db()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT br.record_id, br.due_date, br.return_date, br.fine_amount, br.notified,
               u.full_name, e.equipment_name
        FROM borrow_records br
        JOIN users u ON u.user_id = br.user_id
        JOIN equipment e ON e.equipment_id = br.equipment_id
        ORDER BY br.record_id
        """
    ).fetchall()

    records = []
    for r in rows:
        d = dict(r)
        d["is_overdue"] = (d["return_date"] is None) and (d["fine_amount"] > 0 or False)
        records.append(d)

    for d in records:
        if d["return_date"] is None:
            result = calculate_fine(d["due_date"])
            d["is_overdue"] = result["is_overdue"]

    overdue_count = sum(1 for r in records if r["is_overdue"] and not r["return_date"])
    total_fine = sum(r["fine_amount"] for r in records)
    conn.close()

    return render_template_string(
        PAGE_TEMPLATE,
        records=records,
        overdue_count=overdue_count,
        total_fine=total_fine,
        total_records=len(records),
        rate=DEFAULT_FINE_RATE_PER_DAY,
    )


@app.route("/check", methods=["POST"])
def run_check():
    ensure_db()
    conn = get_connection()
    overdue_list = check_and_update_fines(conn, rate_per_day=DEFAULT_FINE_RATE_PER_DAY)

    line_token = os.environ.get("LINE_CHANNEL_TOKEN")
    notifier = LineNotifier(channel_access_token=line_token, dry_run=not bool(line_token))
    sent = 0
    for item in overdue_list:
        message = notifier.build_overdue_message(
            full_name=item["full_name"],
            equipment_name=item["equipment_name"],
            due_date=item["due_date"],
            days_late=item["days_late"],
            fine_amount=item["fine_amount"],
        )
        result = notifier.send(item["line_user_id"], message)
        if result.success:
            mark_as_notified(conn, item["record_id"])
            sent += 1
    conn.close()

    flash(f"ตรวจสอบเสร็จสิ้น: พบรายการเลยกำหนด {len(overdue_list)} รายการ ส่งแจ้งเตือนสำเร็จ {sent} รายการ")
    return redirect(url_for("index"))


@app.route('/book', methods=['GET', 'POST'])
def handle_booking():
    if request.method == 'POST':
        user_id = request.form['user_id']
        equipment_id = request.form['equipment_id']
        borrow_date = request.form['start_date']
        due_date = request.form['end_date']

        conn = get_connection()
        cursor = conn.cursor()

        # ด่านที่ 1: ตรวจสอบสิทธิ์ ใช้โมดูลกลาง eligibility_checker.py
        # (เช็กครบทั้งของค้างคืนที่ยังเลยกำหนด และค่าปรับค้างจ่าย ไม่ใช่แค่ค่าปรับอย่างเดียว)
        eligibility = check_eligibility(conn, user_id)
        if not eligibility["eligible"]:
            conn.close()
            reasons_text = " / ".join(eligibility["reasons"])
            return f"❌ ขออภัย! ไม่สามารถยืมอุปกรณ์ใหม่ได้: {reasons_text}"

        cursor.execute('''
            SELECT * FROM borrow_records 
            WHERE equipment_id = ? 
            AND return_date IS NULL
            AND (borrow_date <= ? AND due_date >= ?)
        ''', (equipment_id, due_date, borrow_date))  # ด่านที่ 2: เช็กการจองซ้ำ (overlap check)

        existing = cursor.fetchone()

        if existing:
            conn.close()
            return "❌ ขออภัย! อุปกรณ์ชิ้นนี้ถูกยืมหรือจองในช่วงเวลาดังกล่าวแล้ว"

        cursor.execute('''
            INSERT INTO borrow_records (user_id, equipment_id, borrow_date, due_date, return_date, fine_amount, fine_paid, notified)
            VALUES (?, ?, ?, ?, NULL, 0.0, 0, 0)
        ''', (user_id, equipment_id, borrow_date, due_date))

        conn.commit()
        conn.close()

        return "✅ ตรวจสอบสิทธิ์ผ่านและจองอุปกรณ์สำเร็จเรียบร้อยแล้ว!"

    return "🚧 หน้าฟอร์มจองกำลังพัฒนาโดย Front-end (หลังบ้านพร้อมรับข้อมูลแล้ว)"


@app.route('/return/<int:record_id>', methods=['GET', 'POST'])
def return_equipment(record_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT due_date FROM borrow_records WHERE record_id = ?', (record_id,))
    record = cursor.fetchone()

    if not record:
        conn.close()
        return "❌ ไม่พบรายการยืมนี้ในระบบ"

    due_date_str = record['due_date']
    current_date_str = date.today().isoformat()

    # ใช้ calculate_fine() จาก fine_calculator.py แทนการคำนวณเอง
    # (จุดเดียวที่กำหนดสูตรและอัตราค่าปรับ ไม่ซ้ำซ้อน ไม่ต้องแก้หลายที่ถ้าอัตราเปลี่ยน)
    result = calculate_fine(
        due_date=due_date_str,
        return_date=current_date_str,
        rate_per_day=DEFAULT_FINE_RATE_PER_DAY,
    )
    fine_amount = result["fine_amount"]

    cursor.execute('''
        UPDATE borrow_records 
        SET return_date = ?, fine_amount = ?
        WHERE record_id = ?
    ''', (current_date_str, fine_amount, record_id))

    conn.commit()
    conn.close()

    return f"✅ บันทึกการคืนอุปกรณ์ (รายการที่ {record_id}) สำเร็จ! (ยอดค่าปรับ: {fine_amount} บาท)"


@app.route('/webhook', methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    if LINE_CHANNEL_SECRET:
        hash = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'),
                        body.encode('utf-8'),
                        hashlib.sha256).digest()
        computed_signature = base64.b64encode(hash).decode('utf-8')

        if not hmac.compare_digest(computed_signature, signature):
            abort(400)

    try:
        data = json.loads(body)
        events = data.get('events', [])

        for event in events:
            if event.get('type') == 'follow':
                line_user_id = event.get('source', {}).get('userId')
                if line_user_id:
                    ensure_db()
                    conn = get_connection()
                    cursor = conn.cursor()
                    # เช็กก่อนว่า line_user_id นี้เคยถูกบันทึกไว้แล้วหรือยัง (กันซ้ำ)
                    existing = cursor.execute(
                        "SELECT user_id FROM users WHERE line_user_id = ?",
                        (line_user_id,),
                    ).fetchone()
                    if not existing:
                        # follow event ของ LINE ไม่มีข้อมูลว่าเป็นนักศึกษาคนไหน
                        # จึงสร้างเป็น "ผู้ใช้รอผูกข้อมูล" ไว้ก่อน ให้เจ้าหน้าที่
                        # ไปจับคู่กับนักศึกษาจริงทีหลัง (เช่น ผ่านรหัสนักศึกษา)
                        cursor.execute(
                            """
                            INSERT INTO users (full_name, student_id, role, line_user_id)
                            VALUES (?, NULL, 'unlinked', ?)
                            """,
                            ("ผู้ใช้รอผูกข้อมูล (LINE)", line_user_id),
                        )
                        conn.commit()
                    conn.close()
    except Exception as e:
        print(f"Webhook Error: {e}")

    return 'OK', 200


if __name__ == "__main__":
    ensure_db()
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("DEBUG", "0") == "1"
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(debug=debug_mode, host=host, port=port)