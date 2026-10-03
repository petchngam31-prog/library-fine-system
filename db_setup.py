import os
import sqlite3

DB_PATH = "library_mock.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_mock_db():
    conn = get_connection()
    cursor = conn.cursor()

    # ลบตารางเดิมและสร้างโครงสร้างตารางใหม่
    cursor.execute("DROP TABLE IF EXISTS borrow_records")
    cursor.execute("DROP TABLE IF EXISTS equipment")
    cursor.execute("DROP TABLE IF EXISTS users")

    cursor.execute("""
        CREATE TABLE users (
            user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name    TEXT NOT NULL,
            student_id   TEXT UNIQUE,
            role         TEXT NOT NULL DEFAULT 'student',
            line_user_id TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE equipment (
            equipment_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_name TEXT NOT NULL,
            category       TEXT,
            status         TEXT NOT NULL DEFAULT 'available'
        )
    """)

    cursor.execute("""
        CREATE TABLE borrow_records (
            record_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            equipment_id  INTEGER NOT NULL,
            borrow_date   TEXT NOT NULL,
            due_date      TEXT NOT NULL,
            return_date   TEXT,
            fine_amount   REAL NOT NULL DEFAULT 0,
            fine_paid     INTEGER NOT NULL DEFAULT 0,
            notified      INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(equipment_id)
        )
    """)

    # 1. รายการอุปกรณ์ยืม-คืนกล้องจริง 6 รายการ
    sample_equipment = [
        (1, 'กล้อง Canon EOS R50', 'camera', 'available'),
        (2, 'ขาตั้งกล้อง Fancier', 'tripod', 'available'),
        (3, 'กล้องภาพนิ่ง Nikon D3300', 'camera', 'available'),
        (4, 'กล้องภาพนิ่ง Canon EOS 700D', 'camera', 'available'),
        (5, 'กล้องดิจิตอลวิดีโอ Panasonic HC-V700', 'video', 'available'),
        (6, 'ขาตั้งกล้อง Sony', 'tripod', 'available')
    ]
    cursor.executemany("INSERT INTO equipment VALUES (?, ?, ?, ?)", sample_equipment)

    # 2. รายชื่อนักศึกษาที่เพิ่งลงระบบยืมจริง
    sample_users = [
        (1, 'นักศึกษา (6720610027)', '6720610027', 'student', None),
        (2, 'นักศึกษา (6720610037)', '6720610037', 'student', None)
    ]
    cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?)", sample_users)

    # 3. ข้อมูลรายการจองล่าสุดที่พึ่งลงระบบ
    sample_records = [
        (1, 1, 6, '2026-10-05', '2026-10-06', None, 0.0, 0, 0),  # 6720610027 ยืม ขาตั้งกล้อง Sony
        (2, 1, 5, '2026-10-05', '2026-10-06', None, 0.0, 0, 0),  # 6720610027 ยืม กล้องดิจิตอลวิดีโอ Panasonic
        (3, 2, 1, '2026-10-13', '2026-10-14', None, 0.0, 0, 0),  # 6720610037 ยืม กล้อง Canon EOS R50
        (4, 2, 2, '2026-10-13', '2026-10-14', None, 0.0, 0, 0)   # 6720610037 ยืม ขาตั้งกล้อง Fancier
    ]
    cursor.executemany("INSERT INTO borrow_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", sample_records)

    conn.commit()
    return conn

if __name__ == "__main__":
    init_mock_db()
    print("อัปเดตฐานข้อมูลเฉพาะรายการจริงเรียบร้อยแล้ว!")