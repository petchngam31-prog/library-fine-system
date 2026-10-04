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
from werkzeug.security import check_password_hash
from line_notify import LineNotifier
DATABASE_URL=os.environ.get('DATABASE_URL',''); FINE_RATE=50; BANGKOK=ZoneInfo('Asia/Bangkok')
LINE_TOKEN=os.environ.get('LINE_CHANNEL_ACCESS_TOKEN',''); LINE_SECRET=os.environ.get('LINE_CHANNEL_SECRET',''); LINE_ENABLED=bool(LINE_TOKEN and LINE_SECRET)
ADMIN_PASSWORD_HASH=os.environ.get('ADMIN_PASSWORD_HASH',''); ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD',''); CRON_SECRET=os.environ.get('CRON_SECRET','')
app=Flask(__name__); app.secret_key=os.environ.get('FLASK_SECRET_KEY') or os.urandom(32); app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True)
def conn():
    if not DATABASE_URL: raise RuntimeError('DATABASE_URL is required')
    return psycopg.connect(DATABASE_URL,row_factory=dict_row,connect_timeout=10)
def today_bkk(): return datetime.now(BANGKOK).date()
def business_days_late(due,returned=None):
    if isinstance(due,str): due=date.fromisoformat(due)
    end=date.fromisoformat(returned) if isinstance(returned,str) else (returned or today_bkk())
    if end<=due:return 0
    cur=due+timedelta(days=1);days=0
    while cur<=end:
        if cur.weekday()<5:days+=1
        cur+=timedelta(days=1)
    return days
def fine(due,returned=None): days=business_days_late(due,returned);return days,days*FINE_RATE
def valid_line_signature(body):
    sig=request.headers.get('X-Line-Signature','')
    if not LINE_SECRET or not sig:return False
    expected=base64.b64encode(hmac.new(LINE_SECRET.encode(),body,hashlib.sha256).digest()).decode();return hmac.compare_digest(expected,sig)
def notifier():return LineNotifier(channel_access_token=LINE_TOKEN,dry_run=not LINE_ENABLED)
def reply_line(token,text):
    if not LINE_ENABLED or not token:return False
    import requests
    return requests.post('https://api.line.me/v2/bot/message/reply',headers={'Authorization':f'Bearer {LINE_TOKEN}','Content-Type':'application/json'},json={'replyToken':token,'messages':[{'type':'text','text':text}]},timeout=10).status_code==200
def admin_ok(p):
    if ADMIN_PASSWORD_HASH:return check_password_hash(ADMIN_PASSWORD_HASH,p)
    return bool(ADMIN_PASSWORD) and hmac.compare_digest(ADMIN_PASSWORD,p)
def issue_code(c,uid):
    code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8));ch=hashlib.sha256(code.encode()).hexdigest();c.execute('UPDATE line_link_codes SET used_at=now() WHERE user_id=%s AND used_at IS NULL',(uid,));c.execute("INSERT INTO line_link_codes(user_id,code_hash,expires_at) VALUES(%s,%s,now()+interval '15 minutes')",(uid,ch));session['challenge_uid']=uid;session['challenge_hash']=ch;return code
def run_overdue_check():
    with conn() as c:
        rows=c.execute('SELECT br.id AS record_id,br.due_date,br.notified,u.name AS full_name,u.line_user_id,e.name AS equipment_name FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN equipment e ON e.id=br.equipment_id WHERE br.return_date IS NULL').fetchall();sent=overdue=0;n=notifier()
        for r in rows:
            days,amount=fine(r['due_date'])
            if days<=0:continue
            overdue+=1
            if r['notified'] or not r['line_user_id']:continue
            result=n.send(r['line_user_id'],n.build_overdue_message(r['full_name'],r['equipment_name'],str(r['due_date']),days,amount))
            if result.success:sent+=1;c.execute('UPDATE borrow_records SET notified=true WHERE id=%s',(r['record_id'],))
    return overdue,sent
