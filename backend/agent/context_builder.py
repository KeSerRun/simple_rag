"""ContextBuilder: 从一个或多个 prompts/ 目录加载 identity 与 skills,按 skill 组装 OpenAI messages

支持的 skill 布局:
1. 扁平: <prompts_dir>/skills/<skill>.md
2. 嵌套 (Claude Code 风格): <prompts_dir>/skills/<skill>/SKILL.md (或 skill.md)

skill 文件格式 (YAML-like frontmatter + markdown body):

    ---
    name: skill_name
    description: 一句话描述
    include_identity: true|false
    inputs:
      - var1
      - var2
    ---

    Markdown body with {var1} and {var2} placeholders.

多目录加载语义:
- 第一个目录是"基线",其 identity.md 是主身份;后续目录的 identity.md 仅被忽略并 log
- 同名 skill 后加载的覆盖前面,并打 warning
- 核心 skill (CORE_SKILLS) 只允许从基线目录加载,后续目录的同名 skill 被拒绝

调用:
    cb = ContextBuilder(["prompts", "third_party_skills"])
    messages = cb.build_messages("answer_with_context", context=ctx, query=q, history=hist)
    client.chat(messages=messages, model=...)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

from base.logger import logger

# RAG agent 化之后, 答题流程改由 identity + tools 驱动, 没有核心 skill 需要保护
CORE_SKILLS: frozenset = frozenset()


@dataclass
class Skill:
    name: str
    description: str
    inputs: list
    template: str
    include_identity: bool
    source: str = ""
    meta: dict = field(default_factory=dict)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _coerce_bool(s: str):
    low = s.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    return s


def parse_frontmatter(text: str) -> tuple:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta = m.group(1)
    body = m.group(2).strip("\n")
    return _parse_yaml_block(raw_meta), body


def _parse_yaml_block(text: str) -> dict:
    result: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "|":
            # 多行字面块: key: |\n  line1\n  line2
            lines_joined = []
            i += 1
            if i < len(lines):
                indent = len(lines[i]) - len(lines[i].lstrip())
                while i < len(lines):
                    nxt = lines[i]
                    stripped = nxt.strip()
                    if stripped == "":
                        lines_joined.append("")
                        i += 1
                        continue
                    if len(nxt) - len(nxt.lstrip()) >= indent:
                        lines_joined.append(stripped)
                        i += 1
                    else:
                        break
            result[key] = " ".join(lines_joined)
        elif value:
            result[key] = _coerce_bool(_strip_quotes(value))
            i += 1
        else:
            items: list = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if nxt.lstrip().startswith("-"):
                    items.append(_strip_quotes(nxt.lstrip()[1:].strip()))
                    i += 1
                else:
                    break
            result[key] = items
    return result


class ContextBuilder:
    def __init__(
        self,
        prompts_dirs: Union[str, Path, Iterable[Union[str, Path]]],
        core_skills: frozenset = CORE_SKILLS,
    ):
        if isinstance(prompts_dirs, (str, Path)):
            dirs = [Path(prompts_dirs)]
        else:
            dirs = [Path(d) for d in prompts_dirs]
        if not dirs:
            raise ValueError("prompts_dirs 不能为空")
        if not dirs[0].is_dir():
            raise FileNotFoundError(f"基线 prompts 目录不存在: {dirs[0]}")
        self.prompts_dirs = dirs
        self.core_skills = core_skills
        self.identity: str = self._load_identity()
        for d in self.prompts_dirs[1:]:
            if not d.is_dir():
                logger.warning(f"prompts 目录不存在,跳过: {d}")
                continue
            if (d / "identity.md").exists():
                logger.info(f"第三方目录 {d} 中的 identity.md 被忽略(只允许基线目录定义身份)")
        self.skills: dict = {}
        for idx, d in enumerate(self.prompts_dirs):
            if not d.is_dir():
                continue
            is_baseline = idx == 0
            self._load_skills_from(d, is_baseline)
        logger.info(
            f"ContextBuilder 就绪: identity={'是' if self.identity else '否'}, "
            f"skills={sorted(self.skills.keys())}"
        )

    def _load_identity(self) -> str:
        f = self.prompts_dirs[0] / "identity.md"
        if not f.exists():
            return ""
        return f.read_text(encoding="utf-8").strip()

    def _load_skills_from(self, prompts_dir: Path, is_baseline: bool):
        skills_dir = prompts_dir / "skills"
        if not skills_dir.is_dir():
            return
        for file, fallback in self._scan_skills(skills_dir):
            self._register(self._load_one(file, fallback_name=fallback), is_baseline)

    def _scan_skills(self, root: Path):
        for f in sorted(root.glob("*.md")):
            if f.name.lower() in ("skill.md", "readme.md"):
                continue
            yield f, f.stem
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            skill_file = self._find_skill_file(sub)
            if skill_file is not None:
                yield skill_file, sub.name
            else:
                yield from self._scan_skills(sub)

    @staticmethod
    def _find_skill_file(directory: Path) -> Optional[Path]:
        for name in ("SKILL.md", "skill.md"):
            f = directory / name
            if f.exists():
                return f
        return None

    def _load_one(self, file: Path, fallback_name: str) -> Optional[Skill]:
        try:
            text = file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            name = meta.get("name") or fallback_name
            inputs = meta.get("inputs") or []
            if not isinstance(inputs, list):
                inputs = [inputs]
            return Skill(
                name=str(name),
                description=str(meta.get("description", "")),
                inputs=list(inputs),
                template=body,
                include_identity=bool(meta.get("include_identity", False)),
                source=str(file.resolve()),
                meta=meta,
            )
        except Exception as e:
            logger.error(f"加载 skill 失败 {file}: {e}")
            return None

    def _register(self, skill: Optional[Skill], is_baseline: bool):
        if skill is None:
            return
        existing = self.skills.get(skill.name)
        if existing is not None:
            if skill.name in self.core_skills and not is_baseline:
                logger.warning(
                    f"拒绝覆盖核心 skill '{skill.name}': 仅基线目录可定义, "
                    f"忽略 {skill.source}(已存在: {existing.source})"
                )
                return
            logger.warning(f"skill '{skill.name}' 被覆盖: {skill.source} 覆盖 {existing.source}")
        self.skills[skill.name] = skill

    def build_messages(
        self, skill: str, *, include_identity: Optional[bool] = None,
        history: Optional[list] = None, **variables,
    ) -> list:
        if skill not in self.skills:
            raise KeyError(f"未知 skill: {skill}。已加载: {sorted(self.skills.keys())}")
        s = self.skills[skill]
        missing = [k for k in s.inputs if k not in variables]
        if missing:
            raise ValueError(f"skill '{skill}' 缺少变量: {missing}")
        try:
            user_content = s.template.format(**variables)
        except KeyError as e:
            raise ValueError(f"skill '{skill}' 模板中存在未提供的占位符 {e}") from None
        use_identity = s.include_identity if include_identity is None else include_identity
        messages: list = []
        if use_identity and self.identity:
            messages.append({"role": "system", "content": self.identity})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        return messages

    def list_skills(self) -> dict:
        return {name: s.source for name, s in self.skills.items()}
