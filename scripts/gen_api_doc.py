"""Script that generates the whole of api.md from the docstrings in the
contactglovesdk source code.

The role that Doxygen + Moxygen plays in the C++ version
(ContactGloveSDKv2Cpp) is handled in this project by a small script that uses
only ``ast`` / ``inspect`` from the standard library. pdoc3 is not used.

api.md consists of the following two parts, both generated from docstrings
(no hand-written body text is kept in api.md itself):

* Front matter (overview, requirements, installation, usage): the module
  docstring of the ``contactglovesdk`` package (``__init__.py``) is used
  as-is.
* API reference: generated from the docstring of each class, enum, exception
  and constant.

The docstring conventions this script targets:

* Classes and exception classes: an ordinary docstring (first line = summary,
  the rest = detailed description).
* dataclass fields, enum members and module constants: a string literal
  placed immediately after the assignment (an attribute docstring; the same
  convention as Sphinx, pdoc and others).
* Methods: a one-line summary plus ``Args:`` / ``Returns:`` / ``Raises:``
  sections.

Usage::

    python scripts/gen_api_doc.py            # regenerate api.md
    python scripts/gen_api_doc.py --check    # exit code 1 if there is a diff
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import enum
import inspect
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = ROOT / "contactglovesdk"
API_MD = ROOT / "api.md"

sys.path.insert(0, str(ROOT))

import contactglovesdk as sdk  # noqa: E402


# ---------------------------------------------------------------------------
# Attribute-docstring extraction (ast-based)
# ---------------------------------------------------------------------------


def extract_attribute_docs(source_path: Path) -> Dict[Tuple[Optional[str], str], str]:
    """Parse ``source_path`` and return a dict of
    (class name or None, attribute name) -> docstring.

    A key whose class name is ``None`` represents a module-level constant.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    docs: Dict[Tuple[Optional[str], str], str] = {}

    def visit_body(body: List[ast.stmt], class_name: Optional[str]) -> None:
        pending_name: Optional[str] = None
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit_body(node.body, node.name)
                pending_name = None
                continue
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                pending_name = node.target.id
                continue
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                pending_name = node.targets[0].id
                continue
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and pending_name is not None
            ):
                docs[(class_name, pending_name)] = textwrap.dedent(
                    node.value.value
                ).strip()
                pending_name = None
                continue
            pending_name = None

    visit_body(tree.body, None)
    return docs


_MODELS_ATTR_DOCS = extract_attribute_docs(PACKAGE_DIR / "_models.py")
_CLIENT_ATTR_DOCS = extract_attribute_docs(PACKAGE_DIR / "_client.py")


# ---------------------------------------------------------------------------
# Google-style (Args:/Returns:/Raises:) docstring parsing
#
# Headers must stay ASCII-uppercase-starting keywords because pdoc3's
# Google-style section parser only recognizes ``^([A-Z]\w+):$``. A localized
# header (for example ``引数:``) would silently fall through pdoc3 and render
# as a raw indented code block instead of a proper parameter list.
# ---------------------------------------------------------------------------

_SECTION_HEADERS = {"Args:", "Returns:", "Raises:"}
_ITEM_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
_RST_ROLE_RE = re.compile(r":(?:meth|class|func|attr):`([^`]+)`")


def _looks_like_python(text: str) -> bool:
    """Return whether ``text`` parses as Python as-is.

    Used to decide whether a literal block that cannot be parsed as-is - such
    as the pseudo-schema of a record layout (a sequence of C-like type
    declarations) - should fall back to an unadorned fence.
    """
    try:
        ast.parse(text)
    except SyntaxError:
        return False
    return True


def _strip_rst_roles(text: str) -> str:
    """Convert Sphinx role notation such as ``:meth:`X`` into Markdown code notation."""
    return _RST_ROLE_RE.sub(r"`\1`", text)


def _rst_literal_blocks_to_fences(text: str) -> str:
    """Convert an RST literal block introduced by a trailing ``::`` into a fenced code block."""
    lines = text.split("\n")
    out: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].rstrip()
        if stripped.endswith("::"):
            prefix = stripped[:-2].rstrip()
            if prefix:
                out.append(prefix + ":")
            i += 1
            while i < n and lines[i].strip() == "":
                i += 1
            block: List[str] = []
            while i < n and (lines[i].strip() == "" or lines[i].startswith((" ", "\t"))):
                block.append(lines[i])
                i += 1
            block_text = textwrap.dedent("\n".join(block)).strip("\n")
            lang = "python" if _looks_like_python(block_text) else ""
            out.append("")
            out.append(f"```{lang}")
            out.append(block_text)
            out.append("```")
            out.append("")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


