import os
import sys
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, quote

from flask import Flask, render_template, request, send_file, jsonify, url_for

app = Flask(__name__)
BASE_DIR = os.path.dirname(__file__)

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['SEPARATED_FOLDER'] = os.path.join(BASE_DIR, 'separated')
app.config['WIKI_FOLDER'] = os.path.join(BASE_DIR, 'wiki')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SEPARATED_FOLDER'], exist_ok=True)
os.makedirs(app.config['WIKI_FOLDER'], exist_ok=True)

VALID_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.wma', '.aac', '.aiff', '.aif'}


def allowed_file(filename):
    return Path(filename).suffix.lower() in VALID_EXTENSIONS


# ─── 首页：分离 ────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', nav_active='separate')


@app.route('/separate', methods=['POST'])
def separate():
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': f'不支持的文件格式。支持: {", ".join(VALID_EXTENSIONS)}'}), 400

    model_name = request.form.get('model', 'htdemucs')
    two_stems = request.form.get('two_stems', 'true') == 'true'

    track_name = file.filename.rsplit('.', 1)[0]
    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(upload_path)

    out_dir = os.path.join(app.config['SEPARATED_FOLDER'], model_name)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)

    try:
        cmd = [
            sys.executable, '-m', 'demucs',
            '-n', model_name,
            '-o', app.config['SEPARATED_FOLDER'],
            '--filename', '{stem}.{ext}',
        ]
        if two_stems:
            cmd += ['--two-stems', 'vocals']
        cmd.append(upload_path)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or '未知错误'
            return jsonify({'error': f'分离失败: {error_msg}'}), 500

        model_out = os.path.join(app.config['SEPARATED_FOLDER'], model_name)

        files = []
        for f in sorted(os.listdir(model_out)):
            file_path = os.path.join(model_out, f)
            if os.path.isfile(file_path):
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                files.append({
                    'name': f,
                    'size': f'{size_mb:.1f} MB',
                    'url': url_for('download', model=model_name, filename=f),
                })

        return jsonify({'success': True, 'files': files, 'model': model_name})

    except subprocess.TimeoutExpired:
        return jsonify({'error': '处理超时（超过10分钟）'}), 500
    except Exception as e:
        return jsonify({'error': f'处理出错: {str(e)}'}), 500
    finally:
        if os.path.exists(upload_path):
            os.remove(upload_path)


@app.route('/download/<model>/<filename>')
def download(model, filename):
    file_path = os.path.join(app.config['SEPARATED_FOLDER'], model, filename)
    return send_file(file_path, as_attachment=True)


# ─── Wiki ──────────────────────────────────────────────────────

def list_wiki_pages():
    pages = []
    if not os.path.isdir(app.config['WIKI_FOLDER']):
        return pages
    for f in sorted(os.listdir(app.config['WIKI_FOLDER'])):
        if f.endswith('.md'):
            name = f[:-3]
            filepath = os.path.join(app.config['WIKI_FOLDER'], f)
            mtime = os.path.getmtime(filepath)
            pages.append({
                'name': name,
                'title': name,
                'updated': format_time(mtime),
            })
    return pages


def format_time(ts):
    import datetime
    dt = datetime.datetime.fromtimestamp(ts)
    now = datetime.datetime.now()
    if dt.date() == now.date():
        return f'今天 {dt.strftime("%H:%M")}'
    if (now - dt).days < 7:
        days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        return days[dt.weekday()]
    return dt.strftime('%m-%d')


@app.route('/wiki')
def wiki_list():
    pages = list_wiki_pages()
    return render_template('wiki_list.html', pages=pages, nav_active='wiki')


@app.route('/wiki/<path:page_name>')
def wiki_view(page_name):
    page_name = unquote(page_name)

    # Redirect _new to the edit page for creating
    if page_name == '_new':
        return render_template('wiki_edit.html', page_name='', content='', title='新建页面', nav_active='wiki')

    filepath = os.path.join(app.config['WIKI_FOLDER'], page_name + '.md')
    if not os.path.exists(filepath):
        return render_template('wiki_page.html',
                               page_name=page_name, title=page_name,
                               content='*页面不存在*', nav_active='wiki'), 404

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # First line as title
    title = page_name
    lines = content.strip().split('\n')
    if lines and lines[0].startswith('# '):
        title = lines[0][2:]

    return render_template('wiki_page.html',
                           page_name=page_name, title=title,
                           content=content, nav_active='wiki')


@app.route('/wiki/<path:page_name>/edit')
def wiki_edit(page_name):
    page_name = unquote(page_name)
    filepath = os.path.join(app.config['WIKI_FOLDER'], page_name + '.md')
    content = ''
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

    # First line as title
    title = page_name
    lines = content.strip().split('\n')
    if lines and lines[0].startswith('# '):
        title = lines[0][2:]

    return render_template('wiki_edit.html',
                           page_name=page_name, title=title,
                           content=content, nav_active='wiki')


@app.route('/api/wiki/<path:page_name>', methods=['POST'])
def wiki_save(page_name):
    page_name = unquote(page_name)
    if not page_name:
        return jsonify({'error': '页面名不能为空'}), 400

    data = request.get_json()
    if data is None:
        return jsonify({'error': '无效的请求数据'}), 400

    content = data.get('content', '')
    filepath = os.path.join(app.config['WIKI_FOLDER'], page_name + '.md')

    # Prevent path traversal
    try:
        filepath = os.path.realpath(filepath)
        wiki_real = os.path.realpath(app.config['WIKI_FOLDER'])
        if not filepath.startswith(wiki_real):
            return jsonify({'error': '无效的页面名'}), 400
    except (ValueError, OSError):
        return jsonify({'error': '无效的页面名'}), 400

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return jsonify({'success': True, 'page': page_name})


# ─── 启动 ──────────────────────────────────────────────────────

if __name__ == '__main__':
    print('=' * 50)
    print('  BeatForge')
    print('  地址: http://127.0.0.1:5000')
    print('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
