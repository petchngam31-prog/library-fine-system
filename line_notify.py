"""
line_notify.py
===============
โมดูลเชื่อมต่อระบบแจ้งเตือนผ่าน LINE (LINE Notification Integration)

หมายเหตุสำคัญ:
  - ในสภาพแวดล้อมทดสอบนี้ไม่มีการเชื่อมต่ออินเทอร์เน็ตออกไปยังเซิร์ฟเวอร์ของ LINE
    และยังไม่มี LINE Channel Access Token ของจริง
  - โมดูลนี้จึงออกแบบให้มี "DRY-RUN MODE" (ค่าเริ่มต้น) ซึ่งจะพิมพ์ข้อความที่ "จะส่ง"
    ออกทางหน้าจอแทนการยิง HTTP request จริง เพื่อให้ทดสอบ logic การทำงานร่วมกันได้ครบวงจร
  - เมื่อมี LINE Messaging API Channel Access Token และ line_user_id จริงแล้ว
    ให้ตั้งค่า LineNotifier(dry_run=False, channel_access_token="...")
    โค้ดจะเรียก LINE Messaging API (push message) จริงผ่าน requests

การสมัครใช้งานจริง (ทำนอกโค้ดนี้):
  1. สร้าง LINE Official Account / Provider ที่ https://developers.line.biz/console/
  2. สร้าง Messaging API channel แล้วคัดลอก "Channel access token (long-lived)"
  3. ให้ผู้ใช้แต่ละคน Add เพื่อนบัญชี LINE OA แล้วเก็บค่า userId ของแต่ละคน
     (ได้จาก webhook event หรือ LINE Login) มาบันทึกไว้ในตาราง users.line_user_id
"""

from dataclasses import dataclass
from typing import Optional

LINE_PUSH_API_URL = "https://api.line.me/v2/bot/message/push"


@dataclass
class NotificationResult:
    success: bool
    line_user_id: str
    message: str
    mode: str          # "dry_run" หรือ "live"
    detail: str = ""


class LineNotifier:
    def __init__(
        self,
        channel_access_token: Optional[str] = None,
        dry_run: bool = True,
    ):
        self.channel_access_token = channel_access_token
        # ถ้าไม่มี token ให้บังคับ dry_run เสมอ เพื่อป้องกันการยิง request พลาด
        self.dry_run = dry_run or not channel_access_token

    def build_overdue_message(
        self, full_name: str, equipment_name: str, due_date: str,
        days_late: int, fine_amount: float,
    ) -> str:
        return (
            f"📢 แจ้งเตือนค้างคืนอุปกรณ์\n"
            f"คุณ {full_name} ยังไม่คืน: {equipment_name}\n"
            f"กำหนดคืน: {due_date}\n"
            f"เกินกำหนดมาแล้ว: {days_late} วัน\n"
            f"ค่าปรับสะสม: {fine_amount:,.0f} บาท\n"
            f"กรุณานำอุปกรณ์มาคืนโดยเร็วที่สุด"
        )

    def send(self, line_user_id: str, message: str) -> NotificationResult:
        if not line_user_id:
            return NotificationResult(
                success=False, line_user_id="", message=message,
                mode="skipped", detail="ไม่มี line_user_id ของผู้ใช้รายนี้",
            )

        if self.dry_run:
            print("----- [DRY-RUN] จะส่งข้อความ LINE ดังนี้ -----")
            print(f"ถึง userId: {line_user_id}")
            print(message)
            print("-----------------------------------------------")
            return NotificationResult(
                success=True, line_user_id=line_user_id, message=message,
                mode="dry_run", detail="จำลองการส่ง (ไม่ได้ยิง API จริง)",
            )

        # โหมดใช้งานจริง: เรียก LINE Messaging API
        import requests  # นำเข้าเฉพาะตอนใช้งานจริง เพื่อไม่ให้ dry-run ต้องพึ่ง dependency นี้

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.channel_access_token}",
        }
        payload = {
            "to": line_user_id,
            "messages": [{"type": "text", "text": message}],
        }
        try:
            resp = requests.post(LINE_PUSH_API_URL, headers=headers, json=payload, timeout=10)
            success = resp.status_code == 200
            return NotificationResult(
                success=success, line_user_id=line_user_id, message=message,
                mode="live", detail=f"HTTP {resp.status_code}: {resp.text}",
            )
        except Exception as exc:  # pragma: no cover - ต้องมีเครือข่ายจริงถึงจะเกิด
            return NotificationResult(
                success=False, line_user_id=line_user_id, message=message,
                mode="live", detail=f"ส่งไม่สำเร็จ: {exc}",
            )


if __name__ == "__main__":
    notifier = LineNotifier()  # ไม่ใส่ token -> dry-run โดยอัตโนมัติ
    msg = notifier.build_overdue_message(
        full_name="สมชาย ใจดี", equipment_name="กล้อง Canon EOS 90D",
        due_date="2026-09-15", days_late=8, fine_amount=800,
    )
    result = notifier.send("U-mock-somchai-0001", msg)
    print(result)
