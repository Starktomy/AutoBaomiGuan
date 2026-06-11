import json
import os
import time
import uuid
import threading
import requests
from flask import Flask, jsonify, request, render_template, Response

import config
import login
from course import CourseManager

app = Flask(__name__, template_folder="templates")

# Thread safety lock for tasks access
tasks_lock = threading.Lock()
tasks = {}

def log_task(task_id, message):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id]["logs"].append(message)
            # Limit log size
            if len(tasks[task_id]["logs"]) > 2000:
                tasks[task_id]["logs"].pop(0)

def set_task_step(task_id, step):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id]["step"] = step

def set_task_status(task_id, status):
    with tasks_lock:
        if task_id in tasks:
            tasks[task_id]["status"] = status

def task_worker(task_id, username, password):
    def callback_log(msg):
        log_task(task_id, msg)

    course_packet_id = config.course_packet_id

    try:
        set_task_status(task_id, "running")
        
        # Step 1: Login
        set_task_step(task_id, "login")
        log_task(task_id, "正在尝试登录保密观平台...")
        
        token = login.login(username, password, log_callback=callback_log)
        log_task(task_id, "登录成功，已获取 Token。正在校验 Token 有效性...")
        
        # Validate login details
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36",
            "token": token,
            "authToken": token,
            "siteId": "95",
            "Content-Type": "application/json",
        }
        check_url = "https://www.baomi.org.cn/portal/main-api/checkToken.do"
        res = session.get(check_url, headers=headers).json()
        if not res.get("result"):
            raise Exception("获取 Token 成功但平台校验失败，请检查账户或重试")
        
        nickname = res["data"].get("nickName") or "学员"
        log_task(task_id, f"欢迎您，{nickname}！校验成功。")

        course_manager = CourseManager(session, token, log_callback=callback_log)
        
        # Step 2: Study videos
        set_task_step(task_id, "study")
        log_task(task_id, "获取课程基本信息...")
        course_info = course_manager.get_course_info(course_packet_id)
        if course_info and course_info.get("data"):
            log_task(task_id, f"开始学习课程: {course_info['data']['name']}")
        else:
            log_task(task_id, f"警告: 无法获取课程包信息，将使用默认ID {course_packet_id}")

        log_task(task_id, "开始自动学习视频课程（大约需要数分钟，请耐心等待）...")
        study_ok = course_manager.study_course(course_packet_id)
        if not study_ok:
            raise Exception("视频课程刷课未完全成功")
            
        log_task(task_id, "视频课程已全部学习完成！")
        
        # Step 3: Check progress
        set_task_step(task_id, "progress")
        log_task(task_id, "开始验证学习进度，请稍候...")
        progress = course_manager.get_course_progress(course_packet_id)
        if progress and progress.get("data"):
            data = progress["data"]
            log_task(task_id, f"当前学习进度: {data['progressRate'] * 100:.1f}%")
            log_task(task_id, f"已学课程数: {data['studyResourceNum']}/{data['resourceSum']}")
            
            if not data['isFinish']:
                log_task(task_id, "检测到学习进度未达 100%，正在启动补刷机制...")
                course_manager.study_course(course_packet_id)
                
                # Check again
                progress = course_manager.get_course_progress(course_packet_id)
                if progress and progress.get("data"):
                    data = progress["data"]
                    log_task(task_id, f"补刷后进度: {data['progressRate'] * 100:.1f}%")
                    if not data['isFinish']:
                        raise Exception("课程进度未达 100%，请尝试重新刷课")
        else:
            raise Exception("获取课程进度失败，无法验证是否已完成学习")
            
        log_task(task_id, "学习进度验证通过，全部课程已学完。")

        # Step 4: Take the exam
        set_task_step(task_id, "exam")
        log_task(task_id, "开始拉取试卷并自动完成考试...")
        exam_ok = course_manager.complete_exam(course_packet_id)
        if not exam_ok:
            raise Exception("自动考试未能成功提交或满分通过")

        log_task(task_id, "考试已满分通过，并成功更新了课程包的考试状态。")

        # Step 5: Finished
        set_task_step(task_id, "done")
        set_task_status(task_id, "success")
        log_task(task_id, "================ 刷课完成 ================")
        log_task(task_id, "恭喜您！所有课程学习与自动答题已经顺利完成！")
        log_task(task_id, "提示：请使用您的账号登录保密观官方网站 (https://www.baomi.org.cn)，并在个人中心自行下载证书！")

    except Exception as e:
        set_task_status(task_id, "failed")
        log_task(task_id, f"发生致命错误，任务终止: {str(e)}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({
        "course_packet_id": config.course_packet_id
    })

@app.route("/api/start", methods=["POST"])
def start_task():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "账号和密码不能为空"}), 400

    task_id = str(uuid.uuid4())
    
    with tasks_lock:
        tasks[task_id] = {
            "id": task_id,
            "username": username,
            "status": "pending",
            "step": "idle",
            "logs": ["任务已创建，正在加入执行队列..."]
        }

    # Start task thread
    t = threading.Thread(target=task_worker, args=(task_id, username, password))
    t.daemon = True
    t.start()

    return jsonify({
        "status": "success",
        "task_id": task_id
    })

@app.route("/api/logs/<task_id>", methods=["GET"])
def get_logs(task_id):
    # Verify task existence
    with tasks_lock:
        exists = task_id in tasks
    
    if not exists:
        return jsonify({"error": "找不到该任务"}), 404

    def event_stream():
        idx = 0
        while True:
            with tasks_lock:
                task = tasks.get(task_id)
                if not task:
                    break
                
                logs_len = len(task["logs"])
                status = task["status"]
                step = task["step"]
                
                new_logs = []
                if idx < logs_len:
                    new_logs = task["logs"][idx:logs_len]
                    idx = logs_len
            
            # Yield any new logs
            for log in new_logs:
                yield f"data: {json.dumps({'msg': log, 'step': step, 'status': status})}\n\n"
            
            if status in ["success", "failed"]:
                # Yield final packet to notify UI to close connection
                yield f"data: {json.dumps({'msg': '[SYSTEM] 任务运行结束。', 'step': step, 'status': status, 'done': True})}\n\n"
                break
                
            time.sleep(0.5)

    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
