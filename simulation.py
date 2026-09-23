"""
simulation.py
==============
สคริปต์จำลองการทำงานร่วมกันทั้งระบบ (Simulation & Testing)

ขั้นตอน:
  1. สร้างฐานข้อมูลจำลอง (mock DB) พร้อมข้อมูลทดสอบ (จำลองการยืมอุปกรณ์)
  2. ระบบตรวจสอบวันคืน (หารายการที่เลยกำหนด)
  3. คำนวณค่าปรับของแต่ละรายการที่เลยกำหนด
  4. ส่งข้อความแจ้งเตือนผ่าน LINE (dry-run) ไปยังผู้ยืมแต่ละคน
  5. สรุปผลลัพธ์ทั้งหมด เพื่อตรวจสอบว่าโมดูลทำงานประสานกันได้ครบวงจร

รันคำสั่ง:  python simulation.py
"""

from db_setup import init_mock_db
from fine_calculator import check_and_update_fines, mark_as_notified, DEFAULT_FINE_RATE_PER_DAY
from line_notify import LineNotifier


def mark_as_notified_safe(conn, record_id):
    mark_as_notified(conn, record_id)


def run_simulation():
    print("=" * 70)
    print("STEP 1: สร้างฐานข้อมูลจำลอง (Mock Database)")
    print("=" * 70)
    conn = init_mock_db()
    print("สร้างฐานข้อมูลจำลองสำเร็จ (library_mock.db)\n")

    print("=" * 70)
    print("STEP 2-3: ตรวจสอบวันคืน + คำนวณค่าปรับ (Fine Calculation Module)")
    print("=" * 70)
    overdue_list = check_and_update_fines(conn, rate_per_day=DEFAULT_FINE_RATE_PER_DAY)

    if not overdue_list:
        print("ไม่มีรายการเลยกำหนดคืน ณ ขณะนี้")
    for item in overdue_list:
        print(
            f"- [Record #{item['record_id']}] {item['full_name']} ยืม "
            f"'{item['equipment_name']}' เกินกำหนด {item['days_late']} วัน "
            f"=> ค่าปรับ {item['fine_amount']:,.0f} บาท"
        )
    print()

    print("=" * 70)
    print("STEP 4: ส่งข้อความแจ้งเตือนผ่าน LINE (LINE Notification, dry-run mode)")
    print("=" * 70)
    notifier = LineNotifier(dry_run=True)  # ไม่มี token จริง -> จำลองการส่ง
    notification_log = []
    for item in overdue_list:
        message = notifier.build_overdue_message(
            full_name=item["full_name"],
            equipment_name=item["equipment_name"],
            due_date=item["due_date"],
            days_late=item["days_late"],
            fine_amount=item["fine_amount"],
        )
        result = notifier.send(item["line_user_id"], message)
        notification_log.append((item["record_id"], result))
        if result.success:
            mark_as_notified_safe(conn, item["record_id"])
    print()

    print("=" * 70)
    print("STEP 5: สรุปผลการทดสอบ (Summary)")
    print("=" * 70)
    total_fine = sum(item["fine_amount"] for item in overdue_list)
    total_notified = sum(1 for _, r in notification_log if r.success)
    print(f"จำนวนรายการเลยกำหนดทั้งหมด : {len(overdue_list)} รายการ")
    print(f"ยอดค่าปรับรวม               : {total_fine:,.0f} บาท")
    print(f"จำนวนที่แจ้งเตือนสำเร็จ      : {total_notified}/{len(overdue_list)}")

    # ตรวจสอบว่าข้อมูลถูกบันทึกกลับเข้าฐานข้อมูลจริง (verify end-to-end)
    print("\nตรวจสอบข้อมูลใน borrow_records หลังอัปเดต:")
    rows = conn.execute(
        """SELECT record_id, user_id, equipment_id, due_date,
                  return_date, fine_amount, notified
           FROM borrow_records"""
    ).fetchall()
    for r in rows:
        print(dict(r))

    conn.close()
    print("\nจบการจำลองการทำงาน — ระบบทำงานประสานกันครบวงจรตามที่ออกแบบไว้")


if __name__ == "__main__":
    run_simulation()
