import os
import uvicorn
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    host, port = os.environ.get("VIO_HOST", "0.0.0.0"), int(os.environ.get("VIO_PORT", "8000"))
    print(f"VideoImageOperation: http://127.0.0.1:{port}")
    print("局域网使用本机 IPv4 地址访问同一端口。仅启动一个服务进程。")
    uvicorn.run("app.main:app", host=host, port=port, workers=1)
