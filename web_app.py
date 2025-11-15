import json
import datetime
import threading
import time
import requests
import urllib3
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

COOKIES_BY_CLIENT = {}

def load_cookie_header(client_id=None):
    if client_id and client_id in COOKIES_BY_CLIENT:
        arr = COOKIES_BY_CLIENT[client_id]
        return '; '.join([f"{c['name']}={c['value']}" for c in arr])
    try:
        cookies = json.load(open('cookies.json','r',encoding='utf-8'))
        return '; '.join([f"{c['name']}={c['value']}" for c in cookies])
    except Exception:
        return ''

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

async function book(){
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
  if (!seat) { document.getElementById('out').textContent=JSON.stringify({code:-1,msg:'座位号为空'},null,2); return }
  if (end<=start) { document.getElementById('out').textContent=JSON.stringify({code:-1,msg:'结束时间必须大于开始时间'},null,2); return }
  const r=await fetch('/api/book',{method:'POST',headers:{'Content-Type':'application/json','X-Client-Id':clientId},body:JSON.stringify({seatno:seat,seatdate:date,datetime:[start,end],mode})});
  const j=await r.json();
  document.getElementById('out').textContent=JSON.stringify(j,null,2);
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
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header(request.headers.get('X-Client-Id'))
    url = f'{BASE}/apim/seat/SeatDateHandler.ashx'
    params = {'data_type':'seatDate','seatno':seatno,'seatdate':seatdate,'datetime':f"{dt[0]},{dt[1]}"}
    if mode == 'now':
        r = s.get(url, headers=headers, params=params, timeout=10)
        try:
            j = r.json()
        except Exception:
            return jsonify({'code':-1,'msg':'接口返回异常','status':r.status_code,'content_type':r.headers.get('content-type',''), 'raw': r.text[:500]})
        return jsonify(j)
    elif mode == 'next7':
        now = datetime.datetime.now()
        target = (now + datetime.timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        delay = (target - now).total_seconds()
        def run_later():
            try:
                s2 = make_session()
                headers2 = dict(headers)
                r2 = s2.get(url, headers=headers2, params=params, timeout=10)
                # 无需返回，作为后台执行
            except Exception:
                pass
        timer = threading.Timer(max(0, delay), run_later)
        timer.daemon = True
        timer.start()
        return jsonify({'code':0,'msg':'已安排在明日07:00执行','scheduled_for': target.strftime('%Y-%m-%d %H:%M:%S'), 'seatno': seatno, 'seatdate': seatdate, 'datetime': dt})
    else:
        return jsonify({'code':-1,'msg':'未知执行方式'})

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
            return jsonify({'ok': False, 'status': r1.status_code, 'raw': r1.text[:300]})

@app.get('/api/user')
def api_user():
    s = make_session()
    headers = dict(HEADERS)
    headers['Cookie'] = load_cookie_header()
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