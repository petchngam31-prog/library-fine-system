from datetime import date, datetime

# กำหนดอัตราค่าปรับมาตรฐาน (100 บาทต่อวัน)
DEFAULT_FINE_RATE_PER_DAY = 100.0

def calculate_fine(due_date_str, rate_per_day=DEFAULT_FINE_RATE_PER_DAY):
    current_date = date.today()
    due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
    
    # ตรวจสอบว่าเกินกำหนดหรือไม่ (วันที่ปัจจุบัน มากกว่า วันกำหนดคืน)
    if current_date > due_date:
        days_late = (current_date - due_date).days
        fine_amount = days_late * rate_per_day
        return {
            "is_overdue": True,
            "days_late": days_late,
            "fine_amount": fine_amount
        }
    else:
        return {
            "is_overdue": False,
            "days_late": 0,
            "fine_amount": 0.0
        }