@app.after_request
def headers(r):r.headers['X-Content-Type-Options']='nosniff';r.headers['X-Frame-Options']='SAMEORIGIN';r.headers['Referrer-Policy']='same-origin';r.headers['Cache-Control']='no-store';return r
@app.route('/')
@app.route('/booking')
@app.route('/booking.html')
def booking():return render_template('booking.html')
@app.route('/history')
@app.route('/history.html')
def history():return render_template('history.html')
@app.route('/admin',methods=['GET','POST'])
@app.route('/index.html',methods=['GET','POST'])
def admin():
    error=''
    if request.method=='POST':
        if admin_ok(request.form.get('password','')):session.clear();session['is_admin']=True;return redirect(url_for('admin'))
        error='รหัสผ่านไม่ถูกต้อง กรุณาลองอีกครั้ง'
    if session.get('is_admin'):return render_template('index.html')
    return render_template('admin_login.html',error=error)
@app.route('/logout')
def logout():session.clear();return redirect('/')
@app.route('/api/equipment')
def api_equipment():
    with conn() as c:rows=c.execute('SELECT id AS equipment_id,name AS equipment_name,category,status FROM equipment ORDER BY id').fetchall()
    return jsonify(equipment=rows)
@app.route('/api/line/start',methods=['POST'])
def line_start():
    d=request.get_json(silent=True) or {};sid=str(d.get('student_id','')).strip().upper();name=str(d.get('name','')).strip()
    if not sid or len(sid)>50:return jsonify(message='กรุณากรอกรหัสผู้ยืม'),400
    with conn() as c:
        u=c.execute('SELECT id,name,line_user_id FROM users WHERE student_id=%s',(sid,)).fetchone()
        if not u:
            if not name or len(name)>200:return jsonify(message='ผู้ใช้ใหม่กรุณากรอกชื่อ-นามสกุล'),400
            u=c.execute('INSERT INTO users(student_id,name) VALUES(%s,%s) RETURNING id,name,line_user_id',(sid,name)).fetchone()
        code=issue_code(c,u['id']);linked=bool(u['line_user_id'])
    session.pop('verified_user_id',None);session['student_id']=sid
    return jsonify(line_linked=linked,line_code=code,line_instruction=('ยืนยัน '+code if linked else 'ผูก '+code))
@app.route('/api/line/verify')
def line_verify():
    uid=session.get('challenge_uid');ch=session.get('challenge_hash')
    if not uid or not ch:return jsonify(verified=False)
    with conn() as c:row=c.execute('SELECT llc.used_at,u.line_user_id,u.student_id FROM line_link_codes llc JOIN users u ON u.id=llc.user_id WHERE llc.user_id=%s AND llc.code_hash=%s',(uid,ch)).fetchone()
    ok=bool(row and row['used_at'] and row['line_user_id'])
    if ok:session['verified_user_id']=uid;session['student_id']=row['student_id'];session.pop('challenge_uid',None);session.pop('challenge_hash',None)
    return jsonify(verified=ok)
@app.route('/api/book',methods=['POST'])
def api_book():
    uid=session.get('verified_user_id')
    if not uid:return jsonify(message='กรุณายืนยันตัวตนผ่าน LINE ก่อนจอง'),401
    d=request.get_json(silent=True) or {};start=d.get('start_date');end=d.get('end_date');raw=d.get('equipment_ids') or []
    try:
        sd=date.fromisoformat(start);ed=date.fromisoformat(end);eids=list(dict.fromkeys(int(x) for x in raw))
        if not eids or ed<sd or sd<today_bkk() or any(x not in range(1,7) for x in eids):raise ValueError
    except Exception:return jsonify(message='รูปแบบข้อมูลหรือวันที่ไม่ถูกต้อง'),400
    with conn() as c:
        u=c.execute('SELECT line_user_id FROM users WHERE id=%s',(uid,)).fetchone()
        if not u or not u['line_user_id']:return jsonify(message='กรุณายืนยัน LINE ใหม่'),401
        for eid in eids:
            if c.execute('SELECT 1 FROM borrow_records WHERE equipment_id=%s AND return_date IS NULL AND borrow_date<=%s AND due_date>=%s',(eid,ed,sd)).fetchone():return jsonify(message=f'อุปกรณ์หมายเลข {eid} ถูกจองในช่วงเวลาดังกล่าวแล้ว'),400
        for eid in eids:c.execute('INSERT INTO borrow_records(user_id,equipment_id,borrow_date,due_date,purpose) VALUES(%s,%s,%s,%s,%s)',(uid,eid,sd,ed,str(d.get('purpose',''))[:500]))
    return jsonify(message='บันทึกการจองสำเร็จ')
