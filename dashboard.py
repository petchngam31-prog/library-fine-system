"""
dashboard.py
============
ระบบยืม-คืนอุปกรณ์กล้อง สำหรับเจ้าหน้าที่และนักศึกษา
"""

import base64
import hashlib
import hmac
import json
import os
from datetime import date, datetime
from functools import wraps

from flask import Flask, render_template, render_template_string, request, jsonify, abort, redirect, url_for, flash, session

from db_setup import init_mock_db, get_connection, DB_PATH
from fine_calculator import check_and_update_fines, mark_as_notified, DEFAULT_FINE_RATE_PER_DAY, calculate_fine
from line_notify import LineNotifier
from eligibility_checker import check_eligibility

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-1234")
ADMIN_PASSWORD = "admin1234"  # 🔑 รหัสผ่านเข้าแดชบอร์ดเจ้าหน้าที่

LINE_CHANNEL_SECRET = "901bf8bf3b7a8708acaa61a9d6fd25b7"
LINE_CHANNEL_TOKEN = "pAregB0v0D4C3XTPFn5eXj3bJnwdl9NAgIvBZZW48v/V7CM3BZARCeejXeocIZWaNXREAFxWU4oaFbN5g4PCAwBTwHhw3V1JpVlcCGK61iKmQq49ZDN0P/2optvr04xyGGNAl82SiKkOBBMwe4YYlgdB04t89/1O/w1cDnyilFU="


# ตัวดักสิทธิ์: ถ้ายังไม่ล็อกอิน ห้ามเรียกใช้ API เจ้าหน้าที่
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"message": "Unauthorized: กรุณาเข้าสู่ระบบก่อนใช้งาน"}), 401
        return f(*args, **kwargs)
    return decorated_function


def ensure_db():
    if not os.path.exists(DB_PATH):
        conn = init_mock_db()
        conn.close()


# -------------------------------------------------------------
# 1. หน้าแสดงผล HTML
# -------------------------------------------------------------
# -------------------------------------------------------------
# 1. หน้าแสดงผล HTML
# -------------------------------------------------------------

# 1) กำหนดให้หน้าแรกสุดเมื่อเปิดเว็บ (http://127.0.0.1:5000/) เป็นหน้าเลือก/จองกล้อง
@app.route("/")
@app.route("/booking.html")
@app.route("/booking")
def booking_page():
    return render_template("booking.html")


# 2) หน้าแดชบอร์ดเจ้าหน้าที่ (ย้ายไปที่ /admin หรือ /index.html ต้องใส่รหัสผ่าน)
@app.route("/admin", methods=["GET", "POST"])
@app.route("/index.html", methods=["GET", "POST"])
def index_page():
    if request.method == "POST":
        pwd = request.form.get("password", "").strip()
        if pwd == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("index_page"))
        else:
            flash("รหัสผ่านไม่ถูกต้อง!")

    if session.get("is_admin"):
        return render_template("index.html")

    login_template = """
    <!DOCTYPE html>
    <html lang="th">
    <head>
      <meta charset="UTF-8">
      <title>เข้าสู่ระบบเจ้าหน้าที่ | ยืมคืนกล้อง</title>
      <link rel="stylesheet" href="/static/style.css">
      <style>
        body { display: grid; place-items: center; min-height: 100vh; background: #f5f6fa; font-family: sans-serif; }
        .login-box { background: #fff; padding: 36px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); width: 100%; max-width: 380px; text-align: center; }
        .login-box h2 { margin-bottom: 8px; color: #1b2a5e; }
        .login-box p { color: #5d6585; font-size: 14px; margin-bottom: 24px; }
        .login-box input { width: 100%; padding: 12px 14px; border: 1px solid #dfe3ee; border-radius: 10px; margin-bottom: 16px; font-size: 15px; box-sizing: border-box; }
        .login-box input:focus { outline: none; border-color: #1b2a5e; }
        .alert { background: #fde2e0; color: #b3261e; padding: 10px; border-radius: 8px; font-size: 14px; margin-bottom: 16px; }
      </style>
    </head>
    <body>
      <div class="login-box">
        <h2>🔒 เข้าสู่ระบบเจ้าหน้าที่</h2>
        <p>ยืมคืนกล้อง — สำหรับเจ้าหน้าที่ดูแลระบบ</p>
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <div class="alert">{{ messages[0] }}</div>
          {% endif %}
        {% endwith %}
        <form method="POST">
          <input type="password" name="password" placeholder="กรอกรหัสผ่านเจ้าหน้าที่" required autofocus>
          <button type="submit" class="btn btn-amber btn-block">เข้าสู่ระบบ</button>
        </form>
      </div>
    </body>
    </html>
    """
    return render_template_string(login_template)


