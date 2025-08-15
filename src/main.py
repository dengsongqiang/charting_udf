# !/usr/bin/env python
# -*-coding:utf-8-*-
import sys
import os
import logging
from pathlib import Path

# 将项目根目录添加到Sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory, render_template_string, jsonify
from udf import udf_bp, start_update_thread, init_db

from flask import Flask

app = Flask(__name__)

# 添加全局响应头，允许 unload 事件
@app.after_request
def add_permissions_policy(response):
    response.headers["Permissions-Policy"] = "unload=()"
    return response



app = Flask(__name__)
# 设置日志级别
app.logger.setLevel(logging.DEBUG)

# ---配置--
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_PATH = os.path.join(PROJECT_ROOT, "static")
USER_HOME_PATH = STATIC_PATH
CHARTING_LIBRARY_BASE_PATH = os.path.join(STATIC_PATH, "charting_library")
CHARTING_LIBRARY_STATIC_ASSETS_PATH = os.path.join(CHARTING_LIBRARY_BASE_PATH, "bundles")
DATAFEEDS_BASE_PATH = os.path.join(STATIC_PATH, "datafeeds")

# 确保数据目录存在
Path(os.path.join(PROJECT_ROOT, "src", "data")).mkdir(parents=True, exist_ok=True)

# ---注册蓝图（添加url_prefix="/udf"）---
app.register_blueprint(udf_bp, url_prefix="/udf")


@app.route("/")
def serve_html_test_page():
    """提供主HTML测试页面"""
    test_page_path = os.path.join(STATIC_PATH, "index.html")
    if os.path.exists(test_page_path):
        with open(test_page_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        # 内置测试页面
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>TradingView + AkShare Test</title>
            <script src="/charting_library/charting_library.js"></script>
            <script src="/datafeeds/udf/dist/bundle.js"></script>
            <style>
                body { margin: 0; padding: 0; }
                #tv_chart_container { width: 100%; height: 800px; }
            </style>
        </head>
        <body>
            <div id="tv_chart_container"></div>
            <script>
                const widgetOptions = {
                    container_id: "tv_chart_container",
                    datafeed: new Datafeeds.UDFCompatibleDatafeed("/udf"),
                    library_path: "/charting_library/",
                    timezone: "Asia/Shanghai",
                    symbol: "SSE:600036",
                    interval: "D",
                    locale: "zh",
                    disabled_features: [],
                    enabled_features: [],
                    overrides: {},
                    studies_overrides: {},
                };

                const widget = new TradingView.widget(widgetOptions);
            </script>
        </body>
        </html>
        """
        return render_template_string(html_content)


@app.route("/charting_library/bundles/<path:filename>")
def serve_charting_library_static_assets(filename):
    """提供TradingView图表库静态资源"""
    app.logger.debug(f"请求静态资源:{filename}")
    app.logger.debug(f"查找目录：{CHARTING_LIBRARY_STATIC_ASSETS_PATH}")
    return send_from_directory(CHARTING_LIBRARY_STATIC_ASSETS_PATH, filename)


@app.route("/charting_library/<path:filename>")
def serve_charting_library_main_js(filename):
    """提供TradingView图表库主JS文件"""
    app.logger.debug(f"请求图表库主文件: {filename}")
    return send_from_directory(CHARTING_LIBRARY_BASE_PATH, filename)


@app.route("/datafeeds/<path:path_to_file>")
def serve_datafeeds_udf_bundle(path_to_file):
    """提供UDF数据馈送适配器"""
    return send_from_directory(DATAFEEDS_BASE_PATH, path_to_file)


# 跨域支持
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


if __name__ == "__main__":
    # 初始化数据库
    with app.app_context():
        init_db()

    # 启动符号列表更新线程
    start_update_thread(app)

    # 运行应用
    app.run(host="0.0.0.0", port=8080, debug=True)
