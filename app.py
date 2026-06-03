"""
Render.com 健康检查 + MySQL 信号查看
信号同步已由聚宽直接写 OSS 完成，此服务仅用于调试监控。
"""
from flask import Flask, jsonify, request
import pymysql
import os
from datetime import datetime

app = Flask(__name__)

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'mysql6.sqlpub.com'),
    'port': int(os.environ.get('DB_PORT', 3311)),
    'user': os.environ.get('DB_USER', 'jqlhlxh'),
    'password': os.environ.get('DB_PASS', 'jTWmxC7fhD44LLzi'),
    'database': os.environ.get('DB_NAME', 'jqlh_mysql_01'),
    'charset': 'utf8mb4',
}

def get_db():
    return pymysql.connect(**DB_CONFIG)


@app.route('/')
def index():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})


@app.route('/orders')
def get_orders():
    """查看 MySQL 中的待处理信号（调试用）"""
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, time, action, code, amt, pct "
                "FROM stocks WHERE strategy='dougua1' AND mode='1' "
                "ORDER BY time ASC"
            )
            rows = cursor.fetchall()
            orders = [{
                'id': row[0],
                'time': str(row[1]),
                'action': row[2],
                'code': row[3],
                'amt': int(row[4]),
                'pct': float(row[5]),
            } for row in rows]
            return jsonify({'orders': orders, 'count': len(orders)})
    finally:
        conn.close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
