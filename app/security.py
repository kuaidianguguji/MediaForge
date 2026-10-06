import base64
import hashlib
import hmac
import secrets
import time
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .config import DATA_DIR
from .db import get_db, SessionToken, User

def local_secret(filename, factory):
    path = DATA_DIR / filename
    if not path.exists():
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(factory())
            path.chmod(0o600)
        except FileExistsError:
            pass
    return path.read_text(encoding="utf-8").strip()

def cipher():
    return Fernet(local_secret("app.key", lambda: Fernet.generate_key().decode()).encode())

def encrypt(value):
    return cipher().encrypt(value.encode()).decode() if value else ""

def decrypt(value):
    return cipher().decrypt(value.encode()).decode() if value else ""

def hash_password(password):
    salt = secrets.token_bytes(16)
    result = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(result).decode()

def verify_password(password, stored):
    try:
        _, salt, expected = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False

def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()

def current_user(request: Request, db: Session = Depends(get_db)):
    session = db.get(SessionToken, token_hash(request.cookies.get("vio_session", "")))
    if not session or session.expires_at < time.time():
        raise HTTPException(401, "请先登录")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "用户已停用")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.csrf):
            raise HTTPException(403, "会话校验失败，请刷新页面重试")
    request.state.session = session
    return user

def admin_user(user: User = Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "仅管理员可操作")
    return user
