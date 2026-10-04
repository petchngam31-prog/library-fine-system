import os, sqlite3
from datetime import date, datetime
from flask import Flask, jsonify, redirect, render_template, render_template_string, request, session, url_for

DEMO_MODE = os.environ.get('DEMO_MODE', '1').lower() in {'1','true','yes','on'}
DB_PATH = os.environ.get('DATABASE_PATH', '/tmp/library_fine_demo.db')
FINE_RATE = 50

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')

EQUIPMENT = [
    (1, 'กล้อง Canon EOS R50', 'camera'),
    (2, 'ขาตั้งกล้อง Fancier', 'tripod'),
    (3, 'กล้องภาพนิ่ง Nikon D3300', 'camera'),
    (4, 'กล้องภาพนิ่ง Canon EOS 700D', 'camera'),
    (5, 'กล้องดิจิตอลวิดีโอ Panasonic HC-V700', 'video'),
    (6, 'ขาตั้งกล้อง Sony', 'tripod'),
]

def conn():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=conn()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL, student_id TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS equipment(equipment_id INTEGER PRIMARY KEY, equipment_name TEXT NOT NULL, category TEXT, status TEXT NOT NULL DEFAULT 'available');
    CREATE TABLE IF NOT EXISTS borrow_records(record_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,equipment_id INTEGER NOT NULL,borrow_date TEXT NOT NULL,due_date TEXT NOT NULL,return_date TEXT,fine_amount REAL NOT NULL DEFAULT 0,fine_paid INTEGER NOT NULL DEFAULT 0,notified INTEGER NOT NULL DEFAULT 0);
    ''')
    c.executemany('INSERT OR IGNORE INTO equipment(equipment_id,equipment_name,category) VALUES(?,?,?)', EQUIPMENT)
    c.executemany('INSERT OR IGNORE INTO users(full_name,student_id) VALUES(?,?)', [('ผู้ทดลอง A','00012345'),('ผู้ทดลอง B','00023456')])
    c.commit(); c.close()

def fine(due, returned=None):
    end=datetime.strptime(returned or date.today().isoformat(),'%Y-%m-%d').date(); d=datetime.strptime(due,'%Y-%m-%d').date()
    days=max((end-d).days,0); return days, days*FINE_RATE

@app.before_request
def ready(): init_db()

@app.after_request
def headers(r):
    r.headers['X-Content-Type-Options']='nosniff'; r.headers['X-Frame-Options']='SAMEORIGIN'; r.headers['Referrer-Policy']='same-origin'; return r

@app.route('/')
@app.route('/booking')
@app.route('/booking.html')
def booking(): return render_template('booking.html')

@app.route('/history')
@app.route('/history.html')
def history(): return render_template('history.html')

@app.route('/admin', methods=['GET','POST'])
@app.route('/index.html', methods=['GET','POST'])
def admin():
    if request.method=='POST': session['is_admin']=True; return redirect(url_for('admin'))
    if session.get('is_admin'): return render_template('index.html')
    return render_template_string('''<!doctype html><html lang="th"><meta charset="utf-8"><title>Demo Admin</title><link rel="stylesheet" href="/static/style.css"><body><main style="max-width:520px;margin:70px auto;padding:28px"><h2>โหมดทดลองเจ้าหน้าที่</h2><p>นี่เป็น Demo สาธารณะ ใช้ข้อมูลสมมติร่วมกัน และไม่ส่ง LINE จริง</p><form method="post"><button class="btn btn-amber" type="submit">เข้าสู่หน้าทดลองเจ้าหน้าที่</button></form><p><a href="/">กลับหน้าจอง</a></p></main></body></html>''')

@app.route('/logout')
def logout(): session.clear(); return redirect('/')

@app.route('/api/equipment')
def api_equipment():
    c=conn(); rows=c.execute('SELECT * FROM equipment ORDER BY equipment_id').fetchall(); c.close(); return jsonify(equipment=[dict(x) for x in rows])

@app.route('/api/book', methods=['POST'])
def api_book():
    d=request.get_json(silent=True) or {}; sid=str(d.get('user_id','')).strip(); eid=d.get('equipment_id'); start=d.get('start_date'); end=d.get('end_date')
    if not sid or not eid or not start or not end: return jsonify(message='กรุณากรอกข้อมูลให้ครบถ้วน'),400
    try:
        sd=datetime.strptime(start,'%Y-%m-%d').date(); ed=datetime.strptime(end,'%Y-%m-%d').date()
        if ed < sd: return jsonify(message='วันคืนต้องไม่ก่อนวันยืม'),400
        eid=int(eid)
    except Exception: return jsonify(message='รูปแบบข้อมูลไม่ถูกต้อง'),400
    c=conn()
    u=c.execute('SELECT user_id FROM users WHERE student_id=?',(sid,)).fetchone()
    if not u:
        c.execute('INSERT INTO users(full_name,student_id) VALUES(?,?)',(f'ผู้ทดลอง ({sid})',sid)); uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    else: uid=u['user_id']
    conflict=c.execute('SELECT 1 FROM borrow_records WHERE equipment_id=? AND return_date IS NULL AND borrow_date<=? AND due_date>=?',(eid,end,start)).fetchone()
    if conflict: c.close(); return jsonify(message='อุปกรณ์นี้ถูกจองในช่วงเวลาดังกล่าวแล้ว'),400
    c.execute('INSERT INTO borrow_records(user_id,equipment_id,borrow_date,due_date) VALUES(?,?,?,?)',(uid,eid,start,end)); c.commit(); c.close(); return jsonify(message='บันทึกการจอง Demo สำเร็จ'),200

@app.route('/api/records')
def records():
    if not session.get('is_admin'): return jsonify(message='Unauthorized'),401
    c=conn(); rows=c.execute('''SELECT br.*,u.full_name,u.student_id,e.equipment_name FROM borrow_records br JOIN users u ON u.user_id=br.user_id JOIN equipment e ON e.equipment_id=br.equipment_id ORDER BY br.record_id DESC''').fetchall(); out=[]
    for r in rows:
        x=dict(r); days,amount=fine(x['due_date'],x['return_date']); x['days_late']=days; x['fine_amount']=amount if not x['fine_paid'] else x['fine_amount']; x['is_overdue']=days>0 and not x['return_date']; out.append(x)
    c.close(); return jsonify(records=out)

@app.route('/api/return/<int:rid>', methods=['POST'])
def ret(rid):
    if not session.get('is_admin'): return jsonify(message='Unauthorized'),401
    c=conn(); r=c.execute('SELECT due_date,return_date FROM borrow_records WHERE record_id=?',(rid,)).fetchone()
    if not r: c.close(); return jsonify(message='ไม่พบรายการ'),404
    if r['return_date']: c.close(); return jsonify(message='รายการนี้รับคืนแล้ว'),400
    today=date.today().isoformat(); days,amount=fine(r['due_date'],today); c.execute('UPDATE borrow_records SET return_date=?,fine_amount=? WHERE record_id=?',(today,amount,rid)); c.commit(); c.close(); return jsonify(message='รับคืนสำเร็จ',fine_amount=amount,days_late=days)

@app.route('/api/pay-fine/<int:rid>', methods=['POST'])
def pay(rid):
    if not session.get('is_admin'): return jsonify(message='Unauthorized'),401
    c=conn(); c.execute('UPDATE borrow_records SET fine_paid=1 WHERE record_id=?',(rid,)); c.commit(); c.close(); return jsonify(message='บันทึกชำระค่าปรับ Demo แล้ว')

@app.route('/api/check', methods=['POST'])
def check():
    if not session.get('is_admin'): return jsonify(message='Unauthorized'),401
    return jsonify(message='Demo mode: ปิดการส่ง LINE จริง', notified_count=0)

@app.route('/api/history')
def api_history():
    sid=str(request.args.get('student_id') or request.args.get('user_id') or '').strip(); c=conn(); rows=c.execute('''SELECT br.*,e.equipment_name FROM borrow_records br JOIN users u ON u.user_id=br.user_id JOIN equipment e ON e.equipment_id=br.equipment_id WHERE u.student_id=? ORDER BY br.record_id DESC''',(sid,)).fetchall(); c.close(); return jsonify(records=[dict(x) for x in rows])

@app.route('/line/link', methods=['POST'])
def line_link(): return jsonify(success=False,message='Demo mode: ปิดการเชื่อม LINE'),403
@app.route('/line/status')
def line_status(): return jsonify(linked=False,demo=True)
@app.route('/line-mapping')
def line_mapping(): return redirect('/admin')
@app.route('/webhook', methods=['POST'])
def webhook(): return jsonify(message='Demo mode: LINE webhook disabled'),503
@app.route('/health')
def health(): return jsonify(status='ok',demo=True)

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5000')))
