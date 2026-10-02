import json
import os
from dashboard import app, get_connection, init_mock_db, DB_PATH

def run_e2e_tests():
    print("=== 🚀 เริ่มต้นรัน End-to-End Tests ครบทุกเส้นทางระบบหลังบ้าน ===")
    
    # ตรวจสอบเส้นทาง Route ทั้งหมดในระบบ
    routes = [rule.rule for rule in app.url_map.iter_rules()]
    print(f"📋 รายชื่อ Route ที่ตรวจสอบ: /book ({'/book' in routes}), /return ({any('/return' in r for r in routes)}), /webhook ({'/webhook' in routes})")
    
    if '/book' not in routes:
        print("❌ คำเตือน: กรุณาตรวจสอบการ Save ไฟล์ dashboard.py ให้เรียบร้อยก่อน")
        return

    # เตรียมฐานข้อมูล
    if not os.path.exists(DB_PATH):
        init_mock_db()
        
    client = app.test_client()
    conn = get_connection()
    cursor = conn.cursor()
    
    # ==========================================
    # 🟢 [Test Case 1] Happy Path: คนไม่มีปัญหา จองสำเร็จ
    # ==========================================
    print("\n--- [Test Case 1] ทดสอบ /book: ผู้ใช้ปกติ ไม่มีประวัติค้างชำระ ---")
    clean_user_id = 888
    cursor.execute("DELETE FROM borrow_records WHERE user_id = ?", (clean_user_id,))
    cursor.execute("DELETE FROM users WHERE user_id = ?", (clean_user_id,))
    
    cursor.execute("""
        INSERT INTO users (user_id, full_name, student_id, role) 
        VALUES (?, 'ผู้ใช้ปกติ ไม่มีปัญหา', '6588888', 'student')
    """, (clean_user_id,))
    cursor.execute("INSERT OR IGNORE INTO equipment (equipment_id, equipment_name, status) VALUES (2, 'แท็บเล็ตทดสอบ', 'available')")
    conn.commit()
    
    res_1 = client.post('/book', data={'user_id': clean_user_id, 'equipment_id': 2, 'start_date': '2026-10-05', 'end_date': '2026-10-10'})
    text_1 = res_1.data.decode('utf-8', errors='ignore')
    
    if "✅" in text_1 or "สำเร็จ" in text_1:
        print("🎉 [TC1 Result] ผ่าน! ผู้ใช้ปกติจองสำเร็จ")
    else:
        print(f"❌ [TC1 Result] ไม่ผ่าน: {text_1}")

    # ==========================================
    # 🔴 [Test Case 2] Negative Test: คนมีค่าปรับค้าง ถูกบล็อก
    # ==========================================
    print("\n--- [Test Case 2] ทดสอบ /book: ผู้มีค่าปรับค้าง ถูกบล็อกการจอง ---")
    blocked_user_id = 999
    cursor.execute("DELETE FROM borrow_records WHERE user_id = ?", (blocked_user_id,))
    cursor.execute("DELETE FROM users WHERE user_id = ?", (blocked_user_id,))
    
    cursor.execute("""
        INSERT INTO users (user_id, full_name, student_id, role) 
        VALUES (?, 'ทดสอบ ระบบถูกบล็อก', '6599999', 'student')
    """, (blocked_user_id,))
    cursor.execute("INSERT OR IGNORE INTO equipment (equipment_id, equipment_name, status) VALUES (1, 'กล้อง Canon EOS 90D', 'available')")
    cursor.execute("""
        INSERT INTO borrow_records (user_id, equipment_id, borrow_date, due_date, return_date, fine_amount, fine_paid, notified)
        VALUES (?, 1, '2026-01-01', '2026-01-05', NULL, 300.0, 0, 0)
    """, (blocked_user_id,))
    conn.commit()
    
    res_2 = client.post('/book', data={'user_id': blocked_user_id, 'equipment_id': 1, 'start_date': '2026-10-05', 'end_date': '2026-10-10'})
    text_2 = res_2.data.decode('utf-8', errors='ignore')
    
    if "❌" in text_2 or "ไม่สามารถยืม" in text_2:
        print("🎉 [TC2 Result] ผ่าน! ระบบบล็อกผู้มีค่าปรับค้างได้ถูกต้อง")
    else:
        print(f"❌ [TC2 Result] ไม่ผ่าน: {text_2}")

    # ==========================================
    # 🟡 [Test Case 3] Overlap Check: จองอุปกรณ์ทับซ้อนช่วงเวลากัน
    # ==========================================
    print("\n--- [Test Case 3] ทดสอบ /book: Overlap Check (จองซ้ำช่วงเวลา) ---")
    overlap_user_id = 777
    cursor.execute("DELETE FROM borrow_records WHERE user_id = ?", (overlap_user_id,))
    cursor.execute("DELETE FROM users WHERE user_id = ?", (overlap_user_id,))
    
    cursor.execute("""
        INSERT INTO users (user_id, full_name, student_id, role) 
        VALUES (?, 'ผู้ใช้ทดสอบ Overlap', '6577777', 'student')
    """, (overlap_user_id,))
    cursor.execute("INSERT OR IGNORE INTO equipment (equipment_id, equipment_name, status) VALUES (3, 'กล้องวิดีโอ 4K', 'available')")
    cursor.execute("""
        INSERT INTO borrow_records (user_id, equipment_id, borrow_date, due_date, return_date, fine_amount, fine_paid, notified)
        VALUES (888, 3, '2026-10-10', '2026-10-20', NULL, 0.0, 0, 0)
    """)
    conn.commit()
    
    res_3 = client.post('/book', data={'user_id': overlap_user_id, 'equipment_id': 3, 'start_date': '2026-10-15', 'end_date': '2026-10-25'})
    text_3 = res_3.data.decode('utf-8', errors='ignore')
    
    if "ถูกยืมหรือจอง" in text_3:
        print("🎉 [TC3 Result] ผ่าน! ระบบป้องกันการจองทับซ้อนสำเร็จ")
    else:
        print(f"❌ [TC3 Result] ไม่ผ่าน: {text_3}")

    # ==========================================
    # 🔵 [Test Case 4] Return & Fine Calculation: คืนอุปกรณ์
    # ==========================================
    print("\n--- [Test Case 4] ทดสอบ /return: คืนอุปกรณ์และคำนวณค่าปรับ ---")
    return_user_id = 555
    cursor.execute("DELETE FROM borrow_records WHERE user_id = ?", (return_user_id,))
    cursor.execute("DELETE FROM users WHERE user_id = ?", (return_user_id,))
    
    cursor.execute("""
        INSERT INTO users (user_id, full_name, student_id, role) 
        VALUES (?, 'ผู้ใช้ทดสอบคืนของ', '6555555', 'student')
    """, (return_user_id,))
    cursor.execute("INSERT OR IGNORE INTO equipment (equipment_id, equipment_name, status) VALUES (4, 'ขาตั้งกล้อง Tripod', 'available')")
    
    # สร้างรายการยืมที่กำหนดส่งในอดีต เพื่อให้ระบบคำนวณค่าปรับตอนคืน
    cursor.execute("""
        INSERT INTO borrow_records (user_id, equipment_id, borrow_date, due_date, return_date, fine_amount, fine_paid, notified)
        VALUES (?, 4, '2026-09-01', '2026-09-10', NULL, 0.0, 0, 0)
    """, (return_user_id,))
    conn.commit()
    
    # ดึง record_id ล่าสุดที่เพิ่งสร้าง
    rec = cursor.execute("SELECT MAX(record_id) FROM borrow_records").fetchone()
    target_record_id = rec[0]
    
    res_4 = client.post(f'/return/{target_record_id}')
    text_4 = res_4.data.decode('utf-8', errors='ignore')
    print(f"-> ข้อความตอบกลับจาก /return: {text_4}")
    
    # ตรวจสอบใน DB ว่า return_date ถูกบันทึกและมีค่าปรับเกิดขึ้นจริงไหม
    updated_rec = cursor.execute("SELECT return_date, fine_amount FROM borrow_records WHERE record_id = ?", (target_record_id,)).fetchone()
    conn.close()
    
    if updated_rec and updated_rec[0] is not None and updated_rec[1] > 0:
        print(f"🎉 [TC4 Result] ผ่าน! บันทึกการคืนสำเร็จและคำนวณค่าปรับได้ {updated_rec[1]} บาท")
    else:
        print("❌ [TC4 Result] ไม่ผ่าน: ระบบยังบันทึกการคืนหรือคำนวณค่าปรับไม่ถูกต้อง")

    # ==========================================
    # 🟣 [Test Case 5] LINE Webhook Simulation: ผู้ใช้กด Follow
    # ==========================================
    print("\n--- [Test Case 5] ทดสอบ /webhook: จำลองการเพิ่มเพื่อน LINE (Unlinked User) ---")
    test_line_id = "U_TEST_LINE_UUID_9999"
    
    # เคลียร์ line_id นี้ทิ้งก่อนเทสต์
    conn_w = get_connection()
    conn_w.execute("DELETE FROM users WHERE line_user_id = ?", (test_line_id,))
    conn_w.commit()
    conn_w.close()
    
    webhook_payload = {
        "events": [
            {
                "type": "follow",
                "source": {
                    "userId": test_line_id
                }
            }
        ]
    }
    
    res_5 = client.post('/webhook', json=webhook_payload)
    print(f"-> HTTP Status Code จาก /webhook: {res_5.status_code}")
    
    # ตรวจสอบว่าในฐานข้อมูลมี user ใหม่ถูกเพิ่มเข้ามาเป็น 'unlinked' หรือยัง
    conn_check = get_connection()
    new_user = conn_check.execute("SELECT role, full_name FROM users WHERE line_user_id = ?", (test_line_id,)).fetchone()
    conn_check.close()
    
    if res_5.status_code == 200 and new_user and new_user[0] == 'unlinked':
        print(f"🎉 [TC5 Result] ผ่าน! Webhook ทำงานสำเร็จ สร้างผู้ใช้สถานะ [{new_user[0]}] สำเร็จ")
    else:
        print("❌ [TC5 Result] ไม่ผ่าน: ไม่พบข้อมูลผู้ใช้ unlinked ในระบบหลังยิง Webhook")

if __name__ == "__main__":
    run_e2e_tests()