"""gunicorn 配置：在每个 worker 启动后启动自动同步线程"""
import threading

# 不使用 --preload，让每个 worker 独立导入 app，避免 fork 杀死线程
preload_app = False

def post_worker_init(worker):
    """worker 启动后确保自动同步线程运行"""
    try:
        from app import _start_auto_sync
        _start_auto_sync()
    except Exception as e:
        print(f"[gunicorn] auto-sync start failed: {e}")
