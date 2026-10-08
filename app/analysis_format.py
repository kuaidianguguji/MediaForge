"""Conservative compatibility for analysis JSON returned by model gateways.

This module repairs representation, never product facts or the shot timeline.
Every transformation operates on a copy so a saved model response stays intact.
"""
from copy import deepcopy
from typing import Any, Iterable

from pydantic import ValidationError


Path = tuple[str | int, ...]
PROFILE_LISTS = frozenset({"features", "parts", "known_views", "unknowns", "forbidden_traits"})
SHOT_LISTS = frozenset({"visible_parts", "missing_views", "constraints"})
SHOT_TEXT = frozenset({"description", "adaptation", "interaction"})
SEGMENT_TEXT = frozenset({"prompt", "voiceover", "subtitle", "risk", "repair_prompt"})
ROOT_TEXT = frozenset({"summary", "product_identity", "transcript", "image_assessment"})

_LABELS = {
    "summary": "分析摘要", "product_identity": "产品识别", "risks": "风险说明",
    "product_profile": "产品特征", "features": "外观特征", "parts": "产品部件",
    "known_views": "已有视角", "unknowns": "未知结构", "forbidden_traits": "禁止出现的特征",
    "sampling": "采样记录", "shots": "镜头", "segments": "生成片段",
    "description": "画面描述", "adaptation": "替换方案", "visible_parts": "可见部件",
    "missing_views": "缺少的视角", "constraints": "限制条件", "interaction": "交互动作",
    "product_visibility": "产品可见程度", "strategy": "生成策略",
    "reference_image_indices": "参考图片编号", "shot_indices": "镜头编号",
    "start": "开始时间", "end": "结束时间", "index": "片段编号",
    "duration": "时长", "generation_duration": "生成时长", "prompt": "生成提示词",
    "voiceover": "口播文案", "subtitle": "字幕", "risk": "风险说明",
    "repair_prompt": "修复提示词", "transcript": "语音转写", "image_assessment": "图片评估",
    "estimated_cost": "费用估算", "estimated_cost_note": "费用说明",
}


def _field_label(path: Iterable[str | int]) -> str:
    """Do not include untrusted field names in user-facing errors."""
    parts = list(path)
    labels: list[str] = []
    i = 0
    while i < len(parts):
        part = parts[i]
        if part in {"shots", "segments"} and i + 1 < len(parts) and type(parts[i + 1]) is int:
            labels.append(f"{_LABELS[part]} {parts[i + 1] + 1}")
            i += 2
            continue
        if type(part) is int:
            labels.append(f"第 {part + 1} 项")
        elif isinstance(part, str):
            labels.append(_LABELS.get(part, "字段"))
        i += 1
    return "的".join(labels) or "分镜时间线或内容"


def normalize_analysis_payload(payload: Any) -> tuple[dict, list[str]]:
    """Normalize safe optional values without inventing shots, times or prompts.

    Strings in known text-list fields become a *single* list item, including
    punctuation and embedded line breaks. Missing fields and invalid structures
    are left for schema validation. Null optional fields use their empty defaults.
    """
    if not isinstance(payload, dict):
        raise ValueError("分析模型返回的结果必须是 JSON 对象")
    result = deepcopy(payload)
    changes: list[str] = []

    def empty_null(container: dict, key: str, empty: Any, path: Path) -> None:
        if key in container and container[key] is None:
            container[key] = deepcopy(empty)
            changes.append(f"{_field_label(path)}：空值已规范为默认值")

    def text_list(container: dict, key: str, path: Path) -> None:
        if key not in container:
            return
        if isinstance(container[key], str):
            container[key] = [container[key]]
            changes.append(f"{_field_label(path)}：单条文本已规范为列表")
        elif container[key] is None:
            empty_null(container, key, [], path)

    text_list(result, "risks", ("risks",))
    for key in sorted(ROOT_TEXT):
        empty_null(result, key, "", (key,))
    empty_null(result, "product_profile", {}, ("product_profile",))
    empty_null(result, "sampling", {}, ("sampling",))
    empty_null(result, "shots", [], ("shots",))

    profile = result.get("product_profile")
    if isinstance(profile, dict):
        for key in sorted(PROFILE_LISTS):
            text_list(profile, key, ("product_profile", key))

    shots = result.get("shots")
    if isinstance(shots, list):
        for index, shot in enumerate(shots):
            if not isinstance(shot, dict):
                continue
            for key in sorted(SHOT_LISTS):
                text_list(shot, key, ("shots", index, key))
            for key in sorted(SHOT_TEXT):
                empty_null(shot, key, "", ("shots", index, key))
            empty_null(shot, "reference_image_indices", [], ("shots", index, "reference_image_indices"))

    segments = result.get("segments")
    if isinstance(segments, list):
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            # The required prompt is deliberately excluded: null is not a prompt.
            for key in sorted(SEGMENT_TEXT - {"prompt"}):
                empty_null(segment, key, "", ("segments", index, key))
            for key in ("shot_indices", "reference_image_indices"):
                empty_null(segment, key, [], ("segments", index, key))
    return result, changes