@app.route('/api/admin/users',methods=['GET'])
def admin_users():
    if not session.get('is_admin'):return jsonify(message='Unauthorized'),401
    with conn() as c:return jsonify(users=c.execute('SELECT id,student_id,name,(line_user_id IS NOT NULL) AS line_linked,created_at FROM users ORDER BY student_id').fetchall())
@app.route('/api/records')
def records():
    if not session.get('is_admin'):return jsonify(message='Unauthorized'),401
    with conn() as c:rows=c.execute('SELECT br.id AS record_id,br.*,u.name AS full_name,u.student_id,u.line_user_id,e.name AS equipment_name FROM borrow_records br JOIN users u ON u.id=br.user_id JOIN equipment e ON e.id=br.equipment_id ORDER BY br.id DESC').fetchall()
    out=[]
    for x in rows:x=dict(x);days,amount=fine(x['due_date'],x['return_date']);x['days_late']=days;x['fine_amount']=x['fine'] if x['fine_paid'] else amount;x['is_overdue']=days>0 and not x['return_date'];out.append(x)
    return jsonify(records=out)
@app.route('/api/return/<int:rid>',methods=['POST'])
def return_record(rid):
    if not session.get('is_admin'):return jsonify(message='Unauthorized'),401
    with conn() as c:
        row=c.execute('SELECT due_date,return_date FROM borrow_records WHERE id=%s',(rid,)).fetchone()
        if not row:return jsonify(message='ไม่พบรายการ'),404
        if row['return_date']:return jsonify(message='รายการนี้รับคืนแล้ว'),400
        today=today_bkk();days,amount=fine(row['due_date'],today);c.execute('UPDATE borrow_records SET return_date=%s,fine=%s WHERE id=%s',(today,amount,rid))
    return jsonify(message='รับคืนสำเร็จ',fine_amount=amount,days_late=days)
@app.route('/api/pay-fine/<int:rid>',methods=['POST'])
def pay_fine(rid):
    if not session.get('is_admin'):return jsonify(message='Unauthorized'),401
    with conn() as c:c.execute('UPDATE borrow_records SET fine_paid=true WHERE id=%s',(rid,))
    return jsonify(message='บันทึกชำระค่าปรับแล้ว')
@app.route('/api/check',methods=['POST'])
def check():
    if not session.get('is_admin'):return jsonify(message='Unauthorized'),401
    overdue,sent=run_overdue_check();return jsonify(overdue_count=overdue,notified_count=sent)
@app.route('/api/cron/check',methods=['POST'])
def cron_check():
    supplied=request.headers.get('X-Cron-Secret','')
    if not CRON_SECRET or not hmac.compare_digest(supplied,CRON_SECRET):return jsonify(message='Unauthorized'),401
    overdue,sent=run_overdue_check();return jsonify(ok=True,overdue_count=overdue,notified_count=sent)