@dataclasses.dataclass
class ParsedDoc:
    summary: str = ""
    body: str = ""
    params: List[Tuple[str, str]] = dataclasses.field(default_factory=list)
    returns: str = ""
    raises: List[Tuple[str, str]] = dataclasses.field(default_factory=list)


def parse_docstring(doc: Optional[str]) -> ParsedDoc:
    if not doc:
        return ParsedDoc()
    doc = inspect.cleandoc(doc)
    lines = doc.split("\n")
    summary = _strip_rst_roles(lines[0].strip())

    body_lines: List[str] = []
    section_lines: Dict[str, List[str]] = {"Args:": [], "Returns:": [], "Raises:": []}
    current: Optional[str] = None

    for line in lines[1:]:
        stripped = line.strip()
        if stripped in _SECTION_HEADERS:
            current = stripped
            continue
        if current is None:
            body_lines.append(line)
        else:
            section_lines[current].append(line)

    body = _strip_rst_roles(_rst_literal_blocks_to_fences("\n".join(body_lines).strip()))
    params = _parse_item_list(section_lines["Args:"])
    returns = _strip_rst_roles(
        " ".join(s.strip() for s in section_lines["Returns:"] if s.strip()).strip()
    )
    raises = _parse_item_list(section_lines["Raises:"])
    return ParsedDoc(summary=summary, body=body, params=params, returns=returns, raises=raises)


def _parse_item_list(lines: List[str]) -> List[Tuple[str, str]]:
    items: List[Tuple[str, str]] = []
    name: Optional[str] = None
    desc_parts: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _ITEM_RE.match(line)
        if m:
            if name is not None:
                items.append((name, _strip_rst_roles(" ".join(desc_parts).strip())))
            name, desc = m.group(1), m.group(2)
            desc_parts = [desc]
        elif name is not None:
            desc_parts.append(line)
    if name is not None:
        items.append((name, _strip_rst_roles(" ".join(desc_parts).strip())))
    return items


# ---------------------------------------------------------------------------
# Type / signature rendering
# ---------------------------------------------------------------------------


_MODULE_PATH_RE = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*\.)+([A-Za-z_][A-Za-z0-9_]*)")


def _normalize_type_str(s: str) -> str:
    s = _MODULE_PATH_RE.sub(r"\1", s)
    s = re.sub(r"\bLedColor\b", "DeviceColor", s)
    s = re.sub(r"Optional\[([^\[\]]+)\]", r"\1 | None", s)
    s = re.sub(r"\bList\[", "list[", s)
    s = re.sub(r"\bDict\[", "dict[", s)
    s = re.sub(r"\bTuple\[", "tuple[", s)
    return s


def _annotation_str(annotation: Any) -> str:
    if annotation is inspect.Signature.empty:
        return ""
    if isinstance(annotation, str):
        s = annotation
    else:
        s = getattr(annotation, "__name__", str(annotation))
    return _normalize_type_str(s)


def _default_str(default: Any) -> str:
    if isinstance(default, enum.Enum):
        return f"{_normalize_type_str(type(default).__name__)}.{default.name}"
    if isinstance(default, str):
        return f'"{default}"'
    return repr(default)


def render_method_signature(name: str, func: Any, *, is_init: bool = False) -> str:
    sig = inspect.signature(func)
    parts = []
    for pname, p in sig.parameters.items():
        if pname == "self":
            if is_init:
                continue
            parts.append("self")
            continue
        seg = pname
        ann = _annotation_str(p.annotation)
        if ann:
            seg += f": {ann}"
        if p.default is not inspect.Parameter.empty:
            seg += f" = {_default_str(p.default)}"
        parts.append(seg)

    header = f"{name}({', '.join(parts)})" if is_init else f"def {name}({', '.join(parts)})"
    ret = _annotation_str(sig.return_annotation)
    if not is_init and ret and ret != "None":
        header += f" -> {ret}"
    return header


def render_field_type(tp: Any) -> str:
    s = tp.__name__ if isinstance(tp, type) else str(tp)
    return _normalize_type_str(s)


# ---------------------------------------------------------------------------
# Markdown rendering helpers
# ---------------------------------------------------------------------------


def esc_cell(s: str) -> str:
    """Escape ``|`` so that it is not mistaken for a column separator inside a Markdown table cell."""
    return s.replace("|", "\\|")


