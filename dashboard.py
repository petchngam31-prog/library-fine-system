import os
import hmac
import hashlib
import base64
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, redirect, render_template, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from line_notify import LineNotifier

DATABASE_URL = os.environ.get("DATABASE_URL", "")
FINE_RATE = 50
BANGKOK = ZoneInfo("Asia/Bangkok")
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_ENABLED = bool(LINE_TOKEN and LINE_SECRET)
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=True)

def conn():
    if not DATABASE_URL: raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)

def today_bkk(): return datetime.now(BANGKOK).date()

def business_days_late(due, returned=None):
    if isinstance(due, str): due=date.fromisoformat(due)
    end=date.fromisoformat(returned) if isinstance(returned,str) else (returned or today_bkk())
    if end<=due: return 0
    cur=due+timedelta(days=1); days=0
    while cur<=end:
        if cur.weekday()<5: days+=1
        cur+=timedelta(days=1)
    return days

def fine(due, returned=None):
    days=business_days_late(due,returned); return days,days*FINE_RATE

def valid_line_signature(body):
    sig=request.headers.get("X-Line-Signature","")
    if not LINE_SECRET or not sig: return False
    expected=base64.b64encode(hmac.new(LINE_SECRET.encode(),body,hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected,sig)

def notifier(): return LineNotifier(channel_access_token=LINE_TOKEN,dry_run=not LINE_ENABLED)

def reply_line(reply_token,text):
    if not LINE_ENABLED or not reply_token: return False
    import requests
    r=requests.post("https://api.line.me/v2/bot/message/reply",headers={"Authorization":f"Bearer {LINE_TOKEN}","Content-Type":"application/json"},json={"replyToken":reply_token,"messages":[{"type":"text","text":text}]},timeout=10)
    return r.status_code==200

def admin_ok(password):
    if ADMIN_PASSWORD_HASH: return check_password_hash(ADMIN_PASSWORD_HASH,password)
    if ADMIN_PASSWORD: return hmac.compare_digest(ADMIN_PASSWORD,password)
    return False

def run_overdue_check():
    with conn() as c:
        rows=c.execute("SELECT br.id AS record_id,br.due_date,br.notified,u.name AS full_name,u.line_user_id,e.name AS equipment_name FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN equipment e ON e.id=br.equipment_id WHERE br.return_date IS NULL").fetchall()
        sent=overdue=0; n=notifier()
        for r in rows:
            days,amount=fine(r["due_date"])
            if days<=0: continue
            overdue+=1
            if r["notified"] or not r["line_user_id"]: continue
            result=n.send(r["line_user_id"],n.build_overdue_message(r["full_name"],r["equipment_name"],str(r["due_date"]),days,amount))
            if result.success:
                sent+=1; c.execute("UPDATE borrow_records SET notified=true WHERE id=%s",(r["record_id"],))
    return overdue,sent

@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"]="nosniff"; r.headers["X-Frame-Options"]="SAMEORIGIN"; r.headers["Referrer-Policy"]="same-origin"; r.headers["Cache-Control"]="no-store"; return r

@app.route("/")
@app.route("/booking")
@app.route("/booking.html")
def booking(): return render_template("booking.html")

@app.route("/history")
@app.route("/history.html")
def history(): return render_template("history.html")

@app.route("/admin",methods=["GET","POST"])
@app.route("/index.html",methods=["GET","POST"])
def admin():
    error=""
    if request.method=="POST":
        if admin_ok(request.form.get("password","")):
            session.clear(); session["is_admin"]=True; return redirect(url_for("admin"))
        error="รหัสผ่านไม่ถูกต้อง"
    if session.get("is_admin"): return render_template("index.html")
    return render_template_string('''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>เข้าสู่ระบบเจ้าหน้าที่</title><body><main style="max-width:440px;margin:70px auto;font-family:sans-serif"><h2>เข้าสู่ระบบเจ้าหน้าที่</h2>{% if error %}<p style="color:#b91c1c">{{error}}</p>{% endif %}<form method="post"><label>รหัสผ่าน</label><input name="password" type="password" required autocomplete="current-password" style="display:block;width:100%;padding:10px;margin:8px 0 14px"><button type="submit">เข้าสู่ระบบ</button></form><p><a href="/">กลับหน้าจอง</a></p></main></html>''',error=error)

@app.route("/logout")
def logout(): session.clear(); return redirect("/")

@app.route("/api/equipment")
def api_equipment():
    with conn() as c: rows=c.execute("SELECT id AS equipment_id,name AS equipment_name,category,status FROM equipment ORDER BY id").fetchall()
    return jsonify(equipment=rows)

@app.route("/api/admin/users",methods=["GET","POST"])
def admin_users():
    if not session.get("is_admin"): return jsonify(message="Unauthorized"),401
    with conn() as c:
        if request.method=="GET":
            rows=c.execute("SELECT id,student_id,name,(line_user_id IS NOT NULL) AS line_linked,created_at FROM users ORDER BY student_id").fetchall(); return jsonify(users=rows)
        d=request.get_json(silent=True) or {}; sid=str(d.get("student_id","")).strip().upper(); name=str(d.get("name","")).strip()
        if not sid or not name or len(sid)>50 or len(name)>200: return jsonify(message="กรุณากรอกรหัสผู้ยืมและชื่อให้ถูกต้อง"),400
        if c.execute("SELECT 1 FROM users WHERE student_id=%s",(sid,)).fetchone(): return jsonify(message="รหัสผู้ยืมนี้มีอยู่แล้ว"),409
        pin=f"{secrets.randbelow(1000000):06d}"; c.execute("INSERT INTO users(student_id,name,booking_pin_hash) VALUES(%s,%s,%s)",(sid,name,generate_password_hash(pin)))
    return jsonify(message="เพิ่มผู้ยืมสำเร็จ",student_id=sid,booking_pin=pin),201

@app.route("/api/book",methods=["POST"])
def api_book():
    d=request.get_json(silent=True) or {}; sid=str(d.get("user_id","")).strip().upper(); pin=str(d.get("booking_pin","")).strip(); start=d.get("start_date"); end=d.get("end_date")
    raw=d.get("equipment_ids") or ([d.get("equipment_id")] if d.get("equipment_id") else [])
    if not sid or not pin or not start or not end or not raw: return jsonify(message="กรุณากรอกข้อมูลให้ครบถ้วน รวมถึง PIN ผู้ยืม"),400
    try:
        sd=date.fromisoformat(start); ed=date.fromisoformat(end); eids=list(dict.fromkeys(int(x) for x in raw))
        if ed<sd or sd<today_bkk() or any(x not in range(1,7) for x in eids): raise ValueError
    except Exception: return jsonify(message="รูปแบบข้อมูลหรือวันที่ไม่ถูกต้อง"),400
    with conn() as c:
        u=c.execute("SELECT id,booking_pin_hash,line_user_id FROM users WHERE student_id=%s",(sid,)).fetchone()
        if not u or not u["booking_pin_hash"] or not check_password_hash(u["booking_pin_hash"],pin): return jsonify(message="รหัสผู้ยืมหรือ PIN ไม่ถูกต้อง กรุณาติดต่อเจ้าหน้าที่"),403
        uid=u["id"]
        for eid in eids:
            if c.execute("SELECT 1 FROM borrow_records WHERE equipment_id=%s AND return_date IS NULL AND borrow_date<=%s AND due_date>=%s",(eid,ed,sd)).fetchone(): return jsonify(message=f"อุปกรณ์หมายเลข {eid} ถูกจองในช่วงเวลาดังกล่าวแล้ว"),400
        for eid in eids: c.execute("INSERT INTO borrow_records(user_id,equipment_id,borrow_date,due_date,purpose) VALUES(%s,%s,%s,%s,%s)",(uid,eid,sd,ed,str(d.get("purpose",""))[:500]))
        response={"message":"บันทึกการจองสำเร็จ","line_linked":bool(u["line_user_id"])}
        if not u["line_user_id"]:
            code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8)); code_hash=hashlib.sha256(code.encode()).hexdigest()
            c.execute("UPDATE line_link_codes SET used_at=now() WHERE user_id=%s AND used_at IS NULL",(uid,)); c.execute("INSERT INTO line_link_codes(user_id,code_hash,expires_at) VALUES(%s,%s,now()+interval '15 minutes')",(uid,code_hash))
            response.update(line_link_code=code,line_instruction=f"ผูก {code}")
    session["student_id"]=sid
    return jsonify(**response)

