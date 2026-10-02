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

LINE_CHANNEL_SECRET = "901bf8bf3b7a8708acaa61a9d6fd25b7"
LINE_CHANNEL_TOKEN = "pAregB0v0D4C3XTPFn5eXj3bJnwdl9NAgIvBZZW48v/V7CM3BZARCeejXeocIZWaNXREAFxWU4oaFbN5g4PCAwBTwHhw3V1JpVlcCGK61iKmQq49ZDN0P/2optvr04xyGGNAl82SiKkOBBMwe4YYlgdB04t89/1O/w1cDnyilFU="

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

    line_token = os.environ.get("LINE_CHANNEL_TOKEN") or LINE_CHANNEL_TOKEN
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

from flask import request, jsonify
from db_setup import get_connection  # เรียกใช้ฟังก์ชันเชื่อมต่อฐานข้อมูลจากไฟล์ db_setup.py

# 1. API สำหรับผูกบัญชี LINE
@app.route('/line/link', methods=['POST'])
def line_link():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid or missing JSON body"}), 400
        
    user_id = data.get('user_id')         # รหัสประจำตัวนักศึกษา (เช่น '6412345001')
    line_user_id = data.get('line_user_id') # LINE userId (เช่น 'Uxxxxxxxxxxxx')
    
    if not user_id or not line_user_id:
        return jsonify({"success": False, "message": "Missing user_id or line_user_id"}), 400
        
    conn = get_connection()
    try:
        # เช็กว่ามีรหัสผู้ใช้นี้อยู่ในตาราง users หรือไม่ (เทียบกับ student_id)
        user = conn.execute("SELECT * FROM users WHERE student_id = ?", (user_id,)).fetchone()
        if not user:
            return jsonify({"success": False, "message": "ไม่พบรหัสผู้ใช้ในระบบ"}), 400
            
        # เช็กว่า line_user_id นี้ถูกผูกกับคนอื่นไปแล้วหรือยัง
        existing_line = conn.execute(
            "SELECT * FROM users WHERE line_user_id = ? AND student_id != ?", 
            (line_user_id, user_id)
        ).fetchone()
        
        if existing_line:
            return jsonify({"success": False, "message": "LINE บัญชีนี้ถูกเชื่อมต่อกับผู้ใช้อื่นแล้ว"}), 400
            
        # บันทึก / อัปเดต line_user_id ลงในฐานข้อมูล
        conn.execute(
            "UPDATE users SET line_user_id = ? WHERE student_id = ?", 
            (line_user_id, user_id)
        )
        conn.commit()
        
        return jsonify({"success": True, "message": "เชื่อมต่อ LINE สำเร็จ"}), 200
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()


# 2. API สำหรับตรวจสอบสถานะการผูก LINE
@app.route('/line/status', methods=['GET'])
def line_status():
    user_id = request.args.get('user_id') # รับค่าผ่าน Query Parameter เช่น /line/status?user_id=6412345001
    
    if not user_id:
        return jsonify({"linked": False, "message": "Missing user_id parameter"}), 400
        
    conn = get_connection()
    try:
        user = conn.execute("SELECT line_user_id FROM users WHERE student_id = ?", (user_id,)).fetchone()
        
        # ถ้าพบข้อมูลและมี line_user_id บันทึกไว้แล้ว
        if user and user['line_user_id']:
            return jsonify({
                "linked": True,
                "line_user_id": user['line_user_id']
            }), 200
        else:
            return jsonify({
                "linked": False,
                "line_user_id": None
            }), 200
            
    finally:
        conn.close()


# 3. API สำหรับรับ LINE userId (เชื่อมโยงกับหน้า /line-mapping)
@app.route('/line-mapping', methods=['GET'])
def line_mapping():
    # รับค่า userId ที่ส่งมาจาก LINE OA (เช่น /line-mapping?userId=Uxxxxxxxxxxxx)
    line_user_id = request.args.get('userId')
    
    # ส่งค่า line_user_id กลับไปให้ Front-end
    return jsonify({
        "status": "success",
        "line_user_id": line_user_id,
        "message": "Ready for LINE account mapping"
    }), 200


@app.route('/book', methods=['GET', 'POST'])
def handle_booking():
    if request.method == 'POST':
        user_id = request.form['user_id']
        equipment_id = request.form['equipment_id']
        borrow_date = request.form['start_date']
        due_date = request.form['end_date']

        conn = get_connection()
        cursor = conn.cursor()

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
        ''', (equipment_id, due_date, borrow_date))

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

        # 🔑 กำหนด LINE User ID ของเจ้าหน้าที่ (Admin) สำหรับทดสอบสั่งการผ่านแชท
        ADMIN_LINE_IDS = ["Ubd5423c296e823b727c730f0e844b271"]

        for event in events:
            print(">>> LINE User ID ของคุณคือ:", event.get('source', {}).get('userId'), flush=True)
            event_type = event.get('type')

            # --- กรณีที่ 1: ผู้ใช้กดเพิ่มเพื่อน (Follow) ---
            if event_type == 'follow':
                line_user_id = event.get('source', {}).get('userId')
                if line_user_id:
                    ensure_db()
                    conn = get_connection()
                    cursor = conn.cursor()
                    existing = cursor.execute(
                        "SELECT user_id FROM users WHERE line_user_id = ?",
                        (line_user_id,),
                    ).fetchone()
                    if not existing:
                        cursor.execute(
                            """
                            INSERT INTO users (full_name, student_id, role, line_user_id)
                            VALUES (?, NULL, 'unlinked', ?)
                            """,
                            ("ผู้ใช้รอผูกข้อมูล (LINE)", line_user_id),
                        )
                        conn.commit()
                    conn.close()

            # --- กรณีที่ 2: มีข้อความส่งเข้ามาในแชท (รองรับคำสั่งแอดมิน) ---
            elif event_type == 'message':
                message = event.get('message', {})
                if message.get('type') == 'text':
                    user_line_id = event.get('source', {}).get('userId')
                    text_command = message.get('text').strip()

                    # ตรวจสอบสิทธิ์ว่าเป็นแอดมินหรือไม่
                    if user_line_id in ADMIN_LINE_IDS:
                        line_token = os.environ.get("LINE_CHANNEL_TOKEN") or LINE_CHANNEL_TOKEN
                        notifier = LineNotifier(channel_access_token=line_token, dry_run=not bool(line_token))

                        # คำสั่งขอสรุปยอดด่วน
                        if text_command == "สรุปยอด" or text_command == "/summary":
                            ensure_db()
                            conn = get_connection()
                            total_records = conn.execute("SELECT COUNT(*) FROM borrow_records").fetchone()[0]
                            total_fine = conn.execute("SELECT SUM(fine_amount) FROM borrow_records").fetchone()[0] or 0.0
                            conn.close()

                            reply_message = (
                                f"📊 [รายงานด่วนสำหรับแอดมิน]\n"
                                f"----------------------------------\n"
                                f"📌 จำนวนการยืมทั้งหมด: {total_records} รายการ\n"
                                f"💰 ยอดค่าปรับค้างจ่ายรวม: {total_fine} บาท\n"
                                f"สถานะระบบ: ปกติ ✅"
                            )
                            notifier.send(user_line_id, reply_message)

    except Exception as e:
        print(f"Webhook Error: {e}")

    return 'OK', 200


if __name__ == "__main__":
    ensure_db()
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("DEBUG", "0") == "1"
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(debug=debug_mode, host=host, port=port)