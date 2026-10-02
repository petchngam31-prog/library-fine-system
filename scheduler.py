"""
scheduler.py
============
โมดูล Automation — ตั้งเวลาให้ระบบ "เช็กรายการค้างคืน + คำนวณค่าปรับ
+ ส่งแจ้งเตือน LINE" ทำงานเองอัตโนมัติ โดยไม่ต้องมีคนพิมพ์คำสั่งรันเอง

เปรียบเทียบ:
  - ไม่มี scheduler  -> ต้องพิมพ์ python simulation.py เองทุกครั้ง
  - มี scheduler      -> ตั้งเวลาไว้ครั้งเดียว ระบบรันเองไปเรื่อย ๆ ตามเวลาที่กำหนด

โหมดการใช้งาน (เลือกได้ตอนรัน):
  python scheduler.py           -> โหมดจริง รันทุกวันเวลา 06:00 (DAILY_RUN_TIME)
  python scheduler.py --demo    -> โหมดสาธิต รันซ้ำทุก 15 วินาที ให้เห็นผลเร็ว ๆ
                                    (ใช้ตอนนำเสนอให้อาจารย์ดูว่าระบบรันเองได้จริง)
"""

import sys
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from db_setup import init_mock_db, get_connection, DB_PATH
from fine_calculator import check_and_update_fines, mark_as_notified, DEFAULT_FINE_RATE_PER_DAY
from line_notify import LineNotifier
import os

DAILY_RUN_TIME = {"hour": 6, "minute": 0}  # เวลาที่จะให้รันทุกวัน (24 ชม.)
DEMO_INTERVAL_SECONDS = 15                 # ความถี่ตอนรันโหมดสาธิต


def ensure_db():
    if not os.path.exists(DB_PATH):
        conn = init_mock_db()
        conn.close()


def run_daily_check():
    """งานหลักที่ scheduler จะเรียกเองตามเวลาที่ตั้งไว้ -- ไม่มีใครต้องกดอะไรเลย"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 70}")
    print(f"[{now}] เริ่มตรวจสอบรายการค้างคืนอัตโนมัติ")
    print(f"{'=' * 70}")

    ensure_db()
    conn = get_connection()

    overdue_list = check_and_update_fines(conn, rate_per_day=DEFAULT_FINE_RATE_PER_DAY)
    if not overdue_list:
        print("ไม่มีรายการเลยกำหนดคืนในขณะนี้")
        conn.close()
        return

    notifier = LineNotifier(dry_run=True)  # เปลี่ยนเป็น token จริงได้เมื่อพร้อมใช้งานจริง
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
    print(f"ผลสรุป: พบรายการเลยกำหนด {len(overdue_list)} รายการ, ส่งแจ้งเตือนสำเร็จ {sent} รายการ")


def start_scheduler(demo_mode: bool = False):
    scheduler = BlockingScheduler(timezone="Asia/Bangkok")

    if demo_mode:
        scheduler.add_job(
            run_daily_check,
            "interval",
            seconds=DEMO_INTERVAL_SECONDS,
            next_run_time=datetime.now(),  # รันทันที 1 ครั้งตอนเริ่ม จะได้เห็นผลเร็ว
        )
        print(f"[DEMO MODE] ระบบจะรันตรวจสอบเองทุก {DEMO_INTERVAL_SECONDS} วินาที")
        print("(ในระบบจริงจะตั้งเป็นรันวันละครั้งแทน ใช้โหมดนี้เพื่อสาธิตให้เห็นผลเร็ว ๆ เท่านั้น)")
    else:
        scheduler.add_job(
            run_daily_check,
            "cron",
            hour=DAILY_RUN_TIME["hour"],
            minute=DAILY_RUN_TIME["minute"],
        )
        print(f"[PRODUCTION MODE] ระบบจะรันตรวจสอบเองทุกวัน เวลา "
              f"{DAILY_RUN_TIME['hour']:02d}:{DAILY_RUN_TIME['minute']:02d} น.")

    print("กด Ctrl+C เพื่อหยุดการทำงาน\n")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\nหยุดการทำงานของ scheduler แล้ว")


if __name__ == "__main__":
    demo = "--demo" in sys.argv
    start_scheduler(demo_mode=demo)
