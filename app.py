"""
Render.com 免费中转 API - 连接 sqlpub.com MySQL
双通道信号中转：
  1) HTTP API（旧通道，国金PT无法直连 Render）
  2) 阿里云 OSS（新通道，国金PT可通过公网读取）
"""
from flask import Flask, jsonify, request
import pymysql
import oss2
import json
import os
from datetime import datetime

app = Flask(__name__)

# 数据库配置（从环境变量读取，避免硬编码）
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'mysql6.sqlpub.com'),
    'port': int(os.environ.get('DB_PORT', 3311)),
    'user': os.environ.get('DB_USER', 'jqlhlxh'),
    'password': os.environ.get('DB_PASS', 'jTWmxC7fhD44LLzi'),
    'database': os.environ.get('DB_NAME', 'jqlh_mysql_01'),
    'charset': 'utf8mb4',
}

# 阿里云 OSS 配置（密钥通过 Render.com 环境变量注入，不写入代码）
OSS_CONFIG = {
    'access_key': os.environ.get('OSS_ACCESS_KEY', ''),
    'access_secret': os.environ.get('OSS_ACCESS_SECRET', ''),
    'endpoint': 'https://oss-cn-hangzhou.aliyuncs.com',
    'bucket': 'trade-signals-jfchq8848',
    'key': 'signals.json',
}

def get_db():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


@app.route('/')
def index():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})


@app.route('/orders', methods=['GET'])
def get_orders():
    """获取所有待处理的交易信号"""
    strategy = request.args.get('strategy', 'dougua1')
    mode = request.args.get('mode', '1')
    
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, time, action, code, amt, pct, strategy "
                "FROM stocks WHERE strategy=%s AND mode=%s "
                "ORDER BY time ASC",
                (strategy, mode)
            )
            rows = cursor.fetchall()
            orders = []
            for row in rows:
                orders.append({
                    'id': row[0],
                    'time': row[1].strftime('%Y-%m-%d %H:%M:%S') if hasattr(row[1], 'strftime') else str(row[1]),
                    'action': row[2],
                    'code': row[3],
                    'amt': int(row[4]),
                    'pct': float(row[5]),
                    'strategy': row[6],
                })
            return jsonify({'orders': orders, 'count': len(orders)})
    finally:
        conn.close()


@app.route('/orders/process', methods=['POST'])
def process_orders():
    """处理并删除已执行的订单"""
    data = request.get_json()
    if not data or 'ids' not in data:
        return jsonify({'error': 'missing ids'}), 400
    
    conn = get_db()
    try:
        with conn.cursor() as cursor:
            ids = data['ids']
            if isinstance(ids, list) and len(ids) > 0:
                placeholders = ','.join(['%s'] * len(ids))
                cursor.execute(
                    f"DELETE FROM stocks WHERE id IN ({placeholders})",
                    ids
                )
                conn.commit()
                return jsonify({'deleted': cursor.rowcount})
        return jsonify({'deleted': 0})
    finally:
        conn.close()


@app.route('/oss/sync', methods=['GET'])
def oss_sync():
    """将 MySQL 中的交易信号同步到阿里云 OSS（国金PT从OSS读取）
    
    流程：
    1. 读取 MySQL 中所有待处理信号
    2. 写入 OSS signals.json（覆盖写入，PUT 操作原子性保证不会读到半截文件）
    3. 写入成功后，从 MySQL 删除已同步的信号
    4. 如果 OSS 写入失败，MySQL 信号保留，等待下次重试
    """
    strategy = request.args.get('strategy', 'dougua1')
    mode = request.args.get('mode', '1')
    
    conn = get_db()
    try:
        # 1. 读取 MySQL 信号
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, time, action, code, amt, pct "
                "FROM stocks WHERE strategy=%s AND mode=%s "
                "ORDER BY time ASC",
                (strategy, mode)
            )
            rows = cursor.fetchall()
        
        # 2. 格式化为 JSON
        signals = []
        signal_ids = []
        for row in rows:
            signals.append({
                'id': row[0],
                'time': row[1].strftime('%Y-%m-%d %H:%M:%S') if hasattr(row[1], 'strftime') else str(row[1]),
                'action': row[2],
                'code': row[3],
                'amt': int(row[4]),
                'pct': float(row[5]),
            })
            signal_ids.append(row[0])
        
        # 3. 写入 OSS（即使无信号也写空文件，避免国金PT报404）
        auth = oss2.Auth(OSS_CONFIG['access_key'], OSS_CONFIG['access_secret'])
        bucket = oss2.Bucket(auth, OSS_CONFIG['endpoint'], OSS_CONFIG['bucket'])
        
        payload = json.dumps({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'signals': signals,
        }, ensure_ascii=False)
        
        bucket.put_object(OSS_CONFIG['key'], payload.encode('utf-8'))
        
        # 4. 上传成功 → 删除 MySQL 中已同步的信号
        deleted = 0
        if signal_ids:
            with conn.cursor() as cursor:
                placeholders = ','.join(['%s'] * len(signal_ids))
                cursor.execute(
                    f"DELETE FROM stocks WHERE id IN ({placeholders})",
                    signal_ids
                )
                conn.commit()
                deleted = cursor.rowcount
        
        return jsonify({
            'status': 'ok',
            'synced': len(signals),
            'deleted': deleted,
            'signals': signals,
        })
    
    except Exception as e:
        # OSS 写入失败 → MySQL 信号保留，等待下次重试
        return jsonify({
            'status': 'error',
            'error': str(e),
            'message': 'OSS上传失败，MySQL信号已保留待重试',
        }), 500
    finally:
        conn.close()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
