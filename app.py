import json, os, sqlite3, secrets, hashlib, csv, io, time, urllib.parse
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'polaris.db'
STATIC = ROOT / 'static'
SESSIONS = {}

ROLES = {
    'admin': ('admin123','Admin'),
    'logistics': ('log123','Logistics Officer'),
    'station': ('station123','Station Manager'),
    'researcher': ('res123','Researcher'),
}

def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def q1(sql, args=()):
    with conn() as c:
        r = c.execute(sql,args).fetchone()
        return dict(r) if r else None

def qall(sql,args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql,args).fetchall()]

def execsql(sql,args=()):
    with conn() as c:
        cur = c.execute(sql,args); c.commit(); return cur.lastrowid

def audit(actor, action, entity, entity_id='', details=''):
    execsql('INSERT INTO audit_log(ts,actor,action,entity,entity_id,details) VALUES(?,?,?,?,?,?)',
            (datetime.now().isoformat(timespec='seconds'),actor,action,entity,str(entity_id),details))

def setting(key, default=None):
    r=q1('SELECT value FROM settings WHERE key=?',(key,)); return r['value'] if r else default

def set_setting(key,val):
    with conn() as c:
        c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(val))); c.commit()

def init_db(reset=False):
    if reset and DB.exists(): DB.unlink()
    with conn() as c:
        c.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS missions(id TEXT PRIMARY KEY,name TEXT,station TEXT,status TEXT,priority TEXT);
        CREATE TABLE IF NOT EXISTS personnel(id TEXT PRIMARY KEY,name TEXT,role TEXT,location TEXT,status TEXT,medical_ready INTEGER);
        CREATE TABLE IF NOT EXISTS shipments(id TEXT PRIMARY KEY,mode TEXT,origin TEXT,destination TEXT,status TEXT,progress REAL,eta_days REAL,base_eta REAL,weather_delay REAL,last_update TEXT);
        CREATE TABLE IF NOT EXISTS cargo(id TEXT PRIMARY KEY,name TEXT,category TEXT,weight REAL,quantity REAL,unit TEXT,priority TEXT,origin TEXT,destination TEXT,location TEXT,status TEXT,transport TEXT,shipment_id TEXT,container_id TEXT,mission_id TEXT,inventory_item TEXT);
        CREATE TABLE IF NOT EXISTS cargo_events(id INTEGER PRIMARY KEY AUTOINCREMENT,cargo_id TEXT,ts TEXT,location TEXT,status TEXT,actor TEXT,note TEXT);
        CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY AUTOINCREMENT,station TEXT,item TEXT,qty REAL,unit TEXT,daily_usage REAL,reorder_threshold REAL,last_update TEXT, UNIQUE(station,item));
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,name TEXT,type TEXT,location TEXT,status TEXT,health REAL,runtime REAL,service_interval REAL,part_required TEXT,is_backup INTEGER);
        CREATE TABLE IF NOT EXISTS work_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,asset_id TEXT,created_at TEXT,status TEXT,reason TEXT,technician TEXT,part TEXT,plan TEXT);
        CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,severity TEXT,type TEXT,message TEXT,entity TEXT,entity_id TEXT,active INTEGER);
        CREATE TABLE IF NOT EXISTS emergencies(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,type TEXT,location TEXT,person TEXT,status TEXT,response_plan TEXT);
        CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,actor TEXT,action TEXT,entity TEXT,entity_id TEXT,details TEXT);
        CREATE TABLE IF NOT EXISTS comms(station TEXT PRIMARY KEY,status TEXT);
        ''')
        if c.execute('SELECT COUNT(*) n FROM missions').fetchone()['n']==0:
            c.executemany('INSERT INTO missions VALUES(?,?,?,?,?)',[
                ('CR-17','Climate Sensor Deployment','Bharati','On Track','High'),
                ('BIO-04','Polar Microbiology Survey','Maitri','On Track','Medium'),
                ('ATM-09','Atmospheric Observation','Bharati','On Track','High')])
            c.executemany('INSERT INTO personnel VALUES(?,?,?,?,?,?)',[
                ('P-001','Dr. Meera Iyer','Researcher','Bharati','Active',1),
                ('P-002','Arun Kumar','Technician','Bharati','Active',1),
                ('P-003','Dr. Nisha Rao','Medical Officer','Maitri','Active',1),
                ('P-004','Karthik S','Logistics Officer','Cape Town','Active',1),
                ('P-005','Ravi Menon','Vehicle Operator','Bharati','Active',1),
                ('P-006','Priya Das','Researcher','Maitri','Active',1),
                ('P-007','Sanjay Bose','Medical Assistant','Bharati','Active',1)])
            c.executemany('INSERT INTO shipments VALUES(?,?,?,?,?,?,?,?,?,?)',[
                ('SHP-001','SHIP','Cape Town','Bharati','In Transit',42,11,11,0,datetime.now().isoformat(timespec='seconds')),
                ('AIR-002','AIR','Cape Town','Maitri','Scheduled',0,3,3,0,datetime.now().isoformat(timespec='seconds'))])
            cargos=[
                ('PC-1024','Medical Oxygen','Medical',180,40,'units','Critical','Goa','Bharati','Cape Town','Loaded','SHIP','SHP-001','CNT-11','CR-17','Medical Oxygen'),
                ('PC-1088','Food & Rations','Food',620,500,'kg','Medium','Goa','Bharati','At Sea','In Transit','SHIP','SHP-001','CNT-12','ATM-09','Food & Rations'),
                ('PC-1121','Satellite Sensor','Research',75,1,'unit','High','Goa','Bharati','Cape Town','Loaded','AIR','AIR-002','CNT-15','CR-17',None),
                ('PC-1180','Oil Filter Kit','Spares',30,5,'units','High','Goa','Bharati','Bharati','Delivered','AIR',None,'CNT-03','ATM-09','Oil Filter Kit')]
            c.executemany('INSERT INTO cargo VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',cargos)
            now=datetime.now().isoformat(timespec='seconds')
            for x in cargos:
                c.execute('INSERT INTO cargo_events(cargo_id,ts,location,status,actor,note) VALUES(?,?,?,?,?,?)',(x[0],now,x[9],x[10],'Seed','Initial record'))
            inv=[
                ('Bharati','Medical Oxygen',30,'units',2,15,now),
                ('Bharati','Food & Rations',940,'kg',24,300,now),
                ('Bharati','Fuel',5200,'L',90,1200,now),
                ('Bharati','Oil Filter Kit',2,'units',0.03,1,now),
                ('Bharati','Medical Kit',8,'kits',0.08,2,now),
                ('Maitri','Medical Oxygen',55,'units',1.4,15,now),
                ('Maitri','Food & Rations',1300,'kg',26,300,now),
                ('Maitri','Fuel',6800,'L',95,1200,now),
                ('Maitri','Medical Kit',12,'kits',0.08,2,now)]
            c.executemany('INSERT INTO inventory(station,item,qty,unit,daily_usage,reorder_threshold,last_update) VALUES(?,?,?,?,?,?,?)',inv)
            c.executemany('INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)',[
                ('GEN-03','Main Generator','Generator','Bharati','Operational',84,2964,3000,'Oil Filter Kit',0),
                ('GEN-02','Backup Generator','Generator','Bharati','Standby',93,820,3000,'Oil Filter Kit',1),
                ('SV-03','Snow Vehicle','Vehicle','Bharati','Operational',88,1210,1500,'Oil Filter Kit',0),
                ('SV-07','Snow Vehicle','Vehicle','Maitri','Operational',91,860,1500,'Oil Filter Kit',0),
                ('COM-01','Satellite Terminal','Communication','Bharati','Operational',95,430,2000,None,0)])
            c.executemany('INSERT INTO comms VALUES(?,?)',[('Bharati','Online'),('Maitri','Online')])
            for k,v in {'sim_time':datetime.now().replace(microsecond=0).isoformat(),'sim_running':'0','tick_hours':'6'}.items():
                c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,v))
            c.commit()
    recalc_all('system')

def add_alert(severity, typ, message, entity='', entity_id=''):
    with conn() as c:
        exists=c.execute('SELECT id FROM alerts WHERE active=1 AND type=? AND entity_id=? AND message=?',(typ,str(entity_id),message)).fetchone()
        if not exists:
            c.execute('INSERT INTO alerts(ts,severity,type,message,entity,entity_id,active) VALUES(?,?,?,?,?,?,1)',(datetime.now().isoformat(timespec='seconds'),severity,typ,message,entity,str(entity_id))); c.commit()

def recalc_all(actor='system'):
    now=datetime.now().isoformat(timespec='seconds')
    with conn() as c:
        c.execute("UPDATE missions SET status='On Track'")
        for a in c.execute('SELECT * FROM assets').fetchall():
            due = a['runtime'] >= a['service_interval'] or a['health'] < 70 or a['status']=='Failed'
            if due:
                reason = 'Asset failed' if a['status']=='Failed' else 'Preventive maintenance due'
                exists=c.execute("SELECT id FROM work_orders WHERE asset_id=? AND status!='Closed'",(a['id'],)).fetchone()
                if not exists:
                    tech=c.execute("SELECT name FROM personnel WHERE role='Technician' AND location=? AND status='Active' LIMIT 1",(a['location'],)).fetchone()
                    tname=tech['name'] if tech else 'Unassigned'
                    plan=f"Inspect {a['id']} → isolate if required → use backup if available → replace {a['part_required'] or 'required component'} → test and return to service"
                    c.execute('INSERT INTO work_orders(asset_id,created_at,status,reason,technician,part,plan) VALUES(?,?,?,?,?,?,?)',(a['id'],now,'Open',reason,tname,a['part_required'],plan))
                msg=f"{a['id']} requires maintenance"
                ex=c.execute('SELECT id FROM alerts WHERE active=1 AND type=? AND entity_id=? AND message=?',('Maintenance',a['id'],msg)).fetchone()
                if not ex:c.execute('INSERT INTO alerts(ts,severity,type,message,entity,entity_id,active) VALUES(?,?,?,?,?,?,1)',(now,'High','Maintenance',msg,'Asset',a['id']))
        for r in c.execute('SELECT * FROM inventory').fetchall():
            if r['daily_usage']<=0: continue
            days=r['qty']/r['daily_usage']
            inc=c.execute("SELECT MIN(s.eta_days) eta FROM cargo cg JOIN shipments s ON cg.shipment_id=s.id WHERE cg.destination=? AND cg.inventory_item=? AND cg.status!='Delivered'",(r['station'],r['item'])).fetchone()
            eta=float(inc['eta']) if inc and inc['eta'] is not None else None
            msg=None; sev=None; typ=None
            if eta is not None and days < eta:
                gap=eta-days; sev='Critical';typ='Shortage';msg=f"{r['item']} at {r['station']} may run out {gap:.1f} days before resupply"
            elif r['qty'] <= r['reorder_threshold']:
                sev='Medium';typ='Low Stock';msg=f"{r['item']} at {r['station']} is below reorder threshold"
            if msg:
                eid=f"{r['station']}:{r['item']}"
                ex=c.execute('SELECT id FROM alerts WHERE active=1 AND type=? AND entity_id=? AND message=?',(typ,eid,msg)).fetchone()
                if not ex:c.execute('INSERT INTO alerts(ts,severity,type,message,entity,entity_id,active) VALUES(?,?,?,?,?,?,1)',(now,sev,typ,msg,'Inventory',eid))
        for cg in c.execute("SELECT * FROM cargo WHERE status IN ('Delayed','Held')").fetchall():
            if cg['mission_id']:
                c.execute("UPDATE missions SET status='At Risk' WHERE id=?",(cg['mission_id'],))
                msg=f"{cg['mission_id']} is at risk because {cg['id']} is {cg['status'].lower()}"
                ex=c.execute('SELECT id FROM alerts WHERE active=1 AND type=? AND entity_id=? AND message=?',('Mission Impact',cg['mission_id'],msg)).fetchone()
                if not ex:c.execute('INSERT INTO alerts(ts,severity,type,message,entity,entity_id,active) VALUES(?,?,?,?,?,?,1)',(now,'High','Mission Impact',msg,'Mission',cg['mission_id']))
        c.commit()

def compute_readiness():
    with conn() as c:
        personnel = c.execute("SELECT SUM(status='Active') a, COUNT(*) n FROM personnel").fetchone(); p=100*(personnel['a'] or 0)/(personnel['n'] or 1)
        ar=c.execute('SELECT health,status FROM assets').fetchall(); a=sum((r['health'] if r['status']!='Failed' else min(r['health'],35)) for r in ar)/max(len(ar),1)
        status_score={'Registered':40,'Received at Hub':55,'Loaded':70,'In Transit':82,'At Sea':82,'Arrived':92,'Delivered':100,'Delayed':35,'Held':25}
        cr=c.execute('SELECT status FROM cargo').fetchall(); cg=sum(status_score.get(r['status'],65) for r in cr)/max(len(cr),1)
        invrows=c.execute('SELECT qty,reorder_threshold FROM inventory').fetchall(); inv=sum(min(100,100*r['qty']/max(r['reorder_threshold']*2.5,1)) for r in invrows)/max(len(invrows),1)
        trans_score={'In Transit':100,'Scheduled':90,'Arrived':100,'Delayed':45,'Grounded':20}
        sr=c.execute('SELECT status FROM shipments').fetchall(); tr=sum(trans_score.get(r['status'],80) for r in sr)/max(len(sr),1)
    overall=.20*p+.20*a+.20*cg+.25*inv+.15*tr
    return {'overall':round(overall,1),'personnel':round(p,1),'assets':round(a,1),'cargo':round(cg,1),'inventory':round(inv,1),'transport':round(tr,1)}

def dashboard():
    recalc_all('system')
    rd=compute_readiness()
    with conn() as c:
        data={
            'readiness':rd,
            'sim_time':setting('sim_time'),
            'sim_running':setting('sim_running')=='1',
            'counts':{
                'personnel':c.execute('SELECT COUNT(*) n FROM personnel').fetchone()['n'],
                'cargo':c.execute('SELECT COUNT(*) n FROM cargo').fetchone()['n'],
                'assets':c.execute('SELECT COUNT(*) n FROM assets').fetchone()['n'],
                'alerts':c.execute('SELECT COUNT(*) n FROM alerts WHERE active=1').fetchone()['n']},
            'shipments':[dict(r) for r in c.execute('SELECT * FROM shipments ORDER BY id').fetchall()],
            'cargo':[dict(r) for r in c.execute('SELECT * FROM cargo ORDER BY id').fetchall()],
            'inventory':[dict(r) for r in c.execute('SELECT * FROM inventory ORDER BY station,item').fetchall()],
            'assets':[dict(r) for r in c.execute('SELECT * FROM assets ORDER BY location,id').fetchall()],
            'personnel':[dict(r) for r in c.execute('SELECT * FROM personnel ORDER BY location,role').fetchall()],
            'missions':[dict(r) for r in c.execute('SELECT * FROM missions ORDER BY id').fetchall()],
            'alerts':[dict(r) for r in c.execute('SELECT * FROM alerts WHERE active=1 ORDER BY id DESC LIMIT 12').fetchall()],
            'work_orders':[dict(r) for r in c.execute('SELECT * FROM work_orders ORDER BY id DESC LIMIT 8').fetchall()],
            'emergencies':[dict(r) for r in c.execute('SELECT * FROM emergencies ORDER BY id DESC LIMIT 6').fetchall()],
            'audit':[dict(r) for r in c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT 12').fetchall()]
        }
    # forecast enrichment
    for r in data['inventory']:
        r['days_remaining']=round(r['qty']/r['daily_usage'],1) if r['daily_usage']>0 else 999
        inc=q1('''SELECT MIN(s.eta_days) eta FROM cargo cg JOIN shipments s ON cg.shipment_id=s.id WHERE cg.destination=? AND cg.inventory_item=? AND cg.status!='Delivered' ''',(r['station'],r['item']))
        r['resupply_days']=round(float(inc['eta']),1) if inc and inc['eta'] is not None else None
        r['risk']='Critical' if r['resupply_days'] is not None and r['days_remaining']<r['resupply_days'] else ('Low' if r['qty']<=r['reorder_threshold'] else 'Safe')
    return data

def advance(hours=6, actor='system'):
    st=datetime.fromisoformat(setting('sim_time',datetime.now().isoformat())) + timedelta(hours=hours)
    set_setting('sim_time',st.isoformat(timespec='minutes'))
    days=hours/24
    with conn() as c:
        # move shipments and reduce ETA
        for s in c.execute("SELECT * FROM shipments WHERE status IN ('In Transit','Delayed')").fetchall():
            if s['status']=='In Transit':
                prog=min(100,s['progress'] + 100*days/max(s['eta_days'],0.5))
                eta=max(0,s['eta_days']-days)
                status='Arrived' if eta<=0 else 'In Transit'
                c.execute('UPDATE shipments SET progress=?,eta_days=?,status=?,last_update=? WHERE id=?',(prog,eta,status,st.isoformat(timespec='minutes'),s['id']))
                c.execute("UPDATE cargo SET location=?,status=? WHERE shipment_id=? AND status!='Delivered'",('At Sea' if status!='Arrived' else s['destination'],'In Transit' if status!='Arrived' else 'Arrived',s['id']))
            else:
                # delayed shipment holds ETA steady until cleared
                pass
        # consume inventory
        for r in c.execute('SELECT * FROM inventory').fetchall():
            nq=max(0,r['qty']-r['daily_usage']*days)
            c.execute('UPDATE inventory SET qty=?,last_update=? WHERE id=?',(nq,st.isoformat(timespec='minutes'),r['id']))
        # run assets
        for a in c.execute("SELECT * FROM assets WHERE status='Operational'").fetchall():
            rt=a['runtime']+hours
            health=max(0,a['health']-hours*0.015)
            c.execute('UPDATE assets SET runtime=?,health=? WHERE id=?',(rt,health,a['id']))
        c.commit()
    recalc_all(actor)
    audit(actor,'ADVANCE_SIM','Simulation','',f'{hours} hours')
    return dashboard()

def transport_recommend(weight, priority, category):
    p=priority.lower(); cat=category.lower()
    if weight>500: return {'mode':'SHIP','reason':'Heavy cargo exceeds practical air allocation for this prototype rule set.'}
    if p in ('critical','high') and weight<=100: return {'mode':'AIR','reason':'High-priority, low-weight cargo receives expedited air allocation.'}
    if cat in ('medical','emergency') and weight<=150: return {'mode':'AIR','reason':'Medical/emergency cargo is prioritized for faster air movement when weight allows.'}
    return {'mode':'SHIP','reason':'Standard cargo is consolidated by sea for capacity efficiency.'}

def handle_scan(payload,actor):
    cid=payload.get('cargo_id','').strip(); loc=payload.get('location','').strip(); note=payload.get('note','')
    cg=q1('SELECT * FROM cargo WHERE id=?',(cid,))
    if not cg: return {'ok':False,'error':'Cargo ID not found'},404
    status='Received'
    if loc in ('Goa','Cape Town'): status='Received at Hub'
    if loc=='Loaded on Vessel': loc='Cape Town'; status='Loaded'
    if loc in ('Maitri','Bharati'):
        status='Delivered'
    execsql('UPDATE cargo SET location=?,status=? WHERE id=?',(loc,status,cid))
    execsql('INSERT INTO cargo_events(cargo_id,ts,location,status,actor,note) VALUES(?,?,?,?,?,?)',(cid,datetime.now().isoformat(timespec='seconds'),loc,status,actor,note))
    if status=='Delivered' and cg.get('status')!='Delivered' and cg.get('inventory_item') and cg.get('quantity'):
        inv=q1('SELECT * FROM inventory WHERE station=? AND item=?',(loc,cg['inventory_item']))
        if inv:
            execsql('UPDATE inventory SET qty=qty+?,last_update=? WHERE id=?',(cg['quantity'],datetime.now().isoformat(timespec='seconds'),inv['id']))
        else:
            execsql('INSERT INTO inventory(station,item,qty,unit,daily_usage,reorder_threshold,last_update) VALUES(?,?,?,?,?,?,?)',(loc,cg['inventory_item'],cg['quantity'],cg['unit'],0,0,datetime.now().isoformat(timespec='seconds')))
    audit(actor,'SCAN_CARGO','Cargo',cid,f'{status} @ {loc}')
    recalc_all(actor)
    return {'ok':True,'cargo':q1('SELECT * FROM cargo WHERE id=?',(cid,))},200

def trigger_weather(actor):
    s=q1("SELECT * FROM shipments WHERE id='SHP-001'")
    delay=5
    execsql("UPDATE shipments SET status='Delayed',weather_delay=weather_delay+?,eta_days=eta_days+? WHERE id='SHP-001'",(delay,delay))
    execsql("UPDATE cargo SET status='Delayed' WHERE shipment_id='SHP-001' AND status!='Delivered'")
    add_alert('High','Weather','Severe Southern Ocean weather delayed SHP-001 by 5 days','Shipment','SHP-001')
    audit(actor,'TRIGGER_WEATHER','Shipment','SHP-001','+5 day delay')
    recalc_all(actor)
    return dashboard()

def clear_weather(actor):
    execsql("UPDATE shipments SET status='In Transit' WHERE id='SHP-001' AND status='Delayed'")
    execsql("UPDATE cargo SET status='In Transit' WHERE shipment_id='SHP-001' AND status='Delayed'")
    audit(actor,'CLEAR_WEATHER','Shipment','SHP-001','Resume transit')
    return dashboard()

def fail_asset(actor, asset_id='GEN-03'):
    a=q1('SELECT * FROM assets WHERE id=?',(asset_id,))
    if not a: return {'ok':False,'error':'Asset not found'},404
    execsql("UPDATE assets SET status='Failed',health=35 WHERE id=?",(asset_id,))
    backup=q1("SELECT * FROM assets WHERE location=? AND type=? AND is_backup=1 AND status IN ('Standby','Operational') LIMIT 1",(a['location'],a['type']))
    tech=q1("SELECT * FROM personnel WHERE role='Technician' AND location=? AND status='Active' LIMIT 1",(a['location'],))
    part=q1('SELECT * FROM inventory WHERE station=? AND item=?',(a['location'],a['part_required'])) if a['part_required'] else None
    steps=[]
    if backup: steps.append(f"Activate backup {backup['id']} ({backup['name']})")
    steps.append(f"Assign technician {tech['name'] if tech else 'UNAVAILABLE'}")
    if a['part_required']: steps.append(f"Reserve {a['part_required']} ({part['qty'] if part else 0} available)")
    steps += ['Isolate failed asset','Repair and functional test','Return primary asset to service']
    recalc_all(actor)
    audit(actor,'FAIL_ASSET','Asset',asset_id,' | '.join(steps))
    return {'ok':True,'plan':steps,'backup':backup,'technician':tech,'part':part,'dashboard':dashboard()},200

def emergency(actor, typ, location, person):
    med=q1("SELECT * FROM personnel WHERE role IN ('Medical Officer','Medical Assistant') AND status='Active' ORDER BY (location=?) DESC LIMIT 1",(location,))
    veh=q1("SELECT * FROM assets WHERE type='Vehicle' AND location=? AND status='Operational' LIMIT 1",(location,))
    kit=q1("SELECT * FROM inventory WHERE station=? AND item='Medical Kit'",(location,))
    comm=q1('SELECT * FROM comms WHERE station=?',(location,))
    steps=[
        f"Dispatch medical responder: {med['name'] if med else 'No responder available'}",
        f"Assign transport: {veh['id'] if veh else 'No local vehicle available'}",
        f"Reserve medical kit: {kit['qty'] if kit else 0} available",
        f"Confirm satellite link: {comm['status'] if comm else 'Unknown'}",
        'Notify station manager and command centre',
        'Track incident until closure'
    ]
    eid=execsql('INSERT INTO emergencies(ts,type,location,person,status,response_plan) VALUES(?,?,?,?,?,?)',(datetime.now().isoformat(timespec='seconds'),typ,location,person,'Response Active',' | '.join(steps)))
    add_alert('Critical','Emergency',f'{typ} at {location}: {person}','Emergency',eid)
    audit(actor,'CREATE_EMERGENCY','Emergency',eid,' | '.join(steps))
    return {'ok':True,'id':eid,'plan':steps,'resources':{'medical':med,'vehicle':veh,'kit':kit,'comms':comm}},200

class H(BaseHTTPRequestHandler):
    server_version='POLARIS/2.0'
    def log_message(self,*args): pass
    def send_json(self,obj,status=200):
        b=json.dumps(obj,default=str).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def send_file(self,path,ctype):
        b=Path(path).read_bytes(); self.send_response(200); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def body(self):
        n=int(self.headers.get('Content-Length','0') or 0); raw=self.rfile.read(n) if n else b'{}'
        try:return json.loads(raw.decode() or '{}')
        except:return {}
    def session(self):
        cookie=self.headers.get('Cookie',''); sid=''
        for p in cookie.split(';'):
            if p.strip().startswith('sid='): sid=p.strip()[4:]
        return SESSIONS.get(sid)
    def actor(self):
        s=self.session(); return s['username'] if s else 'anonymous'
    def auth_required(self):
        if not self.session(): self.send_json({'ok':False,'error':'Unauthorized'},401); return False
        return True
    def role_required(self,*roles):
        s=self.session()
        if not s: self.send_json({'ok':False,'error':'Unauthorized'},401); return False
        if s['role'] not in roles: self.send_json({'ok':False,'error':f"Action not permitted for role: {s['role']}"},403); return False
        return True
    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/': return self.send_file(STATIC/'index.html','text/html; charset=utf-8')
        if path=='/static/app.js': return self.send_file(STATIC/'app.js','application/javascript; charset=utf-8')
        if path=='/static/style.css': return self.send_file(STATIC/'style.css','text/css; charset=utf-8')
        if path.startswith('/static/qr/') and path.endswith('.png'):
            fp=STATIC/'qr'/Path(path).name
            if fp.exists(): return self.send_file(fp,'image/png')
        if path=='/api/me': return self.send_json({'user':self.session()})
        if path=='/api/dashboard':
            if not self.auth_required(): return
            return self.send_json(dashboard())
        if path.startswith('/api/cargo/') and path.endswith('/history'):
            if not self.auth_required(): return
            cid=path.split('/')[3]; return self.send_json(qall('SELECT * FROM cargo_events WHERE cargo_id=? ORDER BY id DESC',(cid,)))
        if path=='/api/manifest.csv':
            if not self.auth_required(): return
            out=io.StringIO(); w=csv.writer(out); w.writerow(['Cargo ID','Name','Category','Weight','Qty','Unit','Priority','Origin','Destination','Location','Status','Transport','Shipment','Container','Mission'])
            for r in qall('SELECT * FROM cargo ORDER BY id'): w.writerow([r[k] for k in ['id','name','category','weight','quantity','unit','priority','origin','destination','location','status','transport','shipment_id','container_id','mission_id']])
            b=out.getvalue().encode(); self.send_response(200); self.send_header('Content-Type','text/csv'); self.send_header('Content-Disposition','attachment; filename=POLARIS_Cargo_Manifest.csv'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        self.send_error(404)
    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path; p=self.body()
        if path=='/api/login':
            u=p.get('username',''); pw=p.get('password','')
            if u in ROLES and secrets.compare_digest(ROLES[u][0],pw):
                sid=secrets.token_hex(24); SESSIONS[sid]={'username':u,'role':ROLES[u][1]}
                b=json.dumps({'ok':True,'user':SESSIONS[sid]}).encode(); self.send_response(200); self.send_header('Set-Cookie',f'sid={sid}; Path=/; HttpOnly; SameSite=Lax'); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); audit(u,'LOGIN','Session','',''); return
            return self.send_json({'ok':False,'error':'Invalid demo credentials'},401)
        if path=='/api/logout':
            s=self.session();
            if s: audit(s['username'],'LOGOUT','Session','','')
            self.send_response(200); self.send_header('Set-Cookie','sid=; Path=/; Max-Age=0'); self.end_headers(); return
        if not self.auth_required(): return
        actor=self.actor()
        if path=='/api/sim/advance':
            if not self.role_required('Admin'): return
            return self.send_json(advance(float(p.get('hours',6)),actor))
        if path=='/api/sim/run':
            if not self.role_required('Admin'): return
            set_setting('sim_running','1'); audit(actor,'RUN_SIM','Simulation','',''); return self.send_json({'ok':True})
        if path=='/api/sim/pause':
            if not self.role_required('Admin'): return
            set_setting('sim_running','0'); audit(actor,'PAUSE_SIM','Simulation','',''); return self.send_json({'ok':True})
        if path=='/api/sim/weather':
            if not self.role_required('Admin','Logistics Officer'): return
            return self.send_json(trigger_weather(actor))
        if path=='/api/sim/clear-weather':
            if not self.role_required('Admin','Logistics Officer'): return
            return self.send_json(clear_weather(actor))
        if path=='/api/sim/fail-asset':
            if not self.role_required('Admin','Station Manager'): return
            obj,code=fail_asset(actor,p.get('asset_id','GEN-03')); return self.send_json(obj,code)
        if path=='/api/sim/emergency':
            if not self.role_required('Admin','Station Manager','Researcher'): return
            obj,code=emergency(actor,p.get('type','Medical Emergency'),p.get('location','Bharati'),p.get('person','Expedition Member')); return self.send_json(obj,code)
        if path=='/api/cargo/scan':
            if not self.role_required('Admin','Logistics Officer','Station Manager'): return
            obj,code=handle_scan(p,actor); return self.send_json(obj,code)
        if path=='/api/cargo/add':
            if not self.role_required('Admin','Logistics Officer'): return
            req=['name','category','weight','quantity','unit','priority','origin','destination','mission_id']
            if any(str(p.get(k,'')).strip()=='' for k in req): return self.send_json({'ok':False,'error':'Fill all required cargo fields'},400)
            try: weight=float(p['weight']); qty=float(p['quantity'])
            except: return self.send_json({'ok':False,'error':'Weight/quantity must be numeric'},400)
            rec=transport_recommend(weight,p['priority'],p['category']); mode=p.get('transport') or rec['mode']
            n=q1("SELECT COUNT(*) n FROM cargo")['n']+1200; cid=f'PC-{n:04d}'
            shipment='AIR-002' if mode=='AIR' else 'SHP-001'
            execsql('''INSERT INTO cargo(id,name,category,weight,quantity,unit,priority,origin,destination,location,status,transport,shipment_id,container_id,mission_id,inventory_item)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cid,p['name'],p['category'],weight,qty,p['unit'],p['priority'],p['origin'],p['destination'],p['origin'],'Registered',mode,shipment,p.get('container_id','UNASSIGNED'),p['mission_id'],p.get('inventory_item') or None))
            execsql('INSERT INTO cargo_events(cargo_id,ts,location,status,actor,note) VALUES(?,?,?,?,?,?)',(cid,datetime.now().isoformat(timespec='seconds'),p['origin'],'Registered',actor,'Cargo created'))
            audit(actor,'CREATE_CARGO','Cargo',cid,f"Transport={mode}; {rec['reason']}")
            return self.send_json({'ok':True,'cargo_id':cid,'recommendation':rec,'transport':mode})
        if path=='/api/transport/recommend':
            try: weight=float(p.get('weight',0))
            except: weight=0
            return self.send_json(transport_recommend(weight,p.get('priority','Medium'),p.get('category','General')))
        if path=='/api/reset':
            if not self.role_required('Admin'): return
            init_db(reset=True); audit(actor,'RESET_DEMO','System','',''); return self.send_json({'ok':True})
        if path=='/api/alerts/ack':
            execsql('UPDATE alerts SET active=0 WHERE id=?',(p.get('id'),)); audit(actor,'ACK_ALERT','Alert',p.get('id'),''); return self.send_json({'ok':True})
        self.send_error(404)

if __name__=='__main__':
    init_db()
    print('POLARIS 2.0 running at http://127.0.0.1:8000')
    print('Demo login: admin / admin123')
    ThreadingHTTPServer(('127.0.0.1',8000),H).serve_forever()
