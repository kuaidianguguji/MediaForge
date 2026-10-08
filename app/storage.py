import hashlib
from pathlib import Path
from sqlalchemy import func, select
from .config import USER_QUOTA
from .db import Asset, Setting
from .security import decrypt

def add_asset(db, project, data, name, mime, role, meta=None):
    usage = db.scalar(select(func.coalesce(func.sum(Asset.size), 0)).where(Asset.owner_id == project.owner_id))
    if usage + len(data) > USER_QUOTA:
        raise ValueError("用户存储额度不足，请联系管理员增加 VIO_USER_QUOTA_MB")
    asset = Asset(project_id=project.id, owner_id=project.owner_id, name=Path(name).name[:240], mime=mime,
                  role=role, data=data, size=len(data), sha256=hashlib.sha256(data).hexdigest(), meta=meta or {})
    db.add(asset)
    db.flush()
    return asset

def storage_settings(db):
    row = db.get(Setting, "storage")
    if not row or not row.value.get("enabled"):
        raise ValueError("请管理员先配置并启用火山 TOS，用于向视频模型提供可访问的参考素材")
    settings = dict(row.value)
    settings["secret_access_key"] = decrypt(settings.pop("secret_cipher", ""))
    if not settings["secret_access_key"]:
        raise ValueError("TOS Secret Access Key 尚未配置")
    return settings

def asset_json(asset):
    return {"id": asset.id, "name": asset.name, "role": asset.role, "mime": asset.mime,
            "size": asset.size, "meta": asset.meta, "url": f"/api/assets/{asset.id}", "created_at": asset.created_at}
