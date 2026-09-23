"""
db_setup.py
============
สร้างฐานข้อมูลจำลอง (Mock Database) ด้วย SQLite สำหรับทดสอบระบบ
ยืม-คืนอุปกรณ์ของคณะวิทยาการสื่อสาร โดยไม่ต้องเข้าถึงฐานข้อมูลจริง

ตาราง:
  - users            : ผู้ใช้งาน (นักศึกษา/เจ้าหน้าที่) พร้อม LINE user id สำหรับแจ้งเตือน
  - equipment        : รายการอุปกรณ์ที่ให้ยืม
  - borrow_records   : รายการยืม-คืน (วันที่ยืม, กำหนดคืน, วันที่คืนจริง, สถานะค่าปรับ)
"""

import sqlite3
from datetime import date, timedelta

DB_PATH = "library_mock.db"


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    cur.executescript(
        """
        DROP TABLE IF EXISTS borrow_records;
        DROP TABLE IF EXISTS equipment;
        DROP TABLE IF EXISTS users;

        CREATE TABLE users (
            user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name    TEXT NOT NULL,
            student_id   TEXT UNIQUE,
            role         TEXT NOT NULL DEFAULT 'student',   -- student / staff
            line_user_id TEXT                                -- LINE userId สำหรับส่ง push message
        );

        CREATE TABLE equipment (
            equipment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_name TEXT NOT NULL,
            category       TEXT,
            status         TEXT NOT NULL DEFAULT 'available'  -- available / borrowed / maintenance
        );

        CREATE TABLE borrow_records (
            record_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            equipment_id  INTEGER NOT NULL,
            borrow_date   TEXT NOT NULL,   -- ISO format YYYY-MM-DD
            due_date      TEXT NOT NULL,   -- ISO format YYYY-MM-DD
            return_date   TEXT,            -- NULL = ยังไม่คืน
            fine_amount   REAL NOT NULL DEFAULT 0,
            fine_paid     INTEGER NOT NULL DEFAULT 0,  -- 0 = ยังไม่จ่าย, 1 = จ่ายแล้ว
            notified      INTEGER NOT NULL DEFAULT 0,  -- 0 = ยังไม่แจ้งเตือน, 1 = แจ้งเตือนแล้ว
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
        );
        """
    )
    conn.commit()


def seed_data(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    today = date.today()

    # ผู้ใช้งานจำลอง (line_user_id เป็นค่าจำลอง ใช้ทดสอบ dry-run เท่านั้น)
    users = [
        ("สมชาย ใจดี", "6412345001", "student", "U-mock-somchai-0001"),
        ("สมหญิง รักเรียน", "6412345002", "student", "U-mock-somying-0002"),
        ("วิชัย ขยันยืม", "6412345003", "student", "U-mock-wichai-0003"),
        ("เจ้าหน้าที่ ก", None, "staff", "U-mock-staff-0004"),
    ]
    cur.executemany(
        "INSERT INTO users (full_name, student_id, role, line_user_id) VALUES (?, ?, ?, ?)",
        users,
    )

    equipment = [
        ("กล้อง Canon EOS 90D", "camera"),
        ("ขาตั้งกล้อง Manfrotto", "tripod"),
        ("ไมโครโฟน Rode NTG3", "audio"),
        ("โน้ตบุ๊ก MacBook Pro", "computer"),
        ("ไฟส่องสว่าง LED Panel", "lighting"),
    ]
    cur.executemany(
        "INSERT INTO equipment (equipment_name, category) VALUES (?, ?)", equipment
    )

    # รายการยืม จำลองสถานการณ์หลายแบบ:
    #  1) เกินกำหนดมาแล้วหลายวัน ยังไม่คืน  -> ต้องคำนวณค่าปรับ + แจ้งเตือน
    #  2) เกินกำหนด 1 วัน ยังไม่คืน          -> ต้องคำนวณค่าปรับ + แจ้งเตือน
    #  3) ยังไม่ถึงกำหนดคืน                   -> ไม่ต้องทำอะไร
    #  4) คืนตรงเวลาแล้ว                      -> ไม่มีค่าปรับ
    borrow_records = [
        # (user_id, equipment_id, borrow_date, due_date, return_date)
        (1, 1, str(today - timedelta(days=10)), str(today - timedelta(days=3)), None),
        (2, 3, str(today - timedelta(days=6)), str(today - timedelta(days=1)), None),
        (3, 4, str(today - timedelta(days=2)), str(today + timedelta(days=5)), None),
        (1, 2, str(today - timedelta(days=8)), str(today - timedelta(days=5)),
         str(today - timedelta(days=5))),
    ]
    cur.executemany(
        """INSERT INTO borrow_records
           (user_id, equipment_id, borrow_date, due_date, return_date)
           VALUES (?, ?, ?, ?, ?)""",
        borrow_records,
    )

    conn.commit()


def init_mock_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """สร้างและเติมข้อมูลฐานข้อมูลจำลองใหม่ทั้งหมด (ใช้สำหรับรันทดสอบ/สาธิต)"""
    conn = get_connection(db_path)
    create_schema(conn)
    seed_data(conn)
    return conn


if __name__ == "__main__":
    conn = init_mock_db()
    print(f"สร้างฐานข้อมูลจำลองสำเร็จที่ '{DB_PATH}'")
    print("ตาราง users:", [dict(r) for r in conn.execute("SELECT * FROM users")])
    print("ตาราง equipment:", [dict(r) for r in conn.execute("SELECT * FROM equipment")])
    print("ตาราง borrow_records:", [dict(r) for r in conn.execute("SELECT * FROM borrow_records")])
    conn.close()