def md_escape_anchor(name: str) -> str:
    # GitHub/Fumadocs remove dots from qualified Python identifiers.
    return name.lower().replace(".", "")


def render_params_returns_raises(parsed: ParsedDoc) -> str:
    out = []
    if parsed.params:
        out.append("#### Parameters")
        out.append("")
        for pname, desc in parsed.params:
            out.append(f"* `{pname}` {desc}")
            out.append("")
    if parsed.returns:
        out.append("#### Returns")
        out.append(parsed.returns)
        out.append("")
    if parsed.raises:
        out.append("#### Raises")
        out.append("")
        for exc, desc in parsed.raises:
            out.append(f"* `{exc}` {desc}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Per-kind renderers
# ---------------------------------------------------------------------------


def is_exception(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseException)


def is_enum(obj: Any) -> bool:
    return isinstance(obj, type) and issubclass(obj, enum.Enum)


def is_dataclass_type(obj: Any) -> bool:
    return isinstance(obj, type) and dataclasses.is_dataclass(obj)


def render_enum(name: str) -> str:
    cls = getattr(sdk, name)
    doc = parse_docstring(cls.__doc__)
    lines = [f"#### {name}", "", "```python", f"class {name}({cls.__bases__[0].__name__})", "```", ""]
    if doc.summary:
        lines.append(doc.summary)
        lines.append("")
    if doc.body:
        lines.append(doc.body)
        lines.append("")
    lines.append("| Value | Description |")
    lines.append("|-------|-------------|")
    for member_name, member in cls.__members__.items():
        desc = _MODELS_ATTR_DOCS.get((name, member_name),
                                    _MODELS_ATTR_DOCS.get((cls.__name__, member_name), ""))
        lines.append(f"| `{member_name}` | {esc_cell(desc)} |")
    lines.append("")
    return "\n".join(lines)


def render_exception(name: str) -> str:
    cls = getattr(sdk, name)
    doc = parse_docstring(cls.__doc__)
    base = cls.__bases__[0].__name__
    lines = [
        f"## {name}",
        "",
        "```python",
        f"from contactglovesdk import {name}",
        "```",
        "",
        "```python",
        f"class {name}({base})",
        "```",
        "",
    ]
    if doc.summary:
        lines.append(doc.summary)
        lines.append("")
    return "\n".join(lines)


def render_constant(name: str) -> str:
    value = getattr(sdk, name)
    doc = _MODELS_ATTR_DOCS.get((None, name), "")
    lines = [
        f"#### {name}",
        "",
        "```python",
        f"{name}: {type(value).__name__} = {value!r}",
        "```",
        "",
        doc,
        "",
    ]
    return "\n".join(lines)


def render_dataclass(name: str) -> str:
    cls = getattr(sdk, name)
    doc = parse_docstring(cls.__doc__)
    hints = _safe_type_hints(cls)
    lines = [
        f"## {name}",
        "",
        "```python",
        f"from contactglovesdk import {name}",
        "```",
        "",
    ]
    if doc.summary:
        lines.append(doc.summary)
        lines.append("")
    if doc.body:
        lines.append(doc.body)
        lines.append("")

    fields = dataclasses.fields(cls)
    lines.append("### Public Attributes")
    lines.append("")
    lines.append("| Type | Name | Description |")
    lines.append("|------|------|-------------|")
    for f in fields:
        tp = render_field_type(hints.get(f.name, f.type))
        desc = _MODELS_ATTR_DOCS.get((name, f.name), "")
        lines.append(
            f"| `{esc_cell(tp)}` | [`{f.name}`](#{md_escape_anchor(name + '.' + f.name)}) | {esc_cell(desc)} |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, f in enumerate(fields):
        tp = render_field_type(hints.get(f.name, f.type))
        desc = _MODELS_ATTR_DOCS.get((name, f.name), "")
        default = _field_default_repr(f)
        lines.append(f"#### {name}.{f.name}")
        lines.append("")
        lines.append("```python")
        code = f"{f.name}: {tp}"
        if default is not None:
            code += f" = {default}"
        lines.append(code)
        lines.append("```")
        lines.append("")
        lines.append(desc)
        if i != len(fields) - 1:
            lines.append("")
            lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _safe_type_hints(cls: type) -> Dict[str, Any]:
    try:
        import typing

        return typing.get_type_hints(cls)
    except Exception:
        return {}


def _field_default_repr(f: dataclasses.Field) -> Optional[str]:
    if f.default is not dataclasses.MISSING:
        return _default_str(f.default)
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        try:
            value = f.default_factory()  # type: ignore[misc]
        except Exception:
            return None
        if isinstance(value, list):
            return "[]" if not value else f"[{_default_str(value[0])}, ...]  # {len(value)} elements"
        return _default_str(value)
    return None


def render_client_class() -> str:
    cls = sdk.ContactGloveClient
    name = cls.__name__
    class_doc = parse_docstring(cls.__doc__)

    lines = [
        f"## {name}",
        "",
        "```python",
        f"from contactglovesdk import {name}",
        "```",
        "",
    ]
    if class_doc.summary:
        lines.append(class_doc.summary)
        lines.append("")
    if class_doc.body:
        lines.append(class_doc.body)
        lines.append("")

    public_methods = []
    for attr_name, attr in vars(cls).items():
        if attr_name.startswith("_") and attr_name != "__init__":
            continue
        if attr_name == "DEFAULT_DS_PORT":
            continue
        if inspect.isfunction(attr) or attr_name == "__init__":
            public_methods.append(attr_name)
        elif isinstance(attr, property):
            public_methods.append(attr_name)

    # Preserve source definition order (dict preserves insertion order).
    lines.append("### Public Methods")
    lines.append("")
    lines.append("| Return | Name | Description |")
    lines.append("|--------|------|-------------|")
    for attr_name in public_methods:
        attr = vars(cls)[attr_name]
        if attr_name == "__init__":
            doc = class_doc
            ret = ""
        elif isinstance(attr, property):
            doc = parse_docstring(attr.fget.__doc__)
            ret = _annotation_str(inspect.signature(attr.fget).return_annotation)
        else:
            doc = parse_docstring(attr.__doc__)
            ret = _annotation_str(inspect.signature(attr).return_annotation)
        ret_cell = f"`{esc_cell(ret)}`" if ret else ""
        anchor = md_escape_anchor(attr_name)
        lines.append(f"| {ret_cell} | [`{attr_name}`](#{anchor}) | {esc_cell(doc.summary)} |")
    lines.append("")
    lines.append("### Class Attributes")
    lines.append("")
    lines.append("| Return | Name | Description |")
    lines.append("|--------|------|-------------|")
    lines.append(
        f"| `int` | [`DEFAULT_DS_PORT`](#default_ds_port) | "
        f"{esc_cell(_CLIENT_ATTR_DOCS.get(('ContactGloveClient', 'DEFAULT_DS_PORT'), ''))} |"
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    for attr_name in public_methods:
        attr = vars(cls)[attr_name]
        if attr_name == "__init__":
            sig_str = render_method_signature(name, attr, is_init=True)
            doc = class_doc
            lines.append("#### `__init__`")
            lines.append("")
            lines.append("```python")
            lines.append(sig_str)
            lines.append("```")
            lines.append("")
            lines.append(render_params_returns_raises(doc))
        elif isinstance(attr, property):
            doc = parse_docstring(attr.fget.__doc__)
            sig_str = render_method_signature(attr_name, attr.fget)
            lines.append(f"#### {attr_name}")
            lines.append("")
            lines.append("```python")
            lines.append("@property")
            lines.append(sig_str)
            lines.append("```")
            lines.append("")
            if doc.summary:
                lines.append(doc.summary)
                lines.append("")
        else:
            doc = parse_docstring(attr.__doc__)
            sig_str = render_method_signature(attr_name, attr)
            lines.append(f"#### {attr_name}")
            lines.append("")
            lines.append("```python")
            lines.append(sig_str)
            lines.append("```")
            lines.append("")
            if doc.summary:
                lines.append(doc.summary)
                lines.append("")
            if doc.body:
                lines.append(doc.body)
                lines.append("")
            lines.append(render_params_returns_raises(doc))
        lines.append("---")
        lines.append("")

    lines.append(f"#### DEFAULT_DS_PORT")
    lines.append("")
    lines.append("```python")
    lines.append(f"DEFAULT_DS_PORT: int = {cls.DEFAULT_DS_PORT!r}")
    lines.append("```")
    lines.append("")
    lines.append(_CLIENT_ATTR_DOCS.get(("ContactGloveClient", "DEFAULT_DS_PORT"), ""))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level overview tables + full document assembly
# ---------------------------------------------------------------------------

CLASS_NAMES = [
    "ContactGloveClient",
    "Host",
    "GloveData",
    "ControllerData",
    "ErgonomicsData",
    "SkeletonData",
    "RawSkeletonData",
    "RawSensorData",
    "RetargetProfileInfo",
    "Transform",
    "Vec3",
    "Quaternion",
]
ENUM_NAMES = [
    "DeviceFamilyType",
    "DeviceColor",
    "DeviceConnectedState",
    "ButtonStatus",
    "TrackingState",
    "ErgonomicsIndex",
    "SkeletonNode",
    "SkeletonRotationNode",
    "RawSensorIndex",
]
EXCEPTION_NAMES = [
    "ContactGloveSDKError",
    "SDKNotAvailableError",
    "NotConnectedError",
    "InvalidIDError",
]
CONSTANT_NAMES = [
    "ERGONOMICS_COUNT",
    "SKELETON_NODE_COUNT",
    "SKELETON_ROTATION_COUNT",
    "RAW_SENSOR_COUNT",
]


def class_summary(name: str) -> str:
    cls = getattr(sdk, name)
    return parse_docstring(cls.__doc__).summary


def render_overview_tables() -> str:
    lines = [
        "## Defined types and functions",
        "",
        "The types and functions that this SDK defines and makes available are as follows.",
        "",
    ]

    lines.append("### Classes")
    lines.append("")
    lines.append("| Name | Description |")
    lines.append("|------|-------------|")
    for name in CLASS_NAMES:
        lines.append(f"| [`{name}`](#{md_escape_anchor(name)}) | {esc_cell(class_summary(name))} |")
    lines.append("")

    lines.append("### Enumerations")
    lines.append("")
    lines.append("| Name | Description |")
    lines.append("|------|-------------|")
    for name in ENUM_NAMES:
        lines.append(f"| [`{name}`](#{md_escape_anchor(name)}) | {esc_cell(class_summary(name))} |")
    lines.append("")

    lines.append("### Exceptions")
    lines.append("")
    lines.append("| Name | Description |")
    lines.append("|------|-------------|")
    for name in EXCEPTION_NAMES:
        lines.append(f"| [`{name}`](#{md_escape_anchor(name)}) | {esc_cell(class_summary(name))} |")
    lines.append("")

    lines.append("### Constants")
    lines.append("")
    lines.append("| Name | Value | Description |")
    lines.append("|------|-------|-------------|")
    for name in CONSTANT_NAMES:
        value = getattr(sdk, name)
        doc = _MODELS_ATTR_DOCS.get((None, name), "")
        lines.append(f"| [`{name}`](#{md_escape_anchor(name)}) | `{value}` | {esc_cell(doc)} |")
    lines.append("")
    return "\n".join(lines)


def render_reference_section() -> str:
    parts = [render_overview_tables(), "---", ""]

    for name in ENUM_NAMES:
        parts.append(render_enum(name))
        parts.append("---")
        parts.append("")

    for name in CONSTANT_NAMES:
        parts.append(render_constant(name))
        parts.append("---")
        parts.append("")

    # Drop the trailing "---" left over from the constants loop, matching
    # the C++ reference's layout (no separator before the first class).
    if parts and parts[-2] == "---":
        parts.pop(-2)

    parts.append("")
    for name in CLASS_NAMES:
        if name == "ContactGloveClient":
            parts.append(render_client_class())
        else:
            parts.append(render_dataclass(name))
        parts.append("")

    for name in EXCEPTION_NAMES:
        parts.append(render_exception(name))
        parts.append("")

    text = "\n".join(parts)
    return re.sub(r"\n{3,}", "\n\n", text)


def render_front_matter() -> str:
    """Use the module docstring of the ``contactglovesdk`` package as the front matter of api.md."""
    doc = inspect.getdoc(sdk) or ""
    return f"# ContactGlove Python SDK V2\n\n{doc}".rstrip() + "\n"


def render_document() -> str:
    front_matter = render_front_matter()
    reference = render_reference_section().rstrip() + "\n"
    text = f"{front_matter}\n{reference}"
    return re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; return exit code 1 if there is a diff",
    )
    args = parser.parse_args()

    new_text = render_document()

    if args.check:
        current = API_MD.read_text(encoding="utf-8") if API_MD.exists() else None
        if current != new_text:
            print("api.md is out of date. Run: python scripts/gen_api_doc.py", file=sys.stderr)
            return 1
        return 0

    # Path.write_text() applies the platform default newline translation
    # (CRLF on Windows), which would make api.md inconsistent with every
    # other LF-only file in the repo. Force LF explicitly.
    with open(API_MD, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_text)
    print(f"Wrote {API_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
