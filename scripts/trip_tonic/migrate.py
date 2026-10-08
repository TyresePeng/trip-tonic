"""Schema 版本迁移链。

每个步骤把"源版本模式"映射到目标版本并就地修改 guide。
未来新增 1.1 步骤只需向 _STEPS 和 KNOWN_VERSIONS 追加条目；
CLI 暴露 --target，让用户固定目标版本而不是永远跳到最新。
"""

KNOWN_VERSIONS = ("1.0",)


class MigrateError(ValueError):
    """迁移失败：未知目标版本或没有可用迁移路径。"""


def _to_1_0(guide):
    """升级到 1.0：当前仅设置 schema_version 标记。"""
    guide["schema_version"] = "1.0"
    return "1.0"


# (源版本匹配函数, 目标版本, 步骤函数)
_STEPS = (
    (lambda version: version is None, "1.0", _to_1_0),
    (lambda version: isinstance(version, str) and version.startswith("0."), "1.0", _to_1_0),
)


def migrate_guide(guide, target="1.0"):
    """逐步应用迁移直到 guide 达到 target 版本。

    返回 (changed, applied_steps)；无可用路径时抛 MigrateError。
    循环上限为 len(_STEPS)+1 步，超出说明链条存在环或无法收敛。
    """
    if target not in KNOWN_VERSIONS:
        raise MigrateError("未知的 schema_version 目标 {!r}；可用目标：{}".format(target, "/".join(KNOWN_VERSIONS)))
    version = guide.get("schema_version")
    if version == target:
        return False, []
    applied = []
    for _ in range(len(_STEPS) + 1):
        if version == target:
            return True, applied
        # 找第一个匹配当前版本且目标不是自身的步骤
        step = next((entry for entry in _STEPS if entry[0](version) and entry[1] != version), None)
        if step is None:
            raise MigrateError("未知的 schema_version {!r}；没有到 {} 的迁移路径".format(version, target))
        version = step[2](guide)
        applied.append(version)
    raise MigrateError("迁移步骤未能收敛到 {}，请检查 schema_version".format(target))
