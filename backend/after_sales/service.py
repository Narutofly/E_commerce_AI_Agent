import json
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from .store import now, audit, rows


def owned(db, table, item_id, user_id):
    if table not in ('orders','tickets','conversations'):
        raise ValueError('Unsupported table')
    row = db.execute(f'SELECT * FROM {table} WHERE id=? AND user_id=?',(item_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404,'记录不存在')
    return dict(row)


def decode_ticket(row):
    result = dict(row)
    for key in ('snapshot','precheck'):
        result[key] = json.loads(result[key])
    return result


def create_ticket(store, user, req):
    with store.db(True) as db:
        order = owned(db,'orders',req.order_id,user['id'])
        previous = db.execute('SELECT * FROM tickets WHERE user_id=? AND request_id=?',(user['id'],req.request_id)).fetchone()
        if previous:
            if (previous['order_id'],previous['kind'],previous['reason']) != (req.order_id,req.kind,req.reason):
                raise HTTPException(409,'请求标识已用于其他申请')
            return decode_ticket(previous)
        if db.execute("SELECT 1 FROM tickets WHERE order_id=? AND status IN ('pending','approved')",(req.order_id,)).fetchone():
            raise HTTPException(409,'该订单已有待审核或已受理申请')
        days = (datetime.now(timezone.utc)-datetime.fromisoformat(order['signed_at'])).total_seconds()/86400
        limit = 7 if req.kind == 'return' else 30
        precheck = {'rule_days':limit,'elapsed_days':round(days,2),'exception':days>limit,'result':'超出窗口，转人工例外审核' if days>limit else '时间规则通过，仍需人工审核','rules_version':'demo-v1'}
        tid = 'AS-'+uuid.uuid4().hex[:12]
        stamp = now()
        db.execute('INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(tid,user['id'],req.order_id,req.kind,req.reason,'pending','',req.request_id,json.dumps(precheck,ensure_ascii=False),json.dumps(store.policies(db),ensure_ascii=False),stamp,stamp))
        audit(db,user['id'],'ticket.create',tid,precheck)
        return decode_ticket(db.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone())


def review_ticket(store,user,tid,req):
    with store.db(True) as db:
        row = db.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone()
        if not row:
            raise HTTPException(404,'工单不存在')
        expected = 'approved' if req.status=='completed' else 'pending'
        if row['status'] != expected:
            raise HTTPException(409,'工单状态已变更，请刷新')
        db.execute('UPDATE tickets SET status=?,opinion=?,updated_at=? WHERE id=? AND status=?',(req.status,req.opinion,now(),tid,expected))
        audit(db,user['id'],'ticket.'+req.status,tid,{'from':expected,'opinion':req.opinion})
        return decode_ticket(db.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone())
