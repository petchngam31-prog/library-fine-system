"""
dashboard.py
============
เว็บแดชบอร์ดอย่างง่ายสำหรับ "เจ้าหน้าที่" ใช้ดูรายการยืม-คืนอุปกรณ์
รายการที่เลยกำหนด ค่าปรับ และสามารถกดปุ่มเพื่อสั่งให้ระบบตรวจสอบ +
ส่งแจ้งเตือน LINE ได้จากหน้าเว็บโดยตรง (ไม่ต้องพิมพ์คำสั่งเอง)

วิธีรัน:
    pip install flask
    python dashboard.py
แล้วเปิดเบราว์เซอร์ไปที่ http://127.0.0.1:5000

หมายเหตุ: นี่คือเว็บสำหรับรันทดสอบในเครื่อง (development server) เท่านั้น
ถ้าจะให้คนอื่นเข้าจากที่อื่นได้ ต้อง deploy ขึ้นเซิร์ฟเวอร์จริง (ดู README
หัวข้อ "การ Deploy ขึ้นใช้งานจริง")
"""

from flask import Flask, render_template_string, redirect, url_for, flash

from db_setup import init_mock_db, get_connection, DB_PATH
from fine_calculator import check_and_update_fines, mark_as_notified, DEFAULT_FINE_RATE_PER_DAY
from line_notify import LineNotifier
import os

app = Flask(__name__)
# อ่าน secret key จาก environment variable ก่อนเสมอ (สำคัญสำหรับ production)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this-in-production")

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>แดชบอร์ดระบบยืม-คืนอุปกรณ์</title>
<style>
  :root { color-scheme: light; }
  body { font-family: "Segoe UI", "Sarabun", sans-serif; background:#f4f5f7; margin:0; padding:2rem; color:#1f2430; }
  h1 { font-size:1.5rem; margin-bottom:0.25rem; }
  .subtitle { color:#6b7280; margin-bottom:1.5rem; }
  .cards { display:flex; gap:1rem; margin-bottom:1.5rem; flex-wrap:wrap; }
  .card { background:#fff; border-radius:10px; padding:1rem 1.5rem; box-shadow:0 1px 3px rgba(0,0,0,.08); min-width:160px; }
  .card .num { font-size:1.6rem; font-weight:700; }
  .card .label { color:#6b7280; font-size:0.85rem; }
  table { width:100%; border-collapse:collapse; background:#fff; border-radius:10px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.08); }
  th, td { padding:0.7rem 1rem; text-align:left; border-bottom:1px solid #eee; font-size:0.92rem; }
  th { background:#eef1f6; color:#374151; }
  tr.overdue { background:#fff6f6; }
  .badge { display:inline-block; padding:0.15rem 0.6rem; border-radius:999px; font-size:0.78rem; font-weight:600; }
  .badge.overdue { background:#fde2e2; color:#b42318; }
  .badge.ok { background:#e3f7e7; color:#15803d; }
  .badge.notified { background:#e0ecff; color:#1d4ed8; margin-left:0.3rem; }
  button, .btn { background:#2563eb; color:#fff; border:none; padding:0.6rem 1.1rem; border-radius:8px; cursor:pointer; font-size:0.9rem; text-decoration:none; display:inline-block; }
  button:hover, .btn:hover { background:#1d4ed8; }
  .flash { background:#e0ecff; color:#1d4ed8; padding:0.7rem 1rem; border-radius:8px; margin-bottom:1rem; }
  .actions { margin-bottom:1.5rem; }
</style>
</head>
<body>
  <h1>📋 แดชบอร์ดระบบยืม-คืนอุปกรณ์</h1>
  <p class="subtitle">คณะวิทยาการสื่อสาร &mdash; โมดูลแจ้งเตือนและติดตามการคืนอุปกรณ์ (ข้อมูลจำลอง)</p>

  {% with messages = get_flashed_messages() %}
    {% if messages %}
      {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
    {% endif %}
  {% endwith %}

  <div class="cards">
    <div class="card"><div class="num">{{ overdue_count }}</div><div class="label">รายการเลยกำหนด</div></div>
    <div class="card"><div class="num">{{ "{:,.0f}".format(total_fine) }} ฿</div><div class="label">ยอดค่าปรับรวม</div></div>
    <div class="card"><div class="num">{{ total_records }}</div><div class="label">รายการยืมทั้งหมด</div></div>
  </div>

  <div class="actions">
    <form method="POST" action="{{ url_for('run_check') }}" style="display:inline">
      <button type="submit">🔍 ตรวจสอบวันคืน + ส่งแจ้งเตือน LINE ตอนนี้</button>
    </form>
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th><th>ผู้ยืม</th><th>อุปกรณ์</th><th>กำหนดคืน</th><th>วันคืนจริง</th>
        <th>สถานะ</th><th>ค่าปรับ</th>
      </tr>
    </thead>
    <tbody>
      {% for r in records %}
      <tr class="{{ 'overdue' if r.is_overdue else '' }}">
        <td>{{ r.record_id }}</td>
        <td>{{ r.full_name }}</td>
        <td>{{ r.equipment_name }}</td>
        <td>{{ r.due_date }}</td>
        <td>{{ r.return_date or '—' }}</td>
        <td>
          {% if r.return_date %}
            <span class="badge ok">คืนแล้ว</span>
          {% elif r.is_overdue %}
            <span class="badge overdue">เลยกำหนด</span>
            {% if r.notified %}<span class="badge notified">แจ้งเตือนแล้ว</span>{% endif %}
          {% else %}
            <span class="badge ok">ยังไม่ถึงกำหนด</span>
          {% endif %}
        </td>
        <td>{{ "{:,.0f}".format(r.fine_amount) }} บาท</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <p style="margin-top:1.5rem; color:#9ca3af; font-size:0.8rem;">
    อัตราค่าปรับ: {{ rate }} บาท/วัน &middot; โหมดแจ้งเตือน: dry-run (จำลองการส่ง ยังไม่ผูก LINE token จริง)
  </p>
</body>
</html>
"""


def ensure_db():
    """ถ้ายังไม่มีไฟล์ฐานข้อมูล ให้สร้างจำลองขึ้นมาก่อนครั้งแรก"""
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

    # เช็ก overdue แบบ real-time เพิ่มเติม (เผื่อยังไม่เคยกดปุ่มตรวจสอบ)
    from fine_calculator import calculate_fine
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

    # ถ้ามีการตั้งค่า LINE_CHANNEL_TOKEN ไว้ใน environment variable จะส่งข้อความจริง
    # ถ้าไม่มี จะเป็น dry-run (จำลองการส่ง) โดยอัตโนมัติ
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


if __name__ == "__main__":
    ensure_db()
    # PORT: บริการโฮสติ้งอย่าง Render จะกำหนด environment variable นี้มาให้เอง
    # DEBUG=1: ตั้งค่านี้เฉพาะตอนพัฒนาในเครื่องตัวเอง ห้ามเปิดตอนใช้งานจริง (ไม่ปลอดภัย)
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("DEBUG", "0") == "1"
    host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    app.run(debug=debug_mode, host=host, port=port)
