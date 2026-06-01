"""
Render.com 免费中转 API - 连接 sqlpub.com MySQL
双通道信号中转：
  1) HTTP API（旧通道，国金PT无法直连 Render）
  2) 阿里云 OSS（新通道，国金PT可通过公网读取）
  
后台自动同步：聚宽和国金PT都无法直连 Render.com，
故此 API 自带后台线程每30秒自动从 MySQL 同步到 OSS，
聚宽只需写 MySQL，国金PT只需读 OSS，无需互连。
"""
from flask import Flask, jsonify, request
import pymysql
import oss2
import json
import os
import threading
import time as _time
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


def do_sync(strategy='dougua1', mode='1'):
    """核心同步逻辑：读 MySQL → 写 OSS → 删 MySQL。返回 (synced_count, deleted_count)"""
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
        
        # 3. 写入 OSS
        auth = oss2.Auth(OSS_CONFIG['access_key'], OSS_CONFIG['access_secret'])
        bucket = oss2.Bucket(auth, OSS_CONFIG['endpoint'], OSS_CONFIG['bucket'])
        
        payload = json.dumps({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'signals': signals,
        }, ensure_ascii=False)
        
        bucket.put_object(OSS_CONFIG['key'], payload.encode('utf-8'))
        
        # 4. 删除已同步信号
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
        
        return len(signals), deleted
    
    finally:
        conn.close()


# ── 后台自动同步线程 ─────────────────────────────────────────
# 聚宽和国金PT都无法访问 Render.com，故此线程每30秒自动拉取
# MySQL 信号写入 OSS，实现全链路解耦
def _auto_sync_worker():
    """后台线程：每30秒自动同步 MySQL → OSS"""
    while True:
        try:
            synced, deleted = do_sync('dougua1', '1')
            if synced > 0:
                print(f"[auto-sync] synced={synced} deleted={deleted}")
        except Exception as e:
            print(f"[auto-sync] error: {e}")
        _time.sleep(30)

_auto_sync_thread = threading.Thread(target=_auto_sync_worker, daemon=True, name="auto-sync")
_auto_sync_thread.start()


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
    """手动触发 OSS 同步（作为自动同步的补充）"""
    strategy = request.args.get('strategy', 'dougua1')
    mode = request.args.get('mode', '1')
    try:
        synced, deleted = do_sync(strategy, mode)
        return jsonify({'status': 'ok', 'synced': synced, 'deleted': deleted})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