@app.route("/api/records")
def records():
    if not session.get("is_admin"): return jsonify(message="Unauthorized"),401
    with conn() as c: rows=c.execute("SELECT br.id AS record_id,br.*,u.name AS full_name,u.student_id,u.line_user_id,e.name AS equipment_name FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN equipment e ON e.id=br.equipment_id ORDER BY br.id DESC").fetchall()
    out=[]
    for x in rows:
        x=dict(x); days,amount=fine(x["due_date"],x["return_date"]); x["days_late"]=days; x["fine_amount"]=x["fine"] if x["fine_paid"] else amount; x["is_overdue"]=days>0 and not x["return_date"]; out.append(x)
    return jsonify(records=out)

@app.route("/api/return/<int:rid>",methods=["POST"])
def return_record(rid):
    if not session.get("is_admin"): return jsonify(message="Unauthorized"),401
    with conn() as c:
        row=c.execute("SELECT due_date,return_date FROM borrow_records WHERE id=%s",(rid,)).fetchone()
        if not row: return jsonify(message="ไม่พบรายการ"),404
        if row["return_date"]: return jsonify(message="รายการนี้รับคืนแล้ว"),400
        today=today_bkk(); days,amount=fine(row["due_date"],today); c.execute("UPDATE borrow_records SET return_date=%s,fine=%s WHERE id=%s",(today,amount,rid))
    return jsonify(message="รับคืนสำเร็จ",fine_amount=amount,days_late=days)

