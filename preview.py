"""
preview.py — เซิร์ฟเวอร์จำลองสำหรับทดสอบหน้าเว็บ (ไม่ต้องใช้ Backend ของเพื่อน)
ข้อมูลเก็บในหน่วยความจำ รีเซ็ตทุกครั้งที่รันใหม่ ไม่ได้บันทึกลงฐานข้อมูลจริง
รัน:  python3 preview.py   แล้วเปิด http://127.0.0.1:5001
"""
from datetime import date
from flask import Flask, render_template, request, flash, redirect

app = Flask(__name__)
app.secret_key = "preview"

FINE_PER_DAY = 50  # ค่าปรับต่อวัน (จำลอง)

EQUIPMENT = {
    1: "กล้อง Canon EOS R50",
    2: "กล้องภาพนิ่ง Nikon 3300",
    3: "ขาตั้งกล้อง Sony",
    4: "กล้องภาพนิ่ง Canon 700D",
    5: "กล้องดิจิตอลวีดีโอ Panasonic HC-V700",
    6: "ขาตั้งกล้อง Fancier",
}


def short(iso):
    """'2026-10-01' -> '1/10'"""
    d = date.fromisoformat(iso)
    return f"{d.day}/{d.month}"


def make(rid, user_id, eid, start, due, returned=None, fine=0, status="borrowing"):
    return {
        "id": rid, "user_id": user_id, "equipment_id": eid,
        "equipment_name": EQUIPMENT[eid],
        "start": start, "due": due,                      # ISO ใช้คำนวณ
        "start_date": short(start), "end_date": short(due),  # ใช้แสดงผล
        "return_date": short(returned) if returned else None,
        "fine": fine, "status": status,
    }


RECORDS = [
    make(1, "001", 1, "2026-09-28", "2026-10-01"),   # เลยกำหนดแล้ว (รอกดตรวจสอบค่าปรับ)
    make(2, "002", 3, "2026-09-29", "2026-10-02", returned="2026-10-02", status="returned"),
    make(3, "003", 4, "2026-10-01", "2026-10-08"),   # ยังไม่ถึงกำหนด
]


def newest_first(rows):
    return sorted(rows, key=lambda r: r["id"], reverse=True)


@app.route("/")
def index():
    return render_template("index.html", records=newest_first(RECORDS))


@app.route("/booking")
def booking():
    return render_template("booking.html")


@app.route("/book", methods=["POST"])
def book():
    user_id = request.form.get("user_id", "").strip()
    ids = [int(i) for i in request.form.getlist("equipment_id")]
    start = request.form.get("start_date", "")
    end = request.form.get("end_date", "")

    if not (user_id and ids and start and end):
        flash("กรอกข้อมูลไม่ครบ", "error")
        return redirect("/booking")
    if end < start:
        flash("วันที่คืนต้องไม่ก่อนวันที่รับ", "error")
        return redirect("/booking")

    # จองซ้ำ = อุปกรณ์เดียวกัน ยังไม่คืน และช่วงเวลาซ้อนกัน
    for eid in ids:
        for r in RECORDS:
            overlap = not (end < r["start"] or start > r["due"])
            if r["equipment_id"] == eid and r["return_date"] is None and overlap:
                flash("อุปกรณ์ถูกจองซ้ำในช่วงเวลานี้", "error")
                return redirect("/booking")

    for eid in ids:
        next_id = max(r["id"] for r in RECORDS) + 1
        RECORDS.append(make(next_id, user_id, eid, start, end))
    flash("จองอุปกรณ์สำเร็จ", "success")
    return redirect("/booking")


@app.route("/check", methods=["POST"])
def check():
    today = date.today()
    found = 0
    for r in RECORDS:
        if r["return_date"] is None:
            late = (today - date.fromisoformat(r["due"])).days
            if late > 0:
                r["status"] = "overdue"
                r["fine"] = late * FINE_PER_DAY
                found += 1
    if found:
        flash(f"ตรวจสอบค่าปรับสำเร็จ พบรายการเลยกำหนด {found} รายการ "
              f"(แจ้งเตือน LINE: จำลอง)", "success")
    else:
        flash("ตรวจสอบค่าปรับสำเร็จ ไม่พบรายการเลยกำหนด", "success")
    return redirect("/")


@app.route("/return/<int:record_id>")
def return_item(record_id):
    for r in RECORDS:
        if r["id"] == record_id and r["return_date"] is None:
            today = date.today()
            late = max((today - date.fromisoformat(r["due"])).days, 0)
            r["status"] = "returned"
            r["return_date"] = short(today.isoformat())
            r["fine"] = late * FINE_PER_DAY
            msg = "รับคืนอุปกรณ์สำเร็จ"
            if late:
                msg += f" ค่าปรับ {r['fine']} บาท"
            flash(msg, "success")
            return redirect("/")
    flash("ไม่พบรายการ หรือรับคืนไปแล้ว", "error")
    return redirect("/")


@app.route("/history")
def history():
    user_id = request.args.get("user_id", "").strip()
    mine = [r for r in RECORDS if r["user_id"] == user_id]
    return render_template("history.html", user_id=user_id, records=newest_first(mine))


if __name__ == "__main__":
    app.run(debug=True, port=5001)