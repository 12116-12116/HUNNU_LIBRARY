import json
import random
import datetime
import threading
import time
import requests
import urllib3
import re
import uuid
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

COOKIES_BY_CLIENT = {}
SCHEDULED_JOBS = {}
SCHEDULED_RESULTS = {}

def cookie_header_from_list(arr):
    best_idx = {}
    for i, c in enumerate(arr or []):
        name = (c.get('name') or '').strip()
        value = (c.get('value') or '').strip()
        if not name or not value:
            continue
        domain = (c.get('domain') or '').strip().lower()
        score = 0
        if domain == 'libwx.hunnu.edu.cn':
            score = 2
        elif domain == '.libwx.hunnu.edu.cn':
            score = 1
        prev = best_idx.get(name)
        if prev is None or score > prev[0] or (score == prev[0] and i > prev[1]):
            best_idx[name] = (score, i, value)
    out = []
    seen = set()
    for i, c in enumerate(arr or []):
        name = (c.get('name') or '').strip()
        if not name or name in seen:
            continue
        chosen = best_idx.get(name)
        if chosen and chosen[1] == i:
            out.append(f"{name}={chosen[2]}")
            seen.add(name)
    for name, (_, i, value) in best_idx.items():
        if name not in seen:
            out.append(f"{name}={value}")
            seen.add(name)
    return '; '.join(out)

def load_cookie_header(client_id=None):
    if client_id and client_id in COOKIES_BY_CLIENT:
        arr = COOKIES_BY_CLIENT[client_id]
        return cookie_header_from_list(arr)
    try:
        cookies = json.load(open('cookies.json','r',encoding='utf-8'))
        return cookie_header_from_list(cookies)
    except Exception:
        return ''

def is_occupied_msg(msg):
    m = (msg or '')
    return ('被预约' in m) or ('已有预约' in m) or ('已被预约' in m)

def infer_recommend_params(seatno, seatdate):
    sn = (seatno or '').upper()
    areacode = 'HUNNU_ELB'
    prefix = ''
    if sn.startswith('NY01'):
        areacode = 'HUNNU_NY'
        prefix = 'NY01'
    elif sn.startswith('THP'):
        areacode = 'HUNNU_THP'
        prefix = 'THP'
    elif sn.startswith('X'):
        areacode = 'HUNNU_XYH'
        prefix = 'X'
    elif sn.startswith('Z'):
        areacode = 'HUNNU_ELB'
        prefix = 'Z'
    addresscode = ''
    if prefix:
        m = re.match(prefix + r"(\d{3})", sn)
        addresscode = prefix + (m.group(1) if m else '')
    return {'data_type':'GetTuiJianSeat','areacode':areacode,'addresscode':addresscode,'seatdate':seatdate}

def read_seat_preferences():
    prefs = []
    with open('seat_preferences.txt','r',encoding='utf-8') as f:
        txt = f.read()
        for token in txt.replace(',', ' ').split():
            t = token.strip()
            if t:
                prefs.append(t)
    return prefs

def conflict_with_range(show, dt):
    t = (show or '').strip()
    if not t or t == '暂无预约':
        return False
    try:
        parts = t.split('-')
        if len(parts) != 2:
            return False
        def parse_one(x):
            hm = x.strip().split(':')
            return int(hm[0])*60+int(hm[1])
        s1 = parse_one(parts[0])
        e1 = parse_one(parts[1])
        s2 = int(dt[0])
        e2 = int(dt[1])
        return not (e2 <= s1 or s2 >= e1)
    except Exception:
        return True

def seat_date_request(session, headers, seatno, seatdate, dt):
    url = f'{BASE}/apim/seat/SeatDateHandler.ashx'
    params = {'data_type':'seatDate','seatno':seatno,'seatdate':seatdate,'datetime':f"{dt[0]},{dt[1]}"}
    
    # 增加自动重试机制：应对本地时间快于服务器时间导致"未到7点"被拒的情况
    for i in range(6):
        try:
            r = session.get(url, headers=headers, params=params, timeout=10)
            j = r.json()
            msg = j.get('msg', '') or ''
            # 如果是"时间未到"类错误，且不是最后一次尝试，则等待后重试
            if j.get('code') != 0 and '07:00' in msg and i < 5:
                time.sleep(0.5)
                continue
            return j
        except Exception:
            if i < 5:
                time.sleep(0.5)
                continue
            return {'code':-1,'msg':'接口返回异常','status':r.status_code if 'r' in locals() else 0, 'raw': str(e) if 'e' in locals() else ''}
    return {'code':-1,'msg':'重试多次失败'}

