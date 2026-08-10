"""对可配置 Python 正则做保守的回溯风险门禁。"""

from __future__ import annotations

import re
from typing import Any

from memoryhub.safety_rules.errors import RuleLibraryError

try:
    from re import _constants as sre_constants  # type: ignore[attr-defined]  # Python 3.11+
    from re import _parser as sre_parser  # type: ignore[attr-defined]
except ImportError:  # Python 3.10 及更早：内部模块尚未改名，使用 sre_parse/sre_constants
    try:
        import sre_constants as _sre_constants  # type: ignore[import-not-found]
        import sre_parse as _sre_parser  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - 仅用于未来 Python 同时移除两者时失败关闭
        sre_constants = None
        sre_parser = None
    else:
        sre_constants = _sre_constants
        sre_parser = _sre_parser


def _nested_tokens(subpattern: Any) -> list[Any]:
    children: list[Any] = []
    if sre_constants is None:
        return children
    for operation, argument in subpattern:
        if operation is sre_constants.SUBPATTERN:
            children.append(argument[-1])
        elif operation is sre_constants.BRANCH:
            children.extend(argument[1])
        elif operation in (sre_constants.ASSERT, sre_constants.ASSERT_NOT):
            children.append(argument[1])
        elif operation is sre_constants.GROUPREF_EXISTS:
            children.extend(branch for branch in argument[1:] if branch is not None)
        elif operation is getattr(sre_constants, "ATOMIC_GROUP", object()):
            children.append(argument)
    return children


def _contains_branch_or_repeat(subpattern: Any) -> bool:
    if sre_constants is None:
        return True
    repeat_operations = {
        sre_constants.MAX_REPEAT,
        sre_constants.MIN_REPEAT,
        getattr(sre_constants, "POSSESSIVE_REPEAT", object()),
    }
    for operation, argument in subpattern:
        if operation is sre_constants.BRANCH or operation in repeat_operations:
            return True
        if operation is sre_constants.SUBPATTERN and _contains_branch_or_repeat(
            argument[-1]
        ):
            return True
        if operation in (sre_constants.ASSERT, sre_constants.ASSERT_NOT):
            if _contains_branch_or_repeat(argument[1]):
                return True
        if operation is sre_constants.GROUPREF_EXISTS:
            if any(
                branch is not None and _contains_branch_or_repeat(branch)
                for branch in argument[1:]
            ):
                return True
    return False


def _category_ascii_chars(category: Any) -> set[int] | None:
    if sre_constants is None:
        return None
    digits = set(range(ord("0"), ord("9") + 1))
    spaces = {9, 10, 11, 12, 13, 32}
    word = (
        digits
        | set(range(ord("A"), ord("Z") + 1))
        | set(range(ord("a"), ord("z") + 1))
        | {ord("_")}
    )
    universe = set(range(128))
    categories = {
        sre_constants.CATEGORY_DIGIT: digits,
        sre_constants.CATEGORY_NOT_DIGIT: universe - digits,
        sre_constants.CATEGORY_SPACE: spaces,
        sre_constants.CATEGORY_NOT_SPACE: universe - spaces,
        sre_constants.CATEGORY_WORD: word,
        sre_constants.CATEGORY_NOT_WORD: universe - word,
    }
    return categories.get(category)


def _casefold_ascii(characters: set[int]) -> set[int]:
    result = set(characters)
    for character in tuple(characters):
        if ord("A") <= character <= ord("Z"):
            result.add(character + 32)
        elif ord("a") <= character <= ord("z"):
            result.add(character - 32)
    return result


