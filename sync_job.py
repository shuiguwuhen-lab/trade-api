"""GitHub Actions 定时同步脚本：MySQL → 阿里云 OSS
由 GitHub Actions 直接执行，不依赖 Render.com。
读取 MySQL 中的交易信号，写入 OSS signals.json，删除已同步信号。
"""
import pymysql
import oss2
import json
import os
from datetime import datetime

DB_CONFIG = {
    'host': os.environ['DB_HOST'],
    'port': int(os.environ['DB_PORT']),
    'user': os.environ['DB_USER'],
    'password': os.environ['DB_PASS'],
    'database': os.environ['DB_NAME'],
    'charset': 'utf8mb4',
}

OSS_CONFIG = {
    'access_key': os.environ['OSS_ACCESS_KEY'],
    'access_secret': os.environ['OSS_ACCESS_SECRET'],
    'endpoint': 'https://oss-cn-hangzhou.aliyuncs.com',
    'bucket': 'trade-signals-jfchq8848',
    'key': 'signals.json',
}

def do_sync():
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, time, action, code, amt, pct "
                "FROM stocks WHERE strategy='dougua1' AND mode='1' "
                "ORDER BY time ASC"
            )
            rows = cursor.fetchall()

        signals = []
        signal_ids = []
        for row in rows:
            signals.append({
                'id': row[0],
                'time': str(row[1]),
                'action': row[2],
                'code': row[3],
                'amt': int(row[4]),
                'pct': float(row[5]),
            })
            signal_ids.append(row[0])

        auth = oss2.Auth(OSS_CONFIG['access_key'], OSS_CONFIG['access_secret'])
        bucket = oss2.Bucket(auth, OSS_CONFIG['endpoint'], OSS_CONFIG['bucket'])

        payload = json.dumps({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'signals': signals,
        }, ensure_ascii=False)

        bucket.put_object(OSS_CONFIG['key'], payload.encode('utf-8'))

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

        print(f"synced={len(signals)} deleted={deleted}")
        return len(signals), deleted
    finally:
        conn.close()

if __name__ == '__main__':
    do_sync()
