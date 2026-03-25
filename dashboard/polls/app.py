from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response
import sqlite3
import json
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changeme')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'changeme')
DB_PATH = '/data/polls.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs('/data', exist_ok=True)
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS polls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        type TEXT NOT NULL,
        options TEXT,
        expires_at TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poll_id INTEGER NOT NULL,
        choice TEXT NOT NULL,
        voter_token TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )''')
    conn.commit()
    conn.close()


def is_expired(poll):
    if not poll['expires_at']:
        return False
    try:
        expires = datetime.fromisoformat(poll['expires_at'])
        return datetime.utcnow() > expires
    except Exception:
        return False


def get_results(poll_id, poll_type, options):
    conn = get_db()
    if poll_type == 'text':
        rows = conn.execute(
            'SELECT choice, created_at FROM votes WHERE poll_id=? ORDER BY created_at DESC',
            (poll_id,)
        ).fetchall()
        conn.close()
        return {'responses': [dict(r) for r in rows], 'total': len(rows)}
    else:
        results = {opt: 0 for opt in (options or [])}
        rows = conn.execute(
            'SELECT choice, COUNT(*) as count FROM votes WHERE poll_id=? GROUP BY choice',
            (poll_id,)
        ).fetchall()
        conn.close()
        for row in rows:
            results[row['choice']] = row['count']
        total = sum(results.values())
        return {'options': results, 'total': total}


def prepare_poll(p):
    p = dict(p)
    if p['options']:
        p['options'] = json.loads(p['options'])
    p['expired'] = is_expired(p) or not p['active']
    return p


@app.route('/')
def index():
    conn = get_db()
    polls = conn.execute('SELECT * FROM polls ORDER BY created_at DESC').fetchall()
    conn.close()
    active, past = [], []
    for p in polls:
        p = prepare_poll(p)
        (past if p['expired'] else active).append(p)
    return render_template('index.html', active_polls=active, past_polls=past)


@app.route('/poll/<int:poll_id>')
def poll(poll_id):
    conn = get_db()
    p = conn.execute('SELECT * FROM polls WHERE id=?', (poll_id,)).fetchone()
    conn.close()
    if not p:
        return redirect('/')
    p = prepare_poll(p)
    voter_token = request.cookies.get('voter_token', '')
    already_voted = False
    if voter_token:
        conn = get_db()
        already_voted = conn.execute(
            'SELECT id FROM votes WHERE poll_id=? AND voter_token=?',
            (poll_id, voter_token)
        ).fetchone() is not None
        conn.close()
    results = get_results(poll_id, p['type'], p['options'])
    show_results = p['expired'] or already_voted
    return render_template('poll.html', poll=p, already_voted=already_voted,
                           show_results=show_results, results=results)


@app.route('/poll/<int:poll_id>/vote', methods=['POST'])
def vote(poll_id):
    conn = get_db()
    p = conn.execute('SELECT * FROM polls WHERE id=?', (poll_id,)).fetchone()
    conn.close()
    if not p:
        return jsonify({'error': 'not found'}), 404
    p = prepare_poll(p)
    if p['expired']:
        return jsonify({'error': 'poll closed'}), 400

    voter_token = request.cookies.get('voter_token') or str(uuid.uuid4())
    conn = get_db()
    if conn.execute('SELECT id FROM votes WHERE poll_id=? AND voter_token=?',
                    (poll_id, voter_token)).fetchone():
        conn.close()
        return jsonify({'error': 'already voted'}), 400

    data = request.json or {}
    if p['type'] == 'text':
        text = data.get('text', '').strip()
        if not text:
            conn.close()
            return jsonify({'error': 'empty response'}), 400
        conn.execute('INSERT INTO votes (poll_id, choice, voter_token) VALUES (?,?,?)',
                     (poll_id, text, voter_token))
    elif p['type'] == 'single':
        choices = data.get('choices', [])
        if len(choices) != 1:
            conn.close()
            return jsonify({'error': 'select one option'}), 400
        conn.execute('INSERT INTO votes (poll_id, choice, voter_token) VALUES (?,?,?)',
                     (poll_id, choices[0], voter_token))
    elif p['type'] == 'multiple':
        choices = data.get('choices', [])
        if not choices:
            conn.close()
            return jsonify({'error': 'select at least one option'}), 400
        for choice in choices:
            conn.execute('INSERT INTO votes (poll_id, choice, voter_token) VALUES (?,?,?)',
                         (poll_id, choice, voter_token))

    conn.commit()
    conn.close()
    resp = make_response(jsonify({'ok': True}))
    resp.set_cookie('voter_token', voter_token, max_age=60*60*24*365*2, samesite='Lax')
    return resp


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and not session.get('admin'):
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin'))
        return render_template('admin.html', logged_in=False, error='Wrong password')
    if not session.get('admin'):
        return render_template('admin.html', logged_in=False, error=None)

    conn = get_db()
    polls = conn.execute('SELECT * FROM polls ORDER BY created_at DESC').fetchall()
    conn.close()
    poll_list = []
    for p in polls:
        p = prepare_poll(p)
        p['results'] = get_results(p['id'], p['type'], p['options'])
        poll_list.append(p)
    return render_template('admin.html', logged_in=True, polls=poll_list)


@app.route('/admin/create', methods=['POST'])
def admin_create():
    if not session.get('admin'):
        return jsonify({'error': 'unauthorized'}), 401
    data = request.json or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'error': 'title required'}), 400
    poll_type = data.get('type', 'single')
    options = data.get('options', [])
    conn = get_db()
    conn.execute(
        'INSERT INTO polls (title, description, type, options, expires_at) VALUES (?,?,?,?,?)',
        (title, data.get('description', '').strip() or None,
         poll_type, json.dumps(options) if options else None,
         data.get('expires_at') or None)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/close/<int:poll_id>', methods=['POST'])
def admin_close(poll_id):
    if not session.get('admin'):
        return jsonify({'error': 'unauthorized'}), 401
    conn = get_db()
    conn.execute('UPDATE polls SET active=0 WHERE id=?', (poll_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/reopen/<int:poll_id>', methods=['POST'])
def admin_reopen(poll_id):
    if not session.get('admin'):
        return jsonify({'error': 'unauthorized'}), 401
    conn = get_db()
    conn.execute('UPDATE polls SET active=1, expires_at=NULL WHERE id=?', (poll_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/delete/<int:poll_id>', methods=['POST'])
def admin_delete(poll_id):
    if not session.get('admin'):
        return jsonify({'error': 'unauthorized'}), 401
    conn = get_db()
    conn.execute('DELETE FROM votes WHERE poll_id=?', (poll_id,))
    conn.execute('DELETE FROM polls WHERE id=?', (poll_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/')


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8085, debug=False)