def validation_error_summary(error: ValidationError) -> str:
    """Return a bounded Chinese explanation without raw values or debug URLs."""
    errors = error.errors(include_url=False, include_context=False, include_input=False)
    descriptions: list[str] = []
    reasons = {
        "list_type": "需要列表", "string_type": "需要文本", "dict_type": "需要对象",
        "model_type": "需要完整对象", "model_attributes_type": "需要完整对象",
        "missing": "缺少必填内容", "literal_error": "选项值不受支持",
        "int_type": "需要整数", "int_parsing": "需要整数", "int_from_float": "需要整数",
        "float_type": "需要有效数字", "float_parsing": "需要有效数字",
        "finite_number": "需要有限数字", "greater_than": "数值过小",
        "greater_than_equal": "数值过小", "less_than": "数值过大", "less_than_equal": "数值过大",
        "string_too_short": "内容为空或过短", "string_too_long": "内容超过允许长度",
        "too_short": "项目数量不足", "too_long": "项目数量超过限制",
    }
    # Only recognize exact messages raised by our own schema validators.
    # Arbitrary value_error messages may contain input or gateway response text.
    timeline_reasons = {
        "Value error, 镜头结束时间不能早于开始时间": "结束时间早于开始时间",
        "Value error, 镜头必须有正时长，且不能超出分镜总时长": "镜头必须有正时长，且不能超出分镜总时长",
        "Value error, 片段 index 必须从 0 顺序排列，时间线必须连续且不重叠": "生成片段须顺序排列，且时间线连续、不重叠",
    }
    for item in errors:
        known_timeline = timeline_reasons.get(item.get("msg")) if item.get("type") == "value_error" else None
        if known_timeline:
            location = item.get("loc", ())
            description = f"{_field_label(location)}的{known_timeline}" if location else known_timeline
        else:
            description = f"{_field_label(item.get('loc', ()))}{reasons.get(item.get('type'), '不符合要求')}"
        if description not in descriptions:
            descriptions.append(description)
    shown = descriptions[:3]
    if len(descriptions) > len(shown):
        shown.append("其余错误已记录")
    return f"分镜结果校验未通过（共 {len(errors)} 处）：" + "；".join(shown) + "。"


def _text_kind(path: Path) -> str | None:
    """Allow only known text fields, including items inside text lists."""
    if len(path) == 1 and path[0] in ROOT_TEXT:
        return "text"
    if path and path[0] == "risks":
        if len(path) == 1:
            return "list"
        if len(path) == 2 and type(path[1]) is int and path[1] >= 0:
            return "text"
    if len(path) >= 2 and path[0] == "product_profile" and path[1] in PROFILE_LISTS:
        if len(path) == 2:
            return "list"
        if len(path) == 3 and type(path[2]) is int and path[2] >= 0:
            return "text"
    if len(path) >= 3 and path[0] in {"shots", "segments"} and type(path[1]) is int and path[1] >= 0:
        fields = SHOT_TEXT if path[0] == "shots" else SEGMENT_TEXT
        if len(path) == 3 and path[2] in fields:
            return "text"
        if path[0] == "shots" and path[2] in SHOT_LISTS:
            if len(path) == 3:
                return "list"
            if len(path) == 4 and type(path[3]) is int and path[3] >= 0:
                return "text"
    return None