@app.route("/api/pay-fine/<int:rid>",methods=["POST"])
def pay_fine(rid):
    if not session.get("is_admin"): return jsonify(message="Unauthorized"),401
    with conn() as c: c.execute("UPDATE borrow_records SET fine_paid=true WHERE id=%s",(rid,))
    return jsonify(message="บันทึกชำระค่าปรับแล้ว")

@app.route("/api/check",methods=["POST"])
def check():
    if not session.get("is_admin"): return jsonify(message="Unauthorized"),401
    overdue,sent=run_overdue_check(); return jsonify(message="ตรวจสอบรายการเกินกำหนดแล้ว",overdue_count=overdue,notified_count=sent,line_enabled=LINE_ENABLED)

@app.route("/api/cron/check",methods=["POST"])
def cron_check():
    supplied=request.headers.get("X-Cron-Secret","")
    if not CRON_SECRET or not hmac.compare_digest(supplied,CRON_SECRET): return jsonify(message="Unauthorized"),401
    overdue,sent=run_overdue_check(); return jsonify(ok=True,overdue_count=overdue,notified_count=sent)

@app.route("/api/history")
@app.route("/api/user-history")
def api_history():
    sid=session.get("student_id")
    if not sid: return jsonify(message="กรุณาจองหรือยืนยันตัวตนก่อนดูประวัติ",records=[]),401
    with conn() as c: rows=c.execute("SELECT br.id AS record_id,br.borrow_date,br.due_date,br.return_date,br.fine AS fine_amount,e.name AS equipment_name FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN equipment e ON e.id=br.equipment_id WHERE u.student_id=%s ORDER BY br.id DESC",(sid,)).fetchall()
    return jsonify(records=rows)

@app.route("/line/link",methods=["POST"])
def line_link(): return jsonify(success=False,message="ใช้รหัสเชื่อมบัญชีแบบครั้งเดียวผ่าน LINE เท่านั้น"),410

@app.route("/line/status")
def line_status(): return jsonify(enabled=LINE_ENABLED,database="postgres",production=True)

@app.route("/line-mapping")
def line_mapping(): return redirect("/admin")

@app.route("/webhook",methods=["POST"])
def webhook():
    body=request.get_data()
    if not valid_line_signature(body): return "Invalid signature",400
    payload=request.get_json(silent=True) or {}
    for event in payload.get("events",[]):
        luid=(event.get("source") or {}).get("userId"); reply_token=event.get("replyToken")
        if not luid or event.get("type")!="message" or (event.get("message") or {}).get("type")!="text": continue
        text=(event["message"].get("text") or "").strip(); reply="พิมพ์ สถานะ หรือใช้รหัสจากหน้าจอง เช่น ผูก ABCD2345"
        if text.startswith("ผูก "):
            code=text[4:].strip().upper(); code_hash=hashlib.sha256(code.encode()).hexdigest()
            with conn() as c:
                link=c.execute("SELECT llc.id,llc.user_id,u.student_id,u.line_user_id FROM line_link_codes llc JOIN users u ON u.id=llc.user_id WHERE llc.code_hash=%s AND llc.used_at IS NULL AND llc.expires_at>now() FOR UPDATE",(code_hash,)).fetchone(); existing=c.execute("SELECT student_id FROM users WHERE line_user_id=%s",(luid,)).fetchone()
                if not link: reply="รหัสไม่ถูกต้อง หมดอายุ หรือถูกใช้แล้ว กรุณาจองใหม่เพื่อรับรหัสใหม่"
                elif existing and existing["student_id"]!=link["student_id"]: reply="LINE นี้เชื่อมกับผู้ใช้อื่นอยู่แล้ว กรุณาติดต่อเจ้าหน้าที่"
                elif link["line_user_id"] and link["line_user_id"]!=luid: reply="บัญชีผู้ใช้นี้เชื่อม LINE อื่นอยู่แล้ว กรุณาติดต่อเจ้าหน้าที่"
                else:
                    c.execute("UPDATE users SET line_user_id=%s WHERE id=%s",(luid,link["user_id"])); c.execute("UPDATE line_link_codes SET used_at=now() WHERE id=%s",(link["id"],)); reply="เชื่อมบัญชีสำเร็จ ระบบจะส่งการแจ้งเตือนมาที่ LINE นี้"
        elif text.lower() in {"สถานะ","status"}:
            with conn() as c: u=c.execute("SELECT student_id FROM users WHERE line_user_id=%s",(luid,)).fetchone()
            reply=("เชื่อมบัญชีแล้ว: "+u["student_id"]) if u else "ยังไม่ได้เชื่อมบัญชี กรุณาจองผ่านเว็บไซต์เพื่อรับรหัสเชื่อมบัญชี"
        if not reply_line(reply_token,reply): notifier().send(luid,reply)
    return "OK",200

@app.route("/health")
def health():
    db=False
    try:
        with conn() as c: db=c.execute("SELECT 1 AS ok").fetchone()["ok"]==1
    except Exception: pass
    return jsonify(status="ok" if db else "degraded",database=db,line_enabled=LINE_ENABLED,admin_configured=bool(ADMIN_PASSWORD_HASH or ADMIN_PASSWORD)),(200 if db else 503)

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)))