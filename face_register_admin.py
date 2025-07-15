# -*- coding: utf-8 -*-
# Flask 后台：人脸录入页面 + 多图上传 + 列表展示 + 修改 + 添加图片 + 软删除 + 调用 CompreFace 注册 + 存入 MySQL

import os
import uuid
import pymysql
import requests
from flask import Flask, request, render_template_string, redirect, url_for, send_from_directory, flash

UPLOAD_FOLDER = 'uploads'
CF_API_KEY = 'YOUR_COMPRE_FACE_API_KEY'
CF_SUBJECT_API = 'http://localhost:8000/api/v1/recognition/faces'
CF_COLLECTION_ID = 'your_collection_id'

MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'qiu123456',
    'database': 'face_db',
    'charset': 'utf8mb4'
}

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# -------------------- 页面模板 --------------------
HTML_FORM = """
<h2>新增人员</h2>
<form method="POST" enctype="multipart/form-data">
  姓名: <input type="text" name="name" required><br>
  职务: <input type="text" name="position"><br>
  手机号: <input type="text" name="phone"><br>
  个人信息:<br><textarea name="info" rows="4" cols="40"></textarea><br>
  上传照片（可多张）: <input type="file" name="photos" multiple accept="image/*" required><br><br>
  <input type="submit" value="提交">
</form>
<a href='/list'>查看已录入人员</a>
"""

HTML_LIST = """
<h2>已录入人员列表</h2>
<table border="1">
<tr><th>姓名</th><th>职务</th><th>手机号</th><th>图片</th><th>操作</th></tr>
{% for s in subjects %}
<tr>
<td>{{ s[1] }}</td><td>{{ s[2] }}</td><td>{{ s[3] }}</td>
<td>
  {% for img in s[5] %}
    <img src="/uploads/{{ img }}" width="80"> <br>
  {% endfor %}
</td>
<td>
  <a href="/edit/{{ s[0] }}">编辑</a>
  <a href="/delete/{{ s[0] }}" onclick="return confirm('确定删除？')">删除</a>
</td>
</tr>
{% endfor %}
</table>
<a href='/'>返回录入</a>
"""

HTML_EDIT = """
<h2>编辑人员</h2>
<form method="POST" enctype="multipart/form-data">
  姓名: <input type="text" name="name" value="{{ s[1] }}" required><br>
  职务: <input type="text" name="position" value="{{ s[2] }}"><br>
  手机号: <input type="text" name="phone" value="{{ s[3] }}"><br>
  个人信息:<br><textarea name="info" rows="4" cols="40">{{ s[4] }}</textarea><br><br>
  添加照片（可选）: <input type="file" name="photos" multiple accept="image/*"><br><br>
  <input type="submit" value="保存修改">
</form>
<a href='/list'>返回列表</a>
"""

# -------------------- 数据库操作 --------------------
def insert_subject(subject_id, name, position, phone, info):
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subject_table (subject_id, name, position, phone, info, deleted)
            VALUES (%s, %s, %s, %s, %s, 0)
        """, (subject_id, name, position, phone, info))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")

def get_all_subjects():
    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT subject_id, name, position, phone, info FROM subject_table WHERE deleted=0")
    rows = cursor.fetchall()
    result = []
    for r in rows:
        imgs = [f for f in os.listdir(UPLOAD_FOLDER) if f.startswith(r[0])]
        result.append(list(r) + [imgs])
    cursor.close()
    conn.close()
    return result

def get_subject(subject_id):
    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subject_table WHERE subject_id=%s", (subject_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def update_subject(subject_id, name, position, phone, info):
    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE subject_table SET name=%s, position=%s, phone=%s, info=%s WHERE subject_id=%s
    """, (name, position, phone, info, subject_id))
    conn.commit()
    cursor.close()
    conn.close()

def soft_delete_subject(subject_id):
    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute("UPDATE subject_table SET deleted=1 WHERE subject_id=%s", (subject_id,))
    conn.commit()
    cursor.close()
    conn.close()

# -------------------- CompreFace 操作 --------------------
def register_to_compreFace(subject_id, image_path):
    with open(image_path, 'rb') as f:
        files = {'file': (os.path.basename(image_path), f, 'image/jpeg')}
        data = {'subject': subject_id}
        headers = {'x-api-key': CF_API_KEY}
        try:
            r = requests.post(f"{CF_SUBJECT_API}/{CF_COLLECTION_ID}/add", files=files, data=data, headers=headers)
            if r.status_code != 200:
                print(f"[CompreFace ERROR] status={r.status_code}, response={r.text}")
        except Exception as e:
            print(f"[CompreFace ERROR] {e}")

def delete_compreFace_subject(subject_id):
    headers = {'x-api-key': CF_API_KEY}
    try:
        r = requests.delete(f"{CF_SUBJECT_API}/{CF_COLLECTION_ID}/subject/{subject_id}", headers=headers)
        print(f"[CompreFace delete] {r.status_code} => {r.text}")
    except Exception as e:
        print(f"[CompreFace delete ERROR] {e}")

# -------------------- 路由 --------------------
@app.route('/', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        position = request.form.get('position', '')
        phone = request.form.get('phone', '')
        info = request.form.get('info', '')
        files = request.files.getlist('photos')
        if not name or not files:
            flash("姓名和照片不能为空")
            return redirect(url_for('register'))
        subject_id = str(uuid.uuid4())
        insert_subject(subject_id, name, position, phone, info)
        for file in files:
            if file.filename:
                ext = os.path.splitext(file.filename)[1]
                filename = f"{subject_id}_{name}_{uuid.uuid4().hex}{ext}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                register_to_compreFace(subject_id, save_path)
        return f"<h3>注册成功！ID: {subject_id}</h3><a href='/'>返回</a>"
    return render_template_string(HTML_FORM)

@app.route('/list')
def list_page():
    rows = get_all_subjects()
    return render_template_string(HTML_LIST, subjects=rows)

@app.route('/edit/<subject_id>', methods=['GET', 'POST'])
def edit_subject(subject_id):
    if request.method == 'POST':
        name = request.form['name']
        position = request.form['position']
        phone = request.form['phone']
        info = request.form['info']
        update_subject(subject_id, name, position, phone, info)

        files = request.files.getlist('photos')
        for file in files:
            if file.filename:
                ext = os.path.splitext(file.filename)[1]
                filename = f"{subject_id}_{name}_{uuid.uuid4().hex}{ext}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                register_to_compreFace(subject_id, save_path)

        return redirect(url_for('list_page'))
    s = get_subject(subject_id)
    return render_template_string(HTML_EDIT, s=s)

@app.route('/delete/<subject_id>')
def delete_subject_route(subject_id):
    delete_compreFace_subject(subject_id)
    soft_delete_subject(subject_id)
    return redirect(url_for('list_page'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# -------------------- 启动 --------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=True)