from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import requests
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'changeme-set-in-env')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'changeme')
DB_PATH = '/data/bookrecs.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs('/data', exist_ok=True)
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS andrew_recs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        cover_url TEXT,
        ol_key TEXT,
        year INTEGER,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS user_recs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        cover_url TEXT,
        ol_key TEXT,
        year INTEGER,
        recommended_by TEXT,
        message TEXT,
        contact_info TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    try:
        conn.execute('ALTER TABLE user_recs ADD COLUMN contact_info TEXT')
    except Exception:
        pass
    conn.commit()
    conn.close()


@app.route('/')
def index():
    conn = get_db()
    andrew_recs = conn.execute('SELECT * FROM andrew_recs ORDER BY created_at DESC').fetchall()
    user_recs = conn.execute('SELECT * FROM user_recs ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('index.html', andrew_recs=andrew_recs, user_recs=user_recs)


@app.route('/api/books/search')
def search_books():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    try:
        resp = requests.get(
            'https://openlibrary.org/search.json',
            params={'q': q, 'fields': 'title,author_name,cover_i,key,first_publish_year', 'limit': 6},
            timeout=6
        )
        results = []
        for doc in resp.json().get('docs', []):
            cover_id = doc.get('cover_i')
            results.append({
                'title': doc.get('title', ''),
                'author': ', '.join(doc.get('author_name', [])),
                'year': doc.get('first_publish_year'),
                'ol_key': doc.get('key', '').replace('/works/', ''),
                'cover_url': f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg' if cover_id else None
            })
        return jsonify(results)
    except Exception:
        return jsonify([])


@app.route('/api/recommend', methods=['POST'])
def submit_rec():
    data = request.json or {}
    if not data.get('title') or not data.get('author'):
        return jsonify({'error': 'title and author required'}), 400
    conn = get_db()
    conn.execute(
        'INSERT INTO user_recs (title, author, cover_url, ol_key, year, recommended_by, message, contact_info) VALUES (?,?,?,?,?,?,?,?)',
        (data['title'], data['author'], data.get('cover_url'), data.get('ol_key'),
         data.get('year'), data.get('recommended_by') or 'Anonymous', data.get('message', ''), data.get('contact_info', ''))
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin'))
        return render_template('admin.html', error='Wrong password', logged_in=False)
    if not session.get('admin'):
        return render_template('admin.html', logged_in=False, error=None)
    conn = get_db()
    andrew_recs = conn.execute('SELECT * FROM andrew_recs ORDER BY created_at DESC').fetchall()
    user_recs = conn.execute('SELECT * FROM user_recs ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('admin.html', logged_in=True, andrew_recs=andrew_recs, user_recs=user_recs)


@app.route('/admin/add', methods=['POST'])
def admin_add():
    if not session.get('admin'):
        return jsonify({'error': 'unauthorized'}), 401
    data = request.json or {}
    if not data.get('title') or not data.get('author'):
        return jsonify({'error': 'title and author required'}), 400
    conn = get_db()
    conn.execute(
        'INSERT INTO andrew_recs (title, author, cover_url, ol_key, year, note) VALUES (?,?,?,?,?,?)',
        (data['title'], data['author'], data.get('cover_url'), data.get('ol_key'),
         data.get('year'), data.get('note', ''))
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/delete/<int:rec_id>', methods=['POST'])
def admin_delete(rec_id):
    if not session.get('admin'):
        return jsonify({'error': 'unauthorized'}), 401
    table = request.args.get('table', 'andrew_recs')
    if table not in ('andrew_recs', 'user_recs'):
        return jsonify({'error': 'invalid table'}), 400
    conn = get_db()
    conn.execute(f'DELETE FROM {table} WHERE id=?', (rec_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/')


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8083, debug=False)