def _single_atom_ascii_chars(subpattern: Any) -> set[int] | None:
    """给相邻 repeat 做保守的 ASCII 重叠判断；未知原子返回 None。"""
    if sre_constants is None or len(subpattern) != 1:
        return None
    operation, argument = subpattern[0]
    if operation is sre_constants.SUBPATTERN:
        return _single_atom_ascii_chars(argument[-1])
    if operation is sre_constants.LITERAL:
        return _casefold_ascii({argument})
    if operation is sre_constants.NOT_LITERAL:
        if argument >= 128:
            return None
        return set(range(128)) - _casefold_ascii({argument})
    if operation is sre_constants.ANY:
        return set(range(128))
    if operation is sre_constants.CATEGORY:
        return _category_ascii_chars(argument)
    if operation is not sre_constants.IN:
        return None

    negate = False
    characters: set[int] = set()
    for item_operation, item_argument in argument:
        if item_operation is sre_constants.NEGATE:
            negate = True
        elif item_operation is sre_constants.LITERAL:
            characters.add(item_argument)
        elif item_operation is sre_constants.RANGE:
            lower, upper = item_argument
            if lower < 128:
                characters.update(range(lower, min(upper, 127) + 1))
        elif item_operation is sre_constants.CATEGORY:
            category_chars = _category_ascii_chars(item_argument)
            if category_chars is None:
                return None
            characters.update(category_chars)
        else:
            return None
    characters = _casefold_ascii(characters)
    return set(range(128)) - characters if negate else characters


def _validate_subpattern(subpattern: Any, *, inside_repeat: bool = False) -> None:
    if sre_constants is None:
        raise RuleLibraryError("Python regex safety parser is unavailable")
    repeat_operations = {
        sre_constants.MAX_REPEAT,
        sre_constants.MIN_REPEAT,
        getattr(sre_constants, "POSSESSIVE_REPEAT", object()),
    }
    previous_repeat_chars: set[int] | None = None
    previous_was_repeat = False
    for operation, argument in subpattern:
        if operation in repeat_operations:
            _, maximum, child = argument
            repeated = maximum == sre_constants.MAXREPEAT or maximum > 1
            if inside_repeat:
                raise RuleLibraryError(
                    "rule pattern contains nested backtracking repeats"
                )
            if repeated and _contains_branch_or_repeat(child):
                raise RuleLibraryError(
                    "repeated groups may not contain branches or other repeats"
                )
            if maximum != sre_constants.MAXREPEAT and maximum > 4_096:
                raise RuleLibraryError("bounded repeat exceeds the safety limit")
            current_chars = _single_atom_ascii_chars(child)
            if previous_was_repeat and (
                previous_repeat_chars is None
                or current_chars is None
                or previous_repeat_chars & current_chars
            ):
                raise RuleLibraryError(
                    "adjacent backtracking repeats have overlapping candidates"
                )
            previous_was_repeat = True
            previous_repeat_chars = current_chars
            _validate_subpattern(child, inside_repeat=repeated)
            continue
        if operation is sre_constants.BRANCH:
            if inside_repeat:
                raise RuleLibraryError(
                    "alternation inside a repeated group is not allowed"
                )
            for branch in argument[1]:
                _validate_subpattern(branch, inside_repeat=False)
            previous_was_repeat = False
            previous_repeat_chars = None
            continue
        for child in _nested_tokens([(operation, argument)]):
            _validate_subpattern(child, inside_repeat=inside_repeat)
        # Anchors, lookarounds, and an empty capture group consume no input.
        # They must not break adjacency tracking: otherwise patterns such as
        # ``a*()a*`` evade the overlapping-repeat check and can become high-order
        # backtracking chains when repeated.
        if operation in (
            sre_constants.AT,
            sre_constants.ASSERT,
            sre_constants.ASSERT_NOT,
        ) or (operation is sre_constants.SUBPATTERN and len(argument[-1]) == 0):
            continue
        previous_was_repeat = False
        previous_repeat_chars = None


def validate_regex_safety(pattern: str) -> None:
    """
    拒绝常见指数/高阶回溯结构。

    这是保守的发布门禁，不是形式化证明；外部规则文件仍必须来自受信任来源，
    后续扫描器也必须限制单字段长度和执行预算。
    """
    if sre_parser is None:
        raise RuleLibraryError("Python regex safety parser is unavailable")
    try:
        parsed = sre_parser.parse(pattern, 0)
    except (re.error, RecursionError) as exc:
        raise RuleLibraryError(f"invalid rule pattern: {exc}") from exc
    _validate_subpattern(parsed)
