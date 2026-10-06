"""Local maintenance: python -m app.cli backup|reset-password|migrate-data."""
import argparse
from getpass import getpass
from pathlib import Path
import shutil
import sqlite3
import time
from sqlalchemy import create_engine, delete, select
from .config import DATA_DIR, DATABASE_URL
from .db import Base, SessionLocal, SessionToken, User, engine
from .security import hash_password

def main():
    parser = argparse.ArgumentParser(description="VideoImageOperation 本机维护")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="SQLite 一致性备份及加密密钥")
    backup.add_argument("--output", default="backups")
    reset = commands.add_parser("reset-password", help="本机终端重置管理员密码")
    reset.add_argument("username")
    transfer = commands.add_parser("migrate-data", help="复制业务数据到已执行同版本迁移的空数据库；先停止服务")
    transfer.add_argument("--target-url", required=True)
    args = parser.parse_args()
    if args.command == "backup":
        if engine.dialect.name != "sqlite":
            parser.error("云数据库请使用对应数据库的备份工具")
        directory = Path(args.output).resolve() / time.strftime("%Y%m%d-%H%M%S")
        directory.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(engine.url.database) as source, sqlite3.connect(directory / "videoimage.db") as target:
            source.backup(target)
        key = DATA_DIR / "app.key"
        if key.exists():
            shutil.copy2(key, directory / "app.key")
        print(f"备份完成：{directory}；包含密钥，请妥善保管")
    elif args.command == "reset-password":
        password = getpass("新密码（不能为空）：")
        if not password or password != getpass("再次输入："):
            parser.error("密码为空或两次不一致")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == args.username.lower()))
            if not user:
                parser.error("用户不存在")
            user.password_hash = hash_password(password)
            db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
            db.commit()
        print("密码已重置，所有旧会话已失效")
    else:
        from filelock import FileLock
        with FileLock(str(DATA_DIR / "server.lock"), timeout=0):
            target_engine = create_engine(args.target_url)
            # Target schema comes from Alembic, never from copying SQLite DDL.
            with engine.connect() as source, target_engine.begin() as target:
                for table in Base.metadata.sorted_tables:
                    if target.execute(select(table).limit(1)).first():
                        parser.error(f"目标表 {table.name} 非空，已停止；迁移要求空数据库")
                for table in Base.metadata.sorted_tables:
                    if table.name == "sessions":
                        continue
                    rows = source.execute(select(table)).mappings()
                    # Media BLOBs are copied one row at a time to bound memory.
                    for row in rows:
                        target.execute(table.insert().values(**dict(row)))
            print("数据复制完成。请同时迁移 data/app.key、修改 DATABASE_URL，并在切换前检查用户/项目/素材数量和媒体 SHA256。")

if __name__ == "__main__":
    main()