@app.route('/api/history')
@app.route('/api/user-history')
def api_history():
    uid=session.get('verified_user_id')
    if not uid:return jsonify(message='กรุณายืนยันผ่าน LINE ก่อนดูประวัติ',records=[]),401
    with conn() as c:rows=c.execute('SELECT br.id AS record_id,br.borrow_date,br.due_date,br.return_date,br.fine AS fine_amount,e.name AS equipment_name FROM borrow_records br JOIN equipment e ON e.id=br.equipment_id WHERE br.user_id=%s ORDER BY br.id DESC',(uid,)).fetchall()
    return jsonify(records=rows)
@app.route('/line/status')
def line_status():return jsonify(enabled=LINE_ENABLED,database='postgres',production=True)
@app.route('/webhook',methods=['POST'])
def webhook():
    body=request.get_data()
    if not valid_line_signature(body):return 'Invalid signature',400
    for event in (request.get_json(silent=True) or {}).get('events',[]):
        luid=(event.get('source') or {}).get('userId');token=event.get('replyToken')
        if not luid or event.get('type')!='message' or (event.get('message') or {}).get('type')!='text':continue
        text=(event['message'].get('text') or '').strip();parts=text.split(maxsplit=1);cmd=parts[0] if parts else '';code=parts[1].strip().upper() if len(parts)>1 else '';reply='พิมพ์ สถานะ หรือใช้ข้อความยืนยันจากเว็บไซต์'
        if cmd in {'ผูก','ยืนยัน'} and code:
            ch=hashlib.sha256(code.encode()).hexdigest()
            with conn() as c:
                link=c.execute('SELECT llc.id,llc.user_id,u.student_id,u.line_user_id FROM line_link_codes llc JOIN users u ON u.id=llc.user_id WHERE llc.code_hash=%s AND llc.used_at IS NULL AND llc.expires_at>now() FOR UPDATE',(ch,)).fetchone();existing=c.execute('SELECT student_id FROM users WHERE line_user_id=%s',(luid,)).fetchone()
                if not link:reply='รหัสไม่ถูกต้องหรือหมดอายุ กรุณาขอรหัสใหม่จากเว็บไซต์'
                elif cmd=='ยืนยัน' and link['line_user_id']!=luid:reply='LINE นี้ไม่ตรงกับบัญชีผู้ยืม'
                elif cmd=='ผูก' and existing and existing['student_id']!=link['student_id']:reply='LINE นี้เชื่อมกับผู้ใช้อื่นอยู่แล้ว กรุณาติดต่อเจ้าหน้าที่'
                elif cmd=='ผูก' and link['line_user_id'] and link['line_user_id']!=luid:reply='บัญชีนี้เชื่อม LINE อื่นอยู่แล้ว กรุณาติดต่อเจ้าหน้าที่'
                else:
                    if cmd=='ผูก':c.execute('UPDATE users SET line_user_id=%s WHERE id=%s',(luid,link['user_id']))
                    c.execute('UPDATE line_link_codes SET used_at=now() WHERE id=%s',(link['id'],));reply='ยืนยันตัวตนสำเร็จ กลับไปที่เว็บไซต์เพื่อจองได้เลย'
        elif text.lower() in {'สถานะ','status'}:
            with conn() as c:u=c.execute('SELECT student_id FROM users WHERE line_user_id=%s',(luid,)).fetchone()
            reply=('เชื่อมบัญชีแล้ว: '+u['student_id']) if u else 'ยังไม่ได้เชื่อมบัญชี กรุณาเริ่มจากเว็บไซต์'
        if not reply_line(token,reply):notifier().send(luid,reply)
    return 'OK',200
@app.route('/health')
def health():
    db=False
    try:
        with conn() as c:db=c.execute('SELECT 1 AS ok').fetchone()['ok']==1
    except Exception:pass
    return jsonify(status='ok' if db else 'degraded',database=db,line_enabled=LINE_ENABLED,admin_configured=bool(ADMIN_PASSWORD_HASH or ADMIN_PASSWORD),cron_configured=bool(CRON_SECRET)),(200 if db else 503)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))