def do_booking(seatno, seatdate, dt, content, client_id):
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header(client_id)
    if content == 'prefs' and not seatno:
        try:
            prefs = read_seat_preferences()
            if not prefs:
                return {'code':-1,'msg':'偏好文件为空'}
            for code in prefs:
                j2 = seat_date_request(s, headers, code, seatdate, dt)
                if j2.get('code') == 0:
                    return {'code':0,'msg':'已使用偏好座位预约成功','seatno':code,'data':j2}
                if not is_occupied_msg(j2.get('msg','')):
                    return j2
            return {'code':-1,'msg':'偏好座位均不可用'}
        except Exception:
            return {'code':-1,'msg':'读取偏好文件失败'}
    j = seat_date_request(s, headers, seatno, seatdate, dt)
    if content == 'current':
        if j.get('code') == 0 or not is_occupied_msg(j.get('msg','')):
            return j
        try:
            url_rec = f'{BASE}/apim/seat/SeatInfoHandler.ashx'
            form = infer_recommend_params(seatno, seatdate)
            rrec = s.post(url_rec, headers=headers, data=form, timeout=10)
            jrec = rrec.json()
            seats = []
            if jrec.get('code') == 0:
                seats = json.loads(jrec.get('data','[]'))
            for it in seats:
                code = it.get('Code','')
                show = it.get('ShowDataTime','')
                if not code:
                    continue
                if conflict_with_range(show, dt):
                    continue
                j2 = seat_date_request(s, headers, code, seatdate, dt)
                if j2.get('code') == 0:
                    return {'code':0,'msg':'已使用推荐座位预约成功','seatno':code,'data':j2}
            return {'code':-1,'msg':'推荐座位尝试失败'}
        except Exception:
            return j
    if content == 'prefs':
        if j.get('code') == 0 or not is_occupied_msg(j.get('msg','')):
            return j
        try:
            prefs = read_seat_preferences()
            if not prefs:
                return {'code':-1,'msg':'偏好文件为空'}
            seen = {seatno} if seatno else set()
            for code in prefs:
                if code in seen:
                    continue
                seen.add(code)
                j2 = seat_date_request(s, headers, code, seatdate, dt)
                if j2.get('code') == 0:
                    return {'code':0,'msg':'已使用偏好座位预约成功','seatno':code,'data':j2}
                if not is_occupied_msg(j2.get('msg','')):
                    return j2
            return {'code':-1,'msg':'偏好座位均不可用'}
        except Exception:
            return {'code':-1,'msg':'读取偏好文件失败'}
    return j

