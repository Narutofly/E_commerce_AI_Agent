import hashlib
import hmac
import json
import secrets
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 150000).hex()


def password_ok(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)


def rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def db(self, write=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE,role TEXT,password TEXT,active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires TEXT);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),product TEXT,amount INTEGER,signed_at TEXT,logistics TEXT,simulated INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS policies(id TEXT PRIMARY KEY,title TEXT,body TEXT,version INTEGER);
            CREATE TABLE IF NOT EXISTS policy_versions(policy_id TEXT,version INTEGER,title TEXT,body TEXT,created_at TEXT,PRIMARY KEY(policy_id,version));
            CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),order_id TEXT REFERENCES orders(id),kind TEXT CHECK(kind IN ('return','exchange')),reason TEXT,status TEXT CHECK(status IN ('pending','approved','rejected','completed')),opinion TEXT,request_id TEXT,precheck TEXT,snapshot TEXT,created_at TEXT,updated_at TEXT,UNIQUE(user_id,request_id));
            CREATE UNIQUE INDEX IF NOT EXISTS one_active ON tickets(order_id) WHERE status IN ('pending','approved');
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT,action TEXT,target TEXT,detail TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),order_id TEXT REFERENCES orders(id),created_at TEXT);
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id TEXT REFERENCES conversations(id),role TEXT,content TEXT,mode TEXT,evidence TEXT,created_at TEXT);
            ''')
        with self.db(True) as db:
            # Preserve stable IDs and all foreign keys when normalizing demo accounts.
            changed = db.execute("SELECT value FROM meta WHERE key='auth_version'").fetchone() is None
            for uid, username, role, aliases in [('customer-demo','user','customer',('user1','student01')),('merchant-demo','admin','merchant',('teacher01',))]:
                row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
                if row is None:
                    row = db.execute('SELECT * FROM users WHERE username IN (?,?)', (aliases[0], aliases[-1])).fetchone()
                if row:
                    if row['username'] != username or row['role'] != role or not password_ok('123456',row['password']) or not row['active']:
                        db.execute('UPDATE users SET username=?,role=?,password=?,active=1 WHERE id=?',(username,role,password_hash('123456'),row['id']))
                        changed = True
                else:
                    db.execute('INSERT INTO users VALUES(?,?,?,?,1)', (uid,username,role,password_hash('123456')))
            if db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND username NOT IN ('user','admin')").fetchone()[0]:
                changed = True
            db.execute("UPDATE users SET active=0 WHERE username NOT IN ('user','admin')")
            if changed:
                db.execute('DELETE FROM sessions')
                db.execute("INSERT OR REPLACE INTO meta VALUES('auth_version','1')")
            db.execute('DELETE FROM sessions WHERE expires<?',(now(),))
            customer = db.execute("SELECT id FROM users WHERE username='user'").fetchone()[0]
            # Disabled fixture owner verifies isolation without a third login account.
            db.execute("INSERT OR IGNORE INTO users VALUES('fixture-owner','fixture-disabled','customer','disabled',0)")
            for oid, owner, product, amount, days, logistics in [('DEMO-1001',customer,'Nova 无线降噪耳机',59900,3,'已签收 · 模拟顺丰 SF1001001'),('DEMO-1002',customer,'Arc 便携机械键盘',39900,15,'已签收 · 模拟京东 JD1001002'),('DEMO-1003',customer,'Pixel 运动相机',129900,40,'已签收 · 模拟中通 ZT1001003'),('DEMO-OTHER','fixture-owner','隔离测试订单',10000,2,'模拟已签收')]:
                db.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?,?,1)',(oid,owner,product,amount,(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),logistics))
            for pid,title,body in [('returns','退货与换货','数码商品签收后7天内可申请退货，30天内可申请换货；超期仍可提交人工例外审核。请保留商品与配件，最终由商家审核。'),('shipping','运费与寄回','商品质量问题经商家核实后由商家承担合理寄回运费；非质量原因运费由买家承担。受理后等待客服确认寄回地址，不要自行寄送。'),('product','商品使用与售后','耳机请先检查蓝牙配对和充电状态；键盘请检查连接模式与电量；相机请检查存储卡和充电情况。无法解决可提交售后申请。受理和完成均为模拟状态，不代表退款到账。')]:
                db.execute('INSERT OR IGNORE INTO policies VALUES(?,?,?,1)',(pid,title,body))
                db.execute('INSERT OR IGNORE INTO policy_versions VALUES(?,1,?,?,?)',(pid,title,body,now()))
            try:
                db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS policy_fts USING fts5(id UNINDEXED,title,body,tokenize='trigram')")
                db.execute('DELETE FROM policy_fts')
                db.execute('INSERT INTO policy_fts SELECT id,title,body FROM policies')
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False

    def policies(self, db):
        return rows(db.execute('SELECT * FROM policies ORDER BY id'))

    def search(self, db, query):
        terms = [w for w in ['退货','换货','运费','寄回','质量','耳机','键盘','相机','退款','7天','30天'] if w in query]
        # Keyword fallback also covers newly added policy vocabulary, including
        # two-character Chinese terms that FTS trigram cannot index.
        cleaned = query.strip('？?。!！ ')
        if len(cleaned) >= 2:
            terms.append(cleaned)
        for phrase in re.findall(r'[\u4e00-\u9fff]+',query):
            terms.extend(phrase[i:i+2] for i in range(len(phrase)-1)
                         if phrase[i:i+2] not in {'什么','怎么','可以','是否','请问','我的','这个','那个','如何','多少','帮我','一下','为什','么时','时候','现在','需要','问题','申请','使用','商品','说明','服务','处理','支持','相关'})
        found = {}
        if self.fts and len(query) >= 3:
            for p in rows(db.execute('SELECT p.* FROM policy_fts f JOIN policies p ON p.id=f.id WHERE policy_fts MATCH ? LIMIT 4',('"'+query.replace('"','""')+'"',))):
                found[p['id']] = p
        for p in self.policies(db):
            if any(t in p['title']+p['body'] for t in terms):
                found[p['id']] = p
        return list(found.values())


def audit(db, actor, action, target, detail):
    db.execute('INSERT INTO audit(actor,action,target,detail,created_at) VALUES(?,?,?,?,?)',(actor,action,target,json.dumps(detail,ensure_ascii=False),now()))