def _at_path(payload: Any, path: Path) -> Any:
    value = payload
    for key in path:
        if isinstance(value, dict) and isinstance(key, str) and key in value:
            value = value[key]
        elif isinstance(value, list) and type(key) is int and 0 <= key < len(value):
            value = value[key]
        else:
            raise ValueError("修复字段不存在")
    return value


def _text_leaves(value: Any, depth: int = 0) -> list[str] | None:
    if depth > 32:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        # Keys such as "forbidden" or "required" carry product instructions.
        # Dropping them would change meaning despite preserving all text values.
        if len(value) != 1 or next(iter(value)) not in {"text", "content", "value"}:
            return None
        return _text_leaves(next(iter(value.values())), depth + 1)
    if isinstance(value, list):
        children = value
        result: list[str] = []
        for child in children:
            leaves = _text_leaves(child, depth + 1)
            if leaves is None:
                return None
            result.extend(leaves)
        return result
    return None


def eligible_repair_paths(error: ValidationError, payload: dict | None = None) -> list[Path]:
    """Select existing text-only format errors, excluding content/timeline errors.

    Supplying the payload also verifies the path still exists in that result.
    Numeric, boolean and null leaves cannot be translated into new text. Dicts
    are accepted only as a single neutral text/content/value wrapper; instruction
    keys such as forbidden/required cannot safely be dropped.
    """
    paths: list[Path] = []
    for item in error.errors(include_url=False, include_context=False):
        path = tuple(item.get("loc", ()))
        if item.get("type") not in {"list_type", "string_type"} or not _text_kind(path):
            continue
        try:
            value = _at_path(payload, path) if payload is not None else item.get("input")
        except ValueError:
            continue
        if _text_leaves(value) is not None and path not in paths:
            paths.append(path)
    return paths


def apply_format_patches(payload: dict, patches: Any, allowed_paths: Iterable[Path]) -> dict:
    """Apply an exact, content-preserving set of explicitly requested patches.

    A patch is {"path": ["shots", 0, "constraints"], "value": ["text"]}.
    Text leaves must stay in their original order and preserve every non-space
    character; only grouping and whitespace can change. The original is intact
    even if a later patch fails validation.
    """
    if not isinstance(payload, dict) or not isinstance(patches, list):
        raise ValueError("格式修复结果必须包含字段补丁列表")
    allowed = {tuple(path) for path in allowed_paths}
    if not allowed or any(not _text_kind(path) for path in allowed):
        raise ValueError("格式修复包含不允许修改的字段")
    result = deepcopy(payload)
    seen: set[Path] = set()
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != {"path", "value"}:
            raise ValueError("格式修复补丁结构不正确")
        raw_path = patch["path"]
        if not isinstance(raw_path, list) or any(type(part) not in {str, int} for part in raw_path):
            raise ValueError("格式修复字段路径不正确")
        path = tuple(raw_path)
        if path not in allowed or path in seen:
            raise ValueError("格式修复包含额外或重复的字段")
        previous = _at_path(payload, path)
        old_leaves = _text_leaves(previous)
        replacement = patch["value"]
        if _text_kind(path) == "text":
            if not isinstance(replacement, str):
                raise ValueError("格式修复后的字段必须是文本")
            new_leaves = [replacement]
        else:
            if not isinstance(replacement, list) or any(not isinstance(item, str) for item in replacement):
                raise ValueError("格式修复后的字段必须是文本列表")
            new_leaves = replacement
        if old_leaves is None:
            raise ValueError("格式修复不能新增或推断内容")
        compact = lambda leaves: "".join("".join(text.split()) for text in leaves)
        if compact(old_leaves) != compact(new_leaves):
            raise ValueError("格式修复改变了原有文字内容")
        parent = _at_path(result, path[:-1])
        parent[path[-1]] = deepcopy(replacement)
        seen.add(path)
    if seen != allowed:
        raise ValueError("格式修复未覆盖全部错误字段")
    return result