def schedule_booking(job_id, target, payload, client_id):
    delay = (target - datetime.datetime.now()).total_seconds()
    run_seatdate = target.date().strftime('%Y-%m-%d')
    job = {
        'job_id': job_id,
        'client_id': client_id,
        'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'scheduled_for': target.strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'pending',
        'payload': {
            'seatno': payload.get('seatno', ''),
            'seatdate': payload.get('seatdate', ''),
            'seatdate_run': run_seatdate,
            'datetime': payload.get('datetime', [0, 0]),
            'content': payload.get('content', 'current'),
            'mode': payload.get('mode', ''),
        }
    }
    SCHEDULED_JOBS[job_id] = job

    def run_later():
        job['status'] = 'running'
        job['started_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            seatno = job['payload'].get('seatno', '')
            dt = job['payload'].get('datetime', [0, 0])
            content = job['payload'].get('content', 'current')
            seatdate = job['payload'].get('seatdate_run', run_seatdate)
            res = do_booking(seatno, seatdate, dt, content, client_id)
            job['status'] = 'done'
            job['finished_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            SCHEDULED_RESULTS[job_id] = res
        except Exception as e:
            job['status'] = 'failed'
            job['finished_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            SCHEDULED_RESULTS[job_id] = {'code': -1, 'msg': '定时任务执行异常', 'error': str(e)}

    timer = threading.Timer(max(0, delay), run_later)
    timer.daemon = False
    timer.start()
    SCHEDULED_JOBS[job_id]['timer_started'] = True
    return job

def make_session():
    s = requests.Session()
    s.verify = False
    s.trust_env = False
    return s

BASE = 'https://libwx.hunnu.edu.cn'
HEADERS = {
    'Host': 'libwx.hunnu.edu.cn',
    'Origin': 'https://libwx.hunnu.edu.cn',
    'Referer': 'https://libwx.hunnu.edu.cn/mobile/wxindex.aspx',
    'User-Agent': '7.0.5 WindowsWechat',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'X-Requested-With': 'XMLHttpRequest'
}

PAGE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>图书馆座位预约</title>
<style>
:root{--bg:#ffffff;--fg:#111111;--muted:#666666;--line:#e5e5e5;--accent:#222222}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,Segoe UI,Roboto,Helvetica,Arial}
.wrap{max-width:560px;margin:40px auto;padding:0 16px}
h2{font-size:18px;font-weight:600;margin:0 0 16px}
label{display:block;color:var(--muted);font-size:12px;letter-spacing:.02em;margin:16px 0 6px}
input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--fg);font-family:"Times New Roman", Times, serif}
input:focus{outline:none;border-color:#cfcfcf}
.row select{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--fg);font-family:"Times New Roman", Times, serif}
.row select:focus{outline:none;border-color:#cfcfcf}
.row{display:flex;gap:12px}
.row>.col{flex:1}
button{display:inline-block;padding:10px 16px;border:1px solid var(--line);border-radius:6px;background:var(--accent);color:#fff;letter-spacing:.02em}
button:hover{background:#000}
pre{margin:20px 0 0;padding:12px;border:1px solid var(--line);border-radius:6px;background:#fafafa;color:#222;white-space:pre-wrap}
</style>
</head>
<body>
<div class="wrap">
  <h2>图书馆座位预约</h2>
  
  <div class="row">
    <div class="col">
      <label>日期</label>
      <input id="date" type="date" />
    </div>
    <div class="col">
      <label>开始时间</label>
      <div class="row" style="gap:8px">
        <div class="col"><select id="startHour"></select></div>
        <div class="col"><select id="startMin"><option value="00">00</option><option value="30">30</option></select></div>
      </div>
    </div>
    <div class="col">
      <label>结束时间</label>
      <div class="row" style="gap:8px">
        <div class="col"><select id="endHour"></select></div>
        <div class="col"><select id="endMin"><option value="00">00</option><option value="30">30</option></select></div>
      </div>
    </div>
  </div>
  <label>阅览室</label>
  <input id="roomInput" placeholder="输入阅览室ID" />
  <label>座位</label>
  <input id="seatInput" placeholder="输入座位号" />
  <div class="row" style="margin-top:12px">
    <div class="col">
      <label>执行方式</label>
      <select id="mode">
        <option value="now">立即预约</option>
        <option value="next7">明日 07:00 执行</option>
        <option value="next7_normal">明日7点过几秒执行</option>
      </select>
    </div>
    <div class="col">
      <label>执行内容</label>
      <select id="content">
        <option value="current">当前页面输入</option>
        <option value="prefs">已储存的座位偏好</option>
      </select>
    </div>
  </div>
  <div style="margin-top:16px">
    <button onclick="book()">预约</button>
  </div>
  <pre id="out"></pre>
  <div style="margin-top:24px">
    <h2>账号信息查询</h2>
    <div class="row">
      <div class="col">
        <label>账号</label>
        <input id="userName" readonly />
      </div>
      <div class="col">
        <label>姓名</label>
        <input id="realName" readonly />
      </div>
    </div>
    <div style="margin-top:12px">
      <button onclick="loadUser()">查询账号</button>
    </div>
  </div>
  <div style="margin-top:24px">
    <h2>Cookie 管理</h2>
    <div class="row">
      <div class="col">
        <label>ASP.NET_SessionId</label>
        <input id="c_ASPNET_SessionId" placeholder="值" />
      </div>
    </div>
    <div class="row">
      <div class="col">
        <label>cookie_come_sno</label>
        <input id="c_cookie_come_sno" placeholder="值" />
      </div>
    </div>
    <div class="row">
      <div class="col">
        <label>cookie_come_timestamp</label>
        <input id="c_cookie_come_timestamp" placeholder="值" />
      </div>
    </div>
    <div class="row">
      <div class="col">
        <label>dt_cookie_user_name_remember</label>
        <input id="c_dt_cookie_user_name_remember" placeholder="值" />
      </div>
    </div>
    <div style="margin-top:12px">
      <button onclick="saveCookies()">保存 Cookie</button>
      <button style="margin-left:8px" onclick="loadCookies()">加载现有</button>
    </div>
  </div>
</div>
<script>
const cidKey='clientId';
let clientId=localStorage.getItem(cidKey)||((typeof crypto!=='undefined'&&crypto.randomUUID)?crypto.randomUUID():(Date.now().toString(36)+Math.random().toString(36).slice(2)));
localStorage.setItem(cidKey,clientId);
function fmtDate(d){const y=d.getFullYear();const m=('0'+(d.getMonth()+1)).slice(-2);const dd=('0'+d.getDate()).slice(-2);return `${y}-${m}-${dd}`}
const today=new Date();document.getElementById('date').value=fmtDate(today)
function fillHours(id,def,minH=7,maxH=22){const el=document.getElementById(id);el.innerHTML='';for(let h=minH;h<=maxH;h++){const o=document.createElement('option');o.value=('0'+h).slice(-2);o.text=('0'+h).slice(-2);el.appendChild(o)}el.value=('0'+def).slice(-2)}
fillHours('startHour',9,7,22);fillHours('endHour',10,7,22);document.getElementById('startMin').value='00';document.getElementById('endMin').value='00'

function noop(){}
document.getElementById('roomInput').addEventListener('change',noop);

function toMinutes(t){const [h,m]=t.split(':');return parseInt(h)*60+parseInt(m)}

let pollTimer=null;
async function book(){
  if(pollTimer){clearTimeout(pollTimer);pollTimer=null}
  const seatTyped=document.getElementById('seatInput').value.trim();
  const room=document.getElementById('roomInput').value.trim();
  let seat=seatTyped;
  if (room && seat && !/^Z\w+/.test(seat)) {
    seat = room + seat.replace(/\s+/g,'');
  }
  const date=document.getElementById('date').value;
  const start=parseInt(document.getElementById('startHour').value)*60+parseInt(document.getElementById('startMin').value);
  const end=parseInt(document.getElementById('endHour').value)*60+parseInt(document.getElementById('endMin').value);
  const mode=document.getElementById('mode').value;
  const content=document.getElementById('content').value;
  if (content==='current' && !seat) { document.getElementById('out').textContent=JSON.stringify({code:-1,msg:'座位号为空'},null,2); return }
  if (end<=start) { document.getElementById('out').textContent=JSON.stringify({code:-1,msg:'结束时间必须大于开始时间'},null,2); return }
  const r=await fetch('/api/book',{method:'POST',headers:{'Content-Type':'application/json','X-Client-Id':clientId},body:JSON.stringify({seatno:seat,seatdate:date,datetime:[start,end],mode,content})});
  const j=await r.json();
  document.getElementById('out').textContent=JSON.stringify(j,null,2);
  if(j.code===0 && j.job_id && j.scheduled_for){
    const target=new Date(j.scheduled_for.replace(/-/g,'/'));
    const now=new Date();
    const delay=target-now;
    if(delay>0){
      const out=document.getElementById('out');
      out.textContent+='\n\n[系统] 定时任务已创建，请保持页面开启，将在执行后自动更新结果...';
      const waitMs=Math.max(0,delay-60000);
      pollTimer=setTimeout(()=>startPolling(j.job_id),waitMs);
    }else{
      startPolling(j.job_id);
    }
  }
}
async function startPolling(jobId){
  const out=document.getElementById('out');
  const check=async()=>{
    try{
      const r=await fetch('/api/scheduled',{headers:{'X-Client-Id':clientId}});
      const jobs=await r.json();
      const job=jobs.find(x=>x.job_id===jobId);
      if(job && (job.status==='done'||job.status==='failed')){
        out.textContent=`[系统] 任务已执行 (状态: ${job.status})\n执行结果:\n`+JSON.stringify(job.result,null,2);
        pollTimer=null;
        return;
      }
    }catch(e){}
    pollTimer=setTimeout(check,2000);
  };
  check();
}

noop();
async function loadUser(){
  try{
    const r=await fetch('/api/user',{headers:{'X-Client-Id':clientId}});
    const j=await r.json();
    document.getElementById('userName').value=j.user_name||'';
    document.getElementById('realName').value=j.real_name||'';
  }catch(e){}
}
  async function loadCookies(){
    const r=await fetch('/api/cookies',{headers:{'X-Client-Id':clientId}});
    const j=await r.json();
    const m=j||{};
    document.getElementById('c_ASPNET_SessionId').value=m['ASP.NET_SessionId']||'';
    document.getElementById('c_cookie_come_sno').value=m['cookie_come_sno']||'';
    document.getElementById('c_cookie_come_timestamp').value=m['cookie_come_timestamp']||'';
    document.getElementById('c_dt_cookie_user_name_remember').value=m['dt_cookie_user_name_remember']||'';
  }
  async function saveCookies(){
    const payload={
      'ASP.NET_SessionId':document.getElementById('c_ASPNET_SessionId').value.trim(),
      'cookie_come_sno':document.getElementById('c_cookie_come_sno').value.trim(),
      'cookie_come_timestamp':document.getElementById('c_cookie_come_timestamp').value.trim(),
      'dt_cookie_user_name_remember':document.getElementById('c_dt_cookie_user_name_remember').value.trim(),
    };
    const r=await fetch('/api/cookies',{method:'POST',headers:{'Content-Type':'application/json','X-Client-Id':clientId},body:JSON.stringify(payload)});
    const j=await r.json();
    document.getElementById('out').textContent=JSON.stringify(j,null,2);
  }
</script>
</body>
</html>
"""

@app.get('/')
def index():
    return render_template_string(PAGE)

@app.get('/api/rooms')
def api_rooms():
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header(request.headers.get('X-Client-Id'))
    url = f'{BASE}/apim/seat/SeatAddressHandler.ashx'
    params = {'data_type':'list'}
    r = s.get(url, headers=headers, params=params, timeout=10)
    j = r.json()
    if j.get('code') == 0:
        return jsonify(json.loads(j['data']))
    return jsonify([])

@app.get('/api/seats')
def api_seats():
    room_id = request.args.get('room_id','')
    date = request.args.get('date','')
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header(request.headers.get('X-Client-Id'))
    url = f'{BASE}/apim/seat/SeatInfoHandler.ashx'
    params = {'data_type':'getMapPointInit','mapid':room_id}
    r = s.get(url, headers=headers, params=params, timeout=10)
    j = r.json()
    seats = []
    if j.get('code') == 0:
        data = json.loads(j['data'])
        seats = [x['SeatNo'] for x in data]
    return jsonify(seats)

@app.post('/api/book')
def api_book():
    payload = request.get_json(force=True)
    seatno = payload.get('seatno','')
    seatdate = payload.get('seatdate','')
    dt = payload.get('datetime',[0,0])
    mode = payload.get('mode','now')
    content = payload.get('content','current')
    client_id = request.headers.get('X-Client-Id')
    if mode == 'now':
        return jsonify(do_booking(seatno, seatdate, dt, content, client_id))
    elif mode == 'next7':
        now = datetime.datetime.now()
        target = (now + datetime.timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        job_id = uuid.uuid4().hex
        job = schedule_booking(job_id, target, payload, client_id)
        return jsonify({'code': 0, 'msg': '已安排在明日07:00执行', 'job_id': job_id, 'scheduled_for': job['scheduled_for'], 'seatdate_run': job['payload']['seatdate_run']})
    elif mode == 'next7_normal':
        now = datetime.datetime.now()
        base = (now + datetime.timedelta(days=1)).replace(hour=7, minute=0, second=5, microsecond=0)
        jitter = random.gauss(0, 1)
        target = base + datetime.timedelta(seconds=jitter)
        job_id = uuid.uuid4().hex
        job = schedule_booking(job_id, target, payload, client_id)
        return jsonify({'code': 0, 'msg': '已安排在明日7点过几秒执行', 'job_id': job_id, 'scheduled_for': job['scheduled_for'], 'jitter_seconds': jitter, 'distribution': 'normal(base=07:00:05,sigma=1s)', 'seatdate_run': job['payload']['seatdate_run']})
    else:
        return jsonify({'code':-1,'msg':'未知执行方式'})

@app.get('/api/scheduled')
def api_scheduled():
    cid = request.headers.get('X-Client-Id')
    jobs = []
    for job_id, job in SCHEDULED_JOBS.items():
        if cid and job.get('client_id') != cid:
            continue
        item = {
            'job_id': job_id,
            'scheduled_for': job.get('scheduled_for', ''),
            'created_at': job.get('created_at', ''),
            'status': job.get('status', ''),
            'payload': job.get('payload', {}),
        }
        if job_id in SCHEDULED_RESULTS:
            item['result'] = SCHEDULED_RESULTS[job_id]
        jobs.append(item)
    jobs.sort(key=lambda x: x.get('scheduled_for', ''))
    return jsonify(jobs)

@app.get('/api/verify')
def api_verify():
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header(request.headers.get('X-Client-Id'))
    # 尝试基础接口以判断登录态
    url1 = f'{BASE}/apim/basic/BasicHandler.ashx'
    r1 = s.get(url1, headers=headers, timeout=10)
    try:
        _ = r1.json()
        return jsonify({'ok': True, 'via': 'basic'})
    except Exception:
        url2 = f'{BASE}/apim/nav/NavHandler.ashx'
        r2 = s.get(url2, headers=headers, timeout=10)
        try:
            _ = r2.json()
            return jsonify({'ok': True, 'via': 'nav'})
        except Exception:
            raw1 = r1.text[:300]
            reason = 'session_expired' if '页面停留时间过长' in (raw1 or '') else 'unknown'
            return jsonify({'ok': False, 'status': r1.status_code, 'raw': raw1, 'reason': reason})

@app.get('/api/user')
def api_user():
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header(request.headers.get('X-Client-Id'))
    try:
        # 尝试 apim
        url1 = f'{BASE}/apim/user/UserHandler.ashx'
        r1 = s.get(url1, headers=headers, params={'data_type':'user_info'}, timeout=10)
        j1 = r1.json()
        if j1.get('code') == 0:
            data1 = json.loads(j1['data'])
            return jsonify({'user_name': data1.get('user_name',''), 'real_name': data1.get('real_name','')})
        # 回退到 mobile
        url2 = f'{BASE}/mobile/ajax/user/UserHandler.ashx'
        r2 = s.post(url2, headers=headers, data={'data_type':'user_info'}, timeout=10)
        j2 = r2.json()
        if j2.get('code') == 0:
            data2 = json.loads(j2['data'])
            return jsonify({'user_name': data2.get('user_name',''), 'real_name': data2.get('real_name','')})
    except Exception:
        pass
    return jsonify({'user_name':'', 'real_name':''})

@app.get('/api/cookies')
def api_cookies_get():
    cid = request.headers.get('X-Client-Id')
    if cid and cid in COOKIES_BY_CLIENT:
        arr = COOKIES_BY_CLIENT[cid]
        kv = {c['name']: c['value'] for c in arr}
        return jsonify(kv)
    try:
        arr = json.load(open('cookies.json','r',encoding='utf-8'))
        kv = {c['name']: c['value'] for c in arr}
        return jsonify(kv)
    except Exception:
        return jsonify({})

@app.post('/api/cookies')
def api_cookies_post():
    data = request.get_json(force=True)
    cid = request.headers.get('X-Client-Id')
    names = [
        'ASP.NET_SessionId',
        'cookie_come_sno',
        'cookie_come_timestamp',
        'dt_cookie_user_name_remember'
    ]
    out = []
    for n in names:
        v = (data.get(n,'') or '').strip()
        if not v:
            continue
        out.append({
            'domain': '.libwx.hunnu.edu.cn',
            'httpOnly': True if n in ('ASP.NET_SessionId','dt_cookie_user_name_remember','cookie_come_sno') else False,
            'name': n,
            'path': '/',
            'sameSite': 'Lax',
            'secure': True,
            'value': v
        })
        out.append({
            'domain': 'libwx.hunnu.edu.cn',
            'httpOnly': True if n in ('ASP.NET_SessionId','dt_cookie_user_name_remember','cookie_come_sno') else False,
            'name': n,
            'path': '/',
            'sameSite': 'Lax',
            'secure': False,
            'value': v
        })
    # 保留固定值的 cookie（不提供输入框）：cookie_unit_name、cookie_come_app
    try:
        arr_old = json.load(open('cookies.json','r',encoding='utf-8'))
        fixed = {'cookie_unit_name', 'cookie_come_app'}
        for c in arr_old:
            if c.get('name') in fixed:
                out.append(c)
    except Exception:
        pass
    if cid:
        COOKIES_BY_CLIENT[cid] = out
        return jsonify({'code':0,'msg':'已保存','count':len(out)})
    try:
        with open('cookies.json','w',encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return jsonify({'code':0,'msg':'已保存','count':len(out)})
    except Exception:
        return jsonify({'code':-1,'msg':'保存失败'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
