from datetime import date, datetime

DEFAULT_FINE_RATE_PER_DAY = 50.0  # หรืออัตราค่าปรับต่อวันที่ระบบคุณใช้

def calculate_fine(due_date, return_date=None, rate_per_day=DEFAULT_FINE_RATE_PER_DAY):
    if isinstance(due_date, str):
        due = datetime.strptime(due_date.split("T")[0], "%Y-%m-%d").date()
    else:
        due = due_date

    if return_date:
        if isinstance(return_date, str):
            ret = datetime.strptime(return_date.split("T")[0], "%Y-%m-%d").date()
        else:
            ret = return_date
    else:
        ret = date.today()

    late_days = (ret - due).days
    if late_days > 0:
        return {
            "is_overdue": True,
            "days_late": late_days,
            "fine_amount": late_days * rate_per_day
        }
    return {
        "is_overdue": False,
        "days_late": 0,
        "fine_amount": 0.0
    }

def check_and_update_fines(conn, rate_per_day=DEFAULT_FINE_RATE_PER_DAY):
    """ตรวจสอบรายการที่เกินกำหนด อัปเดตค่าปรับลง DB และส่งคืนรายการที่เลยกำหนด"""
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT br.record_id, br.due_date, br.user_id,
               u.full_name, u.line_user_id, e.equipment_name
        FROM borrow_records br
        JOIN users u ON u.user_id = br.user_id
        JOIN equipment e ON e.equipment_id = br.equipment_id
        WHERE br.return_date IS NULL
    """).fetchall()

    overdue_list = []
    today_str = date.today().isoformat()

    for row in rows:
        r = dict(row)
        res = calculate_fine(r["due_date"], today_str, rate_per_day)
        if res["is_overdue"]:
            cursor.execute("""
                UPDATE borrow_records
                SET fine_amount = ?
                WHERE record_id = ?
            """, (res["fine_amount"], r["record_id"]))
            
            r["days_late"] = res["days_late"]
            r["fine_amount"] = res["fine_amount"]
            overdue_list.append(r)

    conn.commit()
    return overdue_list

def mark_as_notified(conn, record_id):
    """บันทึกสถานะว่าแจ้งเตือนแล้ว"""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE borrow_records
        SET notified = 1
        WHERE record_id = ?
    """, (record_id,))
    conn.commit()