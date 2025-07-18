# -*- coding: utf-8 -*-
# 完整版：人脸识别 + 跟踪 + 可视化标注 + Flask 实时网页显示 + 从 MySQL 读取姓名和 info（仅显示姓名）

import cv2
import time
import requests
import numpy as np
import collections
import threading
import uuid
import os
import pymysql
from flask import Flask, Response

# -------------------- 配置 --------------------
RTSP_URL = "rtsp://username:password@camera_ip:554/Streaming/Channels/101"
CF_API_URL = "http://localhost:8000/api/v1/recognition/recognize"
CF_API_KEY = "YOUR_COMPRE_FACE_API_KEY"
WINDOW_SIZE = 5
VOTE_CONF_THRESHOLD = 0.8
RECHECK_INTERVAL_FRAMES = 20

MYSQL_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'face_db',
    'charset': 'utf8mb4'
}

# 初始化 Flask
app = Flask(__name__)

# 跟踪器和缓冲区等
trackers = {}
window_buf = {}
subject_names = {}  # subject_id -> name
subject_infos = {}  # subject_id -> info（不显示，仅供推送使用）
frame_counter = 0

# -------------------- CompreFace 调用 --------------------
def call_compre_face(frame):
    _, img_encoded = cv2.imencode('.jpg', frame)
    files = {'file': ('frame.jpg', img_encoded.tobytes(), 'image/jpeg')}
    headers = {'x-api-key': CF_API_KEY}
    try:
        resp = requests.post(CF_API_URL, files=files, headers=headers, timeout=2)
        data = resp.json().get('result', [])
    except Exception as e:
        print(f"[CompreFace ERROR] {e}")
        return []
    faces = []
    for item in data:
        if not item.get('subjects'):
            continue
        subj = item['subjects'][0]
        faces.append({
            'box': (item['box']['x_min'], item['box']['y_min'],
                    item['box']['x_max'] - item['box']['x_min'],
                    item['box']['y_max'] - item['box']['y_min']),
            'id': subj['subject'],
            'conf': subj['confidence']
        })
    return faces

# -------------------- 可视化主逻辑 --------------------
def gen_frames():
    global frame_counter
    cap = cv2.VideoCapture(RTSP_URL)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开摄像头：{RTSP_URL}")

    while True:
        success, frame = cap.read()
        if not success:
            continue
        frame_counter += 1

        # 更新跟踪器
        for tid in list(trackers.keys()):
            ok, box = trackers[tid]['tracker'].update(frame)
            if not ok:
                trackers.pop(tid)
                window_buf.pop(tid, None)
                continue
            trackers[tid]['last_box'] = box

        # 是否重新识别
        do_detect = (frame_counter % RECHECK_INTERVAL_FRAMES == 0) or not trackers
        if do_detect:
            faces = call_compre_face(frame)
            for face in faces:
                sid, conf, box = face['id'], face['conf'], face['box']
                tracker = cv2.TrackerKCF_create()
                tracker.init(frame, tuple(box))
                tid = str(uuid.uuid4())
                trackers[tid] = {'tracker': tracker, 'last_box': box}
                window_buf[tid] = collections.deque(maxlen=WINDOW_SIZE)
                window_buf[tid].append((sid, conf))

        # 绘制框与名字
        for tid, rec in trackers.items():
            x, y, w, h = map(int, rec['last_box'])
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            buf = window_buf.get(tid)
            if buf and len(buf) == WINDOW_SIZE:
                labels, confs = zip(*buf)
                vote = max(set(labels), key=labels.count)
                avg_conf = np.mean([c for l, c in buf if l == vote])
                if avg_conf >= VOTE_CONF_THRESHOLD:
                    name = subject_names.get(vote, vote)
                    cv2.putText(frame, name, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
                                0.8, (0, 0, 255), 2, cv2.LINE_AA)

        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

# -------------------- Flask 路由 --------------------
@app.route('/video')
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return "<html><body><h1>视频流</h1><img src='/video'></body></html>"

# -------------------- 数据库加载 --------------------
def load_subjects_from_db():
    global subject_names, subject_infos
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT subject_id, name, info FROM subject_table")
        for sid, name, info in cursor.fetchall():
            subject_names[str(sid)] = name
            subject_infos[str(sid)] = info  # 不用于显示
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[MySQL ERROR] {e}")

# -------------------- 启动 --------------------
if __name__ == '__main__':
    load_subjects_from_db()
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)


# todo：
# 1、图片用名字+时间（精确到秒存储）保存到相对路径，然后本地读取，发送到微信公众号
# 2、我能不能直接修改compreFace的ui和数据库，加个职务，手机号，个人信息字段，然后在录入照片的时候要求填这些信息。然后直接调用呢。我用的docker部署的
# 3、数据库字段 名字 职务 手机号 个人信息 出个sql
# 4、我还需要一个方便录入和修改数据的页面 有没有合适的