@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    return redirect(url_for("index_page"))





@app.route("/history.html")
@app.route("/history")
def history_page():
    return render_template("history.html")


@app.route('/line-mapping', methods=['GET'])
def line_mapping():
    return render_template("line_mapping.html")


# -------------------------------------------------------------
# 2. REST API Endpoints ( JSON )
# -------------------------------------------------------------

# API ดึงรายการประวัติยืม-คืนทั้งหมด (สำหรับหน้าแดชบอร์ดเจ้าหน้าที่)
@app.route("/api/records", methods=["GET"])
@admin_required
def api_records():
    ensure_db()
    conn = get_connection()
    rows = conn.execute("""
        SELECT br.record_id, br.borrow_date, br.due_date, br.return_date, 
               br.fine_amount, br.notified, br.user_id,
               u.full_name, u.student_id, e.equipment_name
        FROM borrow_records br
        JOIN users u ON u.user_id = br.user_id
        JOIN equipment e ON e.equipment_id = br.equipment_id
        ORDER BY br.record_id DESC
    """).fetchall()
    
    records = []
    for r in rows:
        d = dict(r)
        if d["return_date"] is None:
            res = calculate_fine(d["due_date"])
            d["is_overdue"] = res["is_overdue"]
            d["fine_amount"] = res["fine_amount"]
        else:
            d["is_overdue"] = False
        records.append(d)
    conn.close()
    return jsonify({"records": records}), 200


