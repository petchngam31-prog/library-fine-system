"""
eligibility_checker.py
=======================
โมดูลตรวจสอบสิทธิ์ก่อนยืม (Eligibility Check Module)

ก่อนอนุมัติให้ใครยืมอุปกรณ์ชิ้นใหม่ ต้องเช็กก่อนว่า:
  1) คนนั้นมีรายการที่ "ค้างคืน" (เลยกำหนด ยังไม่ส่งคืน) อยู่หรือไม่
  2) คนนั้นมี "ค่าปรับค้างจ่าย" อยู่หรือไม่
ถ้ามีอย่างใดอย่างหนึ่ง -> ไม่อนุญาตให้ยืมใหม่ พร้อมบอกเหตุผลที่ถูกปฏิเสธ
"""

import sqlite3
from datetime import date

from fine_calculator import calculate_fine


def check_eligibility(conn: sqlite3.Connection, user_id: int) -> dict:
    """
    ตรวจสอบว่าผู้ใช้คนนี้มีสิทธิ์ยืมอุปกรณ์ใหม่ได้หรือไม่

    Returns:
        dict ที่มี:
          - eligible: True/False อนุญาตให้ยืมได้ไหม
          - reasons: list ของข้อความเหตุผลที่ถูกปฏิเสธ (ว่างถ้า eligible=True)
          - overdue_items: รายการที่ค้างคืนอยู่ (เลยกำหนด)
          - unpaid_fine_total: ยอดค่าปรับค้างจ่ายรวม (บาท)
    """
    cur = conn.cursor()
    reasons = []

    # 1) เช็กรายการที่ยังไม่คืน แล้วดูว่ารายการไหนเลยกำหนดแล้วบ้าง
    unreturned = cur.execute(
        """
        SELECT br.record_id, br.due_date, e.equipment_name
        FROM borrow_records br
        JOIN equipment e ON e.equipment_id = br.equipment_id
        WHERE br.user_id = ? AND br.return_date IS NULL
        """,
        (user_id,),
    ).fetchall()

    overdue_items = []
    for row in unreturned:
        result = calculate_fine(row["due_date"])
        if result["is_overdue"]:
            overdue_items.append(
                {
                    "record_id": row["record_id"],
                    "equipment_name": row["equipment_name"],
                    "due_date": row["due_date"],
                    "days_late": result["days_late"],
                }
            )

    if overdue_items:
        names = ", ".join(item["equipment_name"] for item in overdue_items)
        reasons.append(f"มีอุปกรณ์ค้างคืนเลยกำหนด: {names}")

    # 2) เช็กค่าปรับที่ยังไม่จ่าย (fine_amount > 0 และ fine_paid = 0)
    unpaid_rows = cur.execute(
        """
        SELECT COALESCE(SUM(fine_amount), 0) AS total
        FROM borrow_records
        WHERE user_id = ? AND fine_paid = 0 AND fine_amount > 0
        """,
        (user_id,),
    ).fetchone()
    unpaid_fine_total = unpaid_rows["total"] if unpaid_rows else 0

    if unpaid_fine_total > 0:
        reasons.append(f"มีค่าปรับค้างจ่ายรวม {unpaid_fine_total:,.0f} บาท")

    return {
        "eligible": len(reasons) == 0,
        "reasons": reasons,
        "overdue_items": overdue_items,
        "unpaid_fine_total": unpaid_fine_total,
    }


if __name__ == "__main__":
    from db_setup import init_mock_db
    from fine_calculator import check_and_update_fines

    conn = init_mock_db()
    check_and_update_fines(conn)  # คำนวณค่าปรับก่อน เพื่อให้ fine_amount ในฐานข้อมูลเป็นปัจจุบัน

    print("ทดสอบตรวจสอบสิทธิ์ของผู้ใช้แต่ละคน:\n")
    for user_id in [1, 2, 3, 4]:
        user = conn.execute(
            "SELECT full_name FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        result = check_eligibility(conn, user_id)

        status = "✅ อนุญาตให้ยืมได้" if result["eligible"] else "❌ ไม่อนุญาตให้ยืม"
        print(f"[User #{user_id}] {user['full_name']} -> {status}")
        for reason in result["reasons"]:
            print(f"    เหตุผล: {reason}")
        print()

    conn.close()
