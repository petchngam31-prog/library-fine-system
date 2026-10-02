from dashboard import get_connection

# 1. แทนที่ข้อความด้านล่างนี้ด้วย LINE ID จริงที่คุณคัดลอกมาจากขั้นตอนที่ 1
my_line_id = "Ubd5423c296e823b727c730f0e844b271"

conn = get_connection()
cursor = conn.cursor()

# 2. อัปเดตไอดีนี้ให้กับผู้ใช้ในระบบ (เช่น กำหนดให้ User ID 1 เป็นแอดมินของคุณ)
cursor.execute(
    """
    UPDATE users 
    SET line_user_id = ?, role = 'admin', full_name = 'ท่านแอดมิน (ตัวจริง)' 
    WHERE user_id = 1
""",
    (my_line_id,),
)

conn.commit()
conn.close()

print("🎉 บันทึก LINE ID และตั้งค่าสิทธิ์แอดมินสำเร็จเรียบร้อยแล้ว!")