# API รับคืนอุปกรณ์
@app.route("/api/return/<int:record_id>", methods=["POST"])
@admin_required
def api_return(record_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT due_date FROM borrow_records WHERE record_id = ?', (record_id,))
    record = cursor.fetchone()
    if not record:
        conn.close()
        return jsonify({"message": "ไม่พบรายการยืมนี้"}), 404

    current_date_str = date.today().isoformat()
    result = calculate_fine(due_date=record['due_date'], return_date=current_date_str)
    fine_amount = result["fine_amount"]

    cursor.execute('''
        UPDATE borrow_records 
        SET return_date = ?, fine_amount = ?
        WHERE record_id = ?
    ''', (current_date_str, fine_amount, record_id))
    conn.commit()
    conn.close()
    return jsonify({
        "message": "รับคืนอุปกรณ์สำเร็จ",
        "fine_amount": fine_amount,
        "days_late": result.get("days_late", 0)
    }), 200


# API ตรวจสอบค่าปรับและส่ง LINE แจ้งเตือน
@app.route("/api/check", methods=["POST"])
@admin_required
def api_check():
    ensure_db()
    conn = get_connection()
    overdue_list = check_and_update_fines(conn, rate_per_day=DEFAULT_FINE_RATE_PER_DAY)
    line_token = os.environ.get("LINE_CHANNEL_TOKEN") or LINE_CHANNEL_TOKEN
    notifier = LineNotifier(channel_access_token=line_token, dry_run=not bool(line_token))
    
    sent = 0
    for item in overdue_list:
        if item.get("line_user_id"):
            msg = notifier.build_overdue_message(
                full_name=item["full_name"],
                equipment_name=item["equipment_name"],
                due_date=item["due_date"],
                days_late=item["days_late"],
                fine_amount=item["fine_amount"],
            )
            res = notifier.send(item["line_user_id"], msg)
            if res.success:
                mark_as_notified(conn, item["record_id"])
                sent += 1
    conn.close()
    return jsonify({"overdue_count": len(overdue_list), "notified_count": sent}), 200


# API รับการจองจากหน้า booking.html (รองรับทั้งรหัสนักศึกษาและ user_id)
@app.route("/api/book", methods=["POST"])
def api_book():
    data = request.get_json() or {}
    user_input = str(data.get("user_id", "")).strip()
    equipment_id = data.get("equipment_id")
    borrow_date = data.get("start_date")
    due_date = data.get("end_date")

    if not user_input or not equipment_id or not borrow_date or not due_date:
        return jsonify({"message": "กรุณากรอกข้อมูลให้ครบถ้วน"}), 400

    conn = get_connection()
    cursor = conn.cursor()

    try:
        user = cursor.execute("""
            SELECT user_id FROM users 
            WHERE student_id = ? OR user_id = ?
        """, (user_input, user_input)).fetchone()

        if user:
            internal_user_id = user["user_id"]
        else:
            cursor.execute("""
                INSERT INTO users (full_name, student_id, role)
                VALUES (?, ?, 'student')
            """, (f"นักศึกษา ({user_input})", user_input))
            conn.commit()
            internal_user_id = cursor.lastrowid

        eligibility = check_eligibility(conn, internal_user_id)
        if not eligibility["eligible"]:
            conn.close()
            return jsonify({"message": "ไม่สามารถยืมอุปกรณ์ได้", "reasons": eligibility["reasons"]}), 400

        cursor.execute('''
            SELECT * FROM borrow_records 
            WHERE equipment_id = ? 
            AND return_date IS NULL
            AND (borrow_date <= ? AND due_date >= ?)
        ''', (equipment_id, due_date, borrow_date))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({"message": "อุปกรณ์นี้ถูกยืมหรือจองในช่วงเวลาดังกล่าวแล้ว"}), 400

        cursor.execute('''
            INSERT INTO borrow_records (user_id, equipment_id, borrow_date, due_date, return_date, fine_amount, fine_paid, notified)
            VALUES (?, ?, ?, ?, NULL, 0.0, 0, 0)
        ''', (internal_user_id, equipment_id, borrow_date, due_date))
        
        conn.commit()
        conn.close()
        return jsonify({"message": "บันทึกการจองสำเร็จ"}), 200

    except Exception as e:
        conn.close()
        print(f"Booking Error: {e}")
        return jsonify({"message": f"เกิดข้อผิดพลาดภายในเซิร์ฟเวอร์: {str(e)}"}), 500


# API ส่งรายชื่ออุปกรณ์ยืม-คืนกล้อง ให้ตรงกับรูปถ่ายและชื่อจริง
@app.route("/api/equipment", methods=["GET"])
def api_equipment():
    equipment_list = [
        {"equipment_id": 1, "equipment_name": "กล้อง Canon EOS R50", "category": "camera", "status": "available"},
        {"equipment_id": 2, "equipment_name": "ขาตั้งกล้อง Fancier", "category": "tripod", "status": "available"},
        {"equipment_id": 3, "equipment_name": "กล้องภาพนิ่ง Nikon D3300", "category": "camera", "status": "available"},
        {"equipment_id": 4, "equipment_name": "กล้องภาพนิ่ง Canon EOS 700D", "category": "camera", "status": "available"},
        {"equipment_id": 5, "equipment_name": "กล้องดิจิตอลวิดีโอ Panasonic HC-V700", "category": "video", "status": "available"},
        {"equipment_id": 6, "equipment_name": "ขาตั้งกล้อง Sony", "category": "tripod", "status": "available"}
    ]
    return jsonify({"equipment": equipment_list}), 200


# -------------------------------------------------------------
# 3. LINE Bot & Integration APIs
# -------------------------------------------------------------

@app.route('/line/link', methods=['POST'])
def line_link():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid or missing JSON body"}), 400
        
    user_id = data.get('user_id')
    line_user_id = data.get('line_user_id')
    
    if not user_id or not line_user_id:
        return jsonify({"success": False, "message": "Missing user_id or line_user_id"}), 400
        
    conn = get_connection()
    try:
        user = conn.execute("SELECT * FROM users WHERE student_id = ?", (user_id,)).fetchone()
        if not user:
            return jsonify({"success": False, "message": "ไม่พบรหัสผู้ใช้ในระบบ"}), 400
            
        existing_line = conn.execute(
            "SELECT * FROM users WHERE line_user_id = ? AND student_id != ?", 
            (line_user_id, user_id)
        ).fetchone()
        
        if existing_line:
            return jsonify({"success": False, "message": "LINE บัญชีนี้ถูกเชื่อมต่อกับผู้ใช้อื่นแล้ว"}), 400
            
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


@app.route('/line/status', methods=['GET'])
def line_status():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"linked": False, "message": "Missing user_id parameter"}), 400
        
    conn = get_connection()
    try:
        user = conn.execute("SELECT line_user_id FROM users WHERE student_id = ?", (user_id,)).fetchone()
        if user and user['line_user_id']:
            return jsonify({"linked": True, "line_user_id": user['line_user_id']}), 200
        else:
            return jsonify({"linked": False, "line_user_id": None}), 200
    finally:
        conn.close()


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
        ADMIN_LINE_IDS = ["Ubd5423c296e823b727c730f0e844b271"]

        for event in events:
            event_type = event.get('type')
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

            elif event_type == 'message':
                message = event.get('message', {})
                if message.get('type') == 'text':
                    user_line_id = event.get('source', {}).get('userId')
                    text_command = message.get('text').strip()

                    if user_line_id in ADMIN_LINE_IDS:
                        line_token = os.environ.get("LINE_CHANNEL_TOKEN") or LINE_CHANNEL_TOKEN
                        notifier = LineNotifier(channel_access_token=line_token, dry_run=not bool(line_token))

                        if text_command in ["สรุปยอด", "/summary"]:
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