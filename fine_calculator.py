import sqlite3
from datetime import date, datetime
from typing import Optional

DEFAULT_FINE_RATE_PER_DAY = 100  # บาทต่อวัน


def _parse_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def calculate_fine(
    due_date: str,
    return_date: Optional[str] = None,
    reference_date: Optional[date] = None,
    rate_per_day: float = DEFAULT_FINE_RATE_PER_DAY,
) -> dict:
    # คำนวณค่าปรับของรายการยืม-คืน 1 รายการ
    # ถ้า return_date มีค่า = คืนแล้ว ใช้วันนั้นคำนวณ / ถ้าไม่มี = ยังไม่คืน ใช้วันนี้แทน
    due = _parse_date(due_date)
    check_point = _parse_date(return_date) if return_date else (reference_date or date.today())

    days_late = (check_point - due).days
    days_late = max(days_late, 0)  # ไม่มีค่าปรับติดลบ
    fine_amount = days_late * rate_per_day

    return {
        "is_overdue": days_late > 0,
        "days_late": days_late,
        "fine_amount": fine_amount,
    }


def check_and_update_fines(
    conn: sqlite3.Connection, rate_per_day: float = DEFAULT_FINE_RATE_PER_DAY
) -> list[dict]:
    # ไล่ตรวจทุกรายการที่ยังไม่คืน (return_date IS NULL) แล้วคำนวณ+บันทึกค่าปรับกลับเข้า DB
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT br.record_id, br.due_date, br.return_date, br.notified,
               u.user_id, u.full_name, u.line_user_id,
               e.equipment_id, e.equipment_name
        FROM borrow_records br
        JOIN users u ON u.user_id = br.user_id
        JOIN equipment e ON e.equipment_id = br.equipment_id
        WHERE br.return_date IS NULL
        """
    ).fetchall()

    overdue_list = []
    for row in rows:
        result = calculate_fine(row["due_date"], rate_per_day=rate_per_day)
        if result["is_overdue"]:
            cur.execute(
                "UPDATE borrow_records SET fine_amount = ? WHERE record_id = ?",
                (result["fine_amount"], row["record_id"]),
            )
            # เก็บรายละเอียดไว้ส่งต่อให้โมดูลแจ้งเตือน LINE ใช้งานต่อ
            overdue_list.append(
                {
                    "record_id": row["record_id"],
                    "user_id": row["user_id"],
                    "full_name": row["full_name"],
                    "line_user_id": row["line_user_id"],
                    "equipment_name": row["equipment_name"],
                    "due_date": row["due_date"],
                    "days_late": result["days_late"],
                    "fine_amount": result["fine_amount"],
                    "already_notified": bool(row["notified"]),
                }
            )
    conn.commit()
    return overdue_list


def mark_as_notified(conn: sqlite3.Connection, record_id: int) -> None:
    # กันไม่ให้ส่งแจ้งเตือนซ้ำสำหรับรายการเดิม
    conn.execute(
        "UPDATE borrow_records SET notified = 1 WHERE record_id = ?", (record_id,)
    )
    conn.commit()


if __name__ == "__main__":
    # ทดสอบ logic ล้วน ๆ โดยไม่ต้องพึ่งฐานข้อมูล
    print(calculate_fine(due_date="2026-09-15", reference_date=date(2026, 9, 23)))
    print(calculate_fine(due_date="2026-09-25", reference_date=date(2026, 9, 23)))
    print(calculate_fine(due_date="2026-09-10", return_date="2026-09-12"))