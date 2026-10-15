#!/usr/bin/env python3
"""Render a Foundry VTT actor export to interactive HTML/PDF sheets.

Current support is focused on the dnd5e system and D&D 2024-style actor data.
"""

from __future__ import annotations

import argparse
import ast
import base64
import colorsys
import html
import json
import math
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import emblems
import fightclub
import systems

APP_VERSION = "0.4.0"
APP_STORAGE_VERSION = APP_VERSION.replace(".", "-")

ABILITY_ORDER = ["str", "dex", "con", "int", "wis", "cha"]
ABILITY_LABELS = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}
SCHOOL_LABELS = {
    "abj": "Abjuration",
    "con": "Conjuration",
    "div": "Divination",
    "enc": "Enchantment",
    "evo": "Evocation",
    "ill": "Illusion",
    "nec": "Necromancy",
    "trs": "Transmutation",
}
SPELL_PROPERTY_LABELS = {
    "vocal": "V",
    "somatic": "S",
    "material": "M",
    "concentration": "Concentration",
    "ritual": "Ritual",
}
SKILLS = [
    ("acr", "Acrobatics", "dex"),
    ("ani", "Animal Handling", "wis"),
    ("arc", "Arcana", "int"),
    ("ath", "Athletics", "str"),
    ("dec", "Deception", "cha"),
    ("his", "History", "int"),
    ("ins", "Insight", "wis"),
    ("itm", "Intimidation", "cha"),
    ("inv", "Investigation", "int"),
    ("med", "Medicine", "wis"),
    ("nat", "Nature", "int"),
    ("prc", "Perception", "wis"),
    ("prf", "Performance", "cha"),
    ("per", "Persuasion", "cha"),
    ("rel", "Religion", "int"),
    ("slt", "Sleight of Hand", "dex"),
    ("ste", "Stealth", "dex"),
    ("sur", "Survival", "wis"),
]
LANGUAGE_LABELS = {
    "common": "Common",
    "dwarvish": "Dwarvish",
    "elvish": "Elvish",
}
ARMOR_PROF_LABELS = {
    "lgt": "Light Armor",
    "med": "Medium Armor",
    "hvy": "Heavy Armor",
    "shl": "Shields",
}
WEAPON_PROF_LABELS = {
    "sim": "Simple Weapons",
    "mar": "Martial Weapons",
}
PREPARED_LABELS = {
    0: "",
    1: "Prepared",
    2: "Always",
}
UNIT_LABELS = {
    "ft": "ft",
    "touch": "Touch",
    "self": "Self",
    "inst": "Instant",
    "minute": "Minute",
    "hour": "Hour",
}

POOL_RESOURCE_IDS: frozenset[str] = frozenset({
    "lay-on-hands",
    "healing-light",
})

SPENDABLE_RESOURCE_IDS: frozenset[str] = frozenset({
    "bardic-inspiration",
    "bardic-inspiration-d8",
    "rage",
    "channel-divinity",
    "divine-intervention",
    "wild-shape",
    "wild-companion",
    "second-wind",
    "action-surge",
    "indomitable",
    "superiority-dice",
    "combat-superiority",
    "ki",
    "ki-points",
    "focus-points",
    "stunning-strike",
    "wholeness-of-body",
    "quickened-healing",
    "divine-sense",
    "lay-on-hands",
    "sorcery-points",
    "font-of-magic",
    "mystic-arcanum",
    "healing-light",
    "tomb-of-levistus",
    "arcane-recovery",
    "lucky",
    "fey-touched",
    "breath-weapon",
    "relentless-endurance",
})


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "character"


def to_number(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return default


def to_int(value: Any, default: int = 0) -> int:
    return int(round(to_number(value, default)))


def _mapping(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a dict, else an empty dict.

    Exports are machine-written, but hand-edited copies exist: a field that is
    present yet null must be tolerated exactly like a missing one instead of
    crashing derivation.
    """
    return value if isinstance(value, dict) else {}


def is_spendable_resource(entry: dict[str, Any]) -> bool:
    if to_int(entry.get("uses_max")) < 1:
        return False
    identifier = (entry.get("identifier") or "").strip().lower()
    if identifier and identifier in SPENDABLE_RESOURCE_IDS:
        return True
    return slugify(entry.get("name", "")) in SPENDABLE_RESOURCE_IDS


def is_pool_resource(entry: dict[str, Any]) -> bool:
    identifier = (entry.get("identifier") or "").strip().lower()
    if identifier and identifier in POOL_RESOURCE_IDS:
        return True
    return slugify(entry.get("name", "")) in POOL_RESOURCE_IDS


_FORMULA_FUNCS = {
    "max": max,
    "min": min,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
}


def _eval_formula_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_formula_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_formula_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError("unsupported unary op")
    if isinstance(node, ast.BinOp):
        left = _eval_formula_node(node.left)
        right = _eval_formula_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right else 0.0
        if isinstance(node.op, ast.FloorDiv):
            return left // right if right else 0.0
        if isinstance(node.op, ast.Mod):
            return left % right if right else 0.0
        raise ValueError("unsupported binop")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FORMULA_FUNCS or node.keywords:
            raise ValueError("disallowed call")
        return float(_FORMULA_FUNCS[node.func.id](*(_eval_formula_node(a) for a in node.args)))
    raise ValueError(f"unsupported node {type(node).__name__}")


def resolve_formula(raw: Any, ctx: dict[str, int]) -> int:
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        return int(round(raw))
    if not isinstance(raw, str):
        return 0

    def substitute_ref(match: re.Match[str]) -> str:
        """Replace one ``@reference`` with its value from ``ctx``.

        Foundry writes glued arithmetic like ``@abilities.int.mod-1`` without
        spaces, and the reference pattern would otherwise swallow the ``-1``
        as part of the name. When the full reference is unknown, retry without
        a trailing ``-<number>`` before giving up, so the suffix stays in the
        expression as subtraction.
        """
        ref = match.group(0)
        if ref in ctx:
            return str(ctx[ref])
        split = re.fullmatch(r"(.+)-(\d+)", ref)
        if split:
            base = split.group(1)
            if base in ctx:
                return f"{ctx[base]}-{split.group(2)}"
        return "0"

    expr = raw.strip()
    if not expr:
        return 0
    try:
        if expr.lstrip("-").isdigit():
            return int(expr)
        expr = re.sub(r"@[\w.\-]+", substitute_ref, expr)
        return int(round(_eval_formula_node(ast.parse(expr, mode="eval"))))
    except Exception:
        return 0


def build_formula_context(actor: dict[str, Any]) -> dict[str, int]:
    system = actor.get("system", {}) or {}
    abilities = system.get("abilities", {}) or {}
    classes = list(find_items(actor, "class"))
    total_level = sum(to_int(c.get("system", {}).get("levels")) for c in classes)
    ctx: dict[str, int] = {
        "@prof": proficiency_bonus(total_level),
        "@details.level": total_level,
        "@classes.level": total_level,
    }
    for code in ABILITY_ORDER:
        score = to_int((abilities.get(code) or {}).get("value"))
        mod = ability_mod(score)
        ctx[f"@abilities.{code}.mod"] = mod
        ctx[f"@abilities.{code}.value"] = score
        ctx[f"@abilities.{code}.save"] = mod
    for cls in classes:
        cls_sys = cls.get("system", {}) or {}
        cls_id = (cls_sys.get("identifier") or slugify(cls.get("name", ""))).lower()
        levels = to_int(cls_sys.get("levels"))
        ctx[f"@classes.{cls_id}.levels"] = levels
        adv = cls_sys.get("advancement") or {}
        adv_iter = adv.values() if isinstance(adv, dict) else adv
        for record in adv_iter:
            if not isinstance(record, dict) or record.get("type") != "ScaleValue":
                continue
            cfg = record.get("configuration", {}) or {}
            scale_id = (cfg.get("identifier") or "").strip().lower()
            if not scale_id:
                continue
            best: int | None = None
            for lvl_key, entry in (cfg.get("scale") or {}).items():
                try:
                    lvl = int(lvl_key)
                except (TypeError, ValueError):
                    continue
                if lvl > levels:
                    continue
                value = entry.get("value") if isinstance(entry, dict) else entry
                resolved = to_int(value)
                if resolved:
                    best = resolved
            if best is not None:
                ctx[f"@scale.{cls_id}.{scale_id}"] = best
    return ctx


def ability_mod(score: int) -> int:
    return math.floor((score - 10) / 2)


def proficiency_bonus(level: int) -> int:
    return 2 + max(level - 1, 0) // 4


def signed(value: int) -> str:
    return f"{value:+d}"


def pluralize(label: str, amount: str | int | float | None) -> str:
    if amount in (None, "", 1, 1.0, "1"):
        return label
    return f"{label}s"


def pretty_code(code: str) -> str:
    return code.replace("-", " ").replace("_", " ").title()


def normalize_foundry_refs(text: str) -> str:
    if not text:
        return ""

    def macro_replacer(match: re.Match[str]) -> str:
        inner = match.group(1)
        label = match.group(2)
        if label:
            return label
        parts = [part.strip() for part in inner.split("|")]
        return next((part for part in reversed(parts) if part), "")

    text = re.sub(r"@\w+\[([^\]]+)\](?:\{([^}]+)\})?", macro_replacer, text)
    text = re.sub(r"&Reference\[(?:[^=\]]+=)?([^\]]+)\]", lambda m: pretty_code(m.group(1)), text)
    text = re.sub(r"\[\[/damage\s+([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[/r\s+([^\]]+)\]\]", r"\1", text)
    return text


def html_to_text(value: str) -> str:
    if not value:
        return ""
    value = normalize_foundry_refs(value)
    value = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</\s*(p|div|li|h\d|tr)\s*>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = re.sub(r"\r", "", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(value)).strip()


def first_sentence(value: str) -> str:
    text = compact_text(value)
    if not text:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", text)
    return match.group(1) if match else text


def excerpt_text(value: str, max_chars: int = 360) -> str:
    text = compact_text(value)
    if len(text) <= max_chars:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    excerpt = ""
    for sentence in sentences:
        candidate = f"{excerpt} {sentence}".strip()
        if len(candidate) <= max_chars:
            excerpt = candidate
        else:
            break

    if excerpt and len(excerpt) >= max_chars * 0.6:
        return excerpt

    truncated = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{truncated}..."


def format_units(value: Any, units: str | None) -> str:
    if units == "touch":
        return "Touch"
    if units == "self":
        return "Self"
    if units == "inst":
        return "Instant"
    if value in (None, "", 0, "0"):
        return UNIT_LABELS.get(units or "", pretty_code(units or ""))
    label = UNIT_LABELS.get(units or "", units or "")
    if label in {"ft"}:
        return f"{value} {label}".strip()
    return f"{value} {pluralize(label, value)}".strip()


def format_activation(data: dict[str, Any]) -> str:
    value = data.get("value")
    action_type = data.get("type") or ""
    if action_type == "bonus":
        return "Bonus Action"
    if action_type == "reaction":
        return "Reaction"
    if action_type == "action":
        return f"{value or 1} Action"
    if action_type == "special":
        return "Special"
    if action_type:
        return pretty_code(action_type)
    return "Passive"


def format_range(data: dict[str, Any]) -> str:
    units = data.get("units")
    value = data.get("value")
    long_range = data.get("long")
    if value in (None, "", 0, "0") and units == "self":
        return "Self"
    if value in (None, "", 0, "0") and units == "touch":
        return "Touch"
    if value in (None, "", 0, "0") and units == "ft":
        return ""
    if value not in (None, "", 0, "0") and long_range not in (None, "", 0, "0"):
        return f"{value}/{long_range} {UNIT_LABELS.get(units or '', units or '')}".strip()
    return format_units(value, units)


def format_duration(data: dict[str, Any]) -> str:
    return format_units(data.get("value"), data.get("units"))


def format_recovery(uses: dict[str, Any]) -> str:
    recovery = uses.get("recovery") or []
    labels: list[str] = []
    for entry in recovery:
        if entry.get("type") == "recoverAll" and entry.get("period") == "lr":
            labels.append("Long Rest")
        elif entry.get("type") == "recoverAll" and entry.get("period") == "sr":
            labels.append("Short Rest")
        elif entry.get("type") == "formula" and entry.get("period") == "sr":
            labels.append(f"+{entry.get('formula', '?')} on Short Rest")
        elif entry.get("period"):
            labels.append(pretty_code(entry["period"]))
    return ", ".join(labels)


def format_spell_properties(properties: list[str]) -> str:
    labels = [SPELL_PROPERTY_LABELS[property_code] for property_code in SPELL_PROPERTY_LABELS if property_code in properties]
    return ", ".join(labels)


def format_currency(currency: dict[str, Any]) -> str:
    parts = []
    for coin in ["pp", "gp", "ep", "sp", "cp"]:
        amount = currency.get(coin, 0)
        if amount:
            parts.append(f"{amount} {coin.upper()}")
    return ", ".join(parts) or "None"


def coin_counts(currency: dict[str, Any]) -> dict[str, int]:
    return {coin: to_int(currency.get(coin, 0)) for coin in ["cp", "sp", "ep", "gp", "pp"]}


def total_weight(items: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in items:
        quantity = to_number(item.get("system", {}).get("quantity"), 1)
        weight = to_number(item.get("system", {}).get("weight", {}).get("value"))
        total += quantity * weight
    return total


def find_items(actor: dict[str, Any], item_type: str) -> list[dict[str, Any]]:
    return [item for item in actor.get("items") or [] if item.get("type") == item_type]


def human_school(code: str) -> str:
    return SCHOOL_LABELS.get(code, pretty_code(code))


def source_label(source: dict[str, Any]) -> str:
    if not isinstance(source, dict):
        return ""
    book = source.get("book") or source.get("custom") or ""
    page = source.get("page")
    if book and page:
        return f"{book} p. {page}"
    return str(book or "")


def ordered_activities(system_data: dict[str, Any]) -> list[dict[str, Any]]:
    activities = system_data.get("activities", {})
    return sorted(
        activities.values(),
        key=lambda activity: (
            to_int(activity.get("sort")),
            activity.get("name") or "",
            activity.get("_id") or "",
        ),
    )


def first_activity(system_data: dict[str, Any]) -> dict[str, Any] | None:
    activities = ordered_activities(system_data)
    return activities[0] if activities else None


def activity_names(system_data: dict[str, Any]) -> list[str]:
    return [activity.get("name") for activity in ordered_activities(system_data) if activity.get("name")]


def class_levels(actor: dict[str, Any]) -> list[dict[str, Any]]:
    classes = []
    for item in find_items(actor, "class"):
        levels = to_int(item.get("system", {}).get("levels"))
        classes.append({"name": item.get("name", "Class"), "levels": levels, "item": item})
    return classes


def primary_class_slug(actor: dict[str, Any]) -> str | None:
    classes = class_levels(actor)
    if not classes:
        return None
    primary = max(classes, key=lambda entry: entry["levels"])
    identifier = primary["item"].get("system", {}).get("identifier")
    name = (identifier or primary["name"]).strip().lower()
    return name or None


def class_theme_color(actor: dict[str, Any]) -> str | None:
    slug = primary_class_slug(actor)
    return CLASS_THEME_COLORS.get(slug) if slug else None


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def mix_hex(color: str, mix_with: str, ratio: float) -> str:
    cr, cg, cb = _hex_to_rgb(color)
    mr, mg, mb = _hex_to_rgb(mix_with)
    return _rgb_to_hex(
        round(cr * (1 - ratio) + mr * ratio),
        round(cg * (1 - ratio) + mg * ratio),
        round(cb * (1 - ratio) + mb * ratio),
    )


def hex_to_rgba(color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha})"


_RGBA_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")


def flatten_color(color: str, under: str) -> str:
    """Opaque hex for a #hex or rgba() color painted over the opaque ``under`` color."""
    match = _RGBA_RE.fullmatch(color.strip())
    if not match:
        return color
    r, g, b = (round(float(v)) for v in match.groups()[:3])
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return mix_hex(_rgb_to_hex(r, g, b), under, 1 - alpha)


def relative_luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 2 contrast ratio between two opaque #hex colors."""
    hi, lo = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def is_weapon_proficient(actor: dict[str, Any], weapon: dict[str, Any]) -> bool:
    weapon_type = weapon.get("system", {}).get("type", {}).get("value", "")
    profs = actor.get("system", {}).get("traits", {}).get("weaponProf", {}).get("value", [])
    if weapon.get("name") == "Unarmed Strike":
        return True
    if weapon_type.startswith("simple") and "sim" in profs:
        return True
    if weapon_type.startswith("martial") and "mar" in profs:
        return True
    return False


def attack_ability_code(weapon: dict[str, Any]) -> str:
    activities = weapon.get("system", {}).get("activities", {})
    for activity in activities.values():
        attack = activity.get("attack")
        if attack and attack.get("ability"):
            return attack["ability"]
    weapon_type = weapon.get("system", {}).get("type", {}).get("value", "")
    if weapon_type.endswith("R"):
        return "dex"
    return "str"


def format_damage(weapon: dict[str, Any], ability_bonus: int) -> str:
    damage = weapon.get("system", {}).get("damage", {}).get("base", {})
    pieces: list[str] = []
    if damage.get("custom", {}).get("enabled") and damage.get("custom", {}).get("formula"):
        pieces.append(str(damage["custom"]["formula"]))
    elif damage.get("number") and damage.get("denomination"):
        pieces.append(f"{damage['number']}d{damage['denomination']}")

    bonus = damage.get("bonus", "")
    add_ability = weapon.get("type") == "weapon"
    if bonus == "@mod":
        add_ability = True
    elif bonus not in (None, ""):
        pieces.append(str(bonus))
        add_ability = False

    if add_ability and ability_bonus:
        pieces.append(str(ability_bonus))

    damage_str = " + ".join(pieces) if pieces else str(max(1, ability_bonus))
    damage_types = damage.get("types") or []
    if damage_types:
        damage_str += f" {'/'.join(pretty_code(damage_type) for damage_type in damage_types)}"
    return damage_str


def derive_armor_class(actor: dict[str, Any], dex_mod: int) -> int:
    equipped = [
        item for item in actor.get("items") or []
        if item.get("type") == "equipment" and _mapping(item.get("system")).get("equipped")
    ]
    armor_items = [item for item in equipped if _mapping(_mapping(item.get("system")).get("type")).get("value") != "shield"]
    shield_bonus = sum(
        to_int(_mapping(_mapping(item.get("system")).get("armor")).get("value"))
        for item in equipped
        if item.get("system", {}).get("type", {}).get("value") == "shield"
    )
    base = 10 + dex_mod
    if armor_items:
        best = 0
        for item in armor_items:
            armor = item.get("system", {}).get("armor", {})
            armor_base = to_int(armor.get("value"))
            dex_cap = armor.get("dex")
            dex_bonus = dex_mod if dex_cap in (None, "") else min(dex_mod, to_int(dex_cap))
            best = max(best, armor_base + dex_bonus)
        base = best
    return base + shield_bonus


def spell_slot_defaults(spells_data: dict[str, Any]) -> list[dict[str, Any]]:
    slots = []
    for level in range(1, 10):
        key = f"spell{level}"
        value = _mapping(spells_data.get(key)).get("value", 0)
        if value:
            slots.append({"label": f"Level {level}", "value": int(value)})
    pact = _mapping(spells_data.get("pact")).get("value", 0)
    if pact:
        slots.append({"label": "Pact", "value": int(pact)})
    return slots


def aggregate_spells(actor: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for spell in find_items(actor, "spell"):
        grouped[(to_int(spell.get("system", {}).get("level")), spell.get("name", "").casefold())].append(spell)

    active_spells: list[dict[str, Any]] = []
    spell_library: dict[int, list[str]] = defaultdict(list)

    for (level, _), group in sorted(grouped.items(), key=lambda pair: (pair[0][0], pair[1][0].get("name", ""))):
        first = group[0]
        sys_data = first.get("system", {})
        badges: list[str] = []
        descriptions = [compact_text(spell.get("system", {}).get("description", {}).get("value", "")) for spell in group]
        description = next((text for text in descriptions if text), "")
        properties = sorted({property_code for spell in group for property_code in spell.get("system", {}).get("properties", [])})

        prepared_values = {to_int(spell.get("system", {}).get("prepared")) for spell in group}
        methods = {spell.get("system", {}).get("method") for spell in group}
        uses_list = [spell.get("system", {}).get("uses", {}) for spell in group]
        card_uses = next((uses for uses in uses_list if uses.get("max")), {})
        recovery_badges = []
        for uses in uses_list:
            if uses.get("max"):
                label = f"{uses.get('max')}"
                recovery = format_recovery(uses)
                recovery_badges.append(f"{label} use{'s' if str(uses.get('max')) != '1' else ''}" + (f" / {recovery}" if recovery else ""))

        if level == 0:
            badges.append("Cantrip")
        if 2 in prepared_values:
            badges.append("Always")
        if 1 in prepared_values and level > 0:
            badges.append("Prepared")
        if "innate" in methods:
            badges.append("Innate")
        badges.extend(recovery_badges)

        is_active = level == 0 or "innate" in methods or 1 in prepared_values or 2 in prepared_values
        entry = {
            "name": first.get("name", "Spell"),
            "level": level,
            "school": human_school(sys_data.get("school", "")),
            "activation": format_activation(sys_data.get("activation", {})),
            "range": format_range(sys_data.get("range", {})),
            "duration": format_duration(sys_data.get("duration", {})),
            "badges": badges,
            "description": description,
            "summary": excerpt_text(description, 420),
            "components": format_spell_properties(properties),
            "uses": card_uses,
            "source_label": source_label(sys_data.get("source", {})),
        }

        if is_active:
            active_spells.append(entry)
        else:
            spell_library[level].append(first.get("name", "Spell"))

    return active_spells, spell_library


_SCALING_VARIANT_RE = re.compile(r"^(.+?)-d(\d+)$")


def _collapse_scaling_variants(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return entries
    base_of: list[str | None] = []
    tier_of: list[int] = []
    for entry in entries:
        ident = (entry.get("identifier") or "").lower()
        if not ident:
            base_of.append(None)
            tier_of.append(0)
            continue
        match = _SCALING_VARIANT_RE.match(ident)
        if match:
            base_of.append(match.group(1))
            tier_of.append(int(match.group(2)))
        else:
            base_of.append(ident)
            tier_of.append(0)
    max_tier: dict[str, int] = {}
    for base, tier in zip(base_of, tier_of, strict=True):
        if base is None:
            continue
        if tier > max_tier.get(base, 0):
            max_tier[base] = tier
    if not any(v > 0 for v in max_tier.values()):
        return entries
    winner_idx: dict[str, int] = {}
    for i, base in enumerate(base_of):
        if base is None or max_tier.get(base, 0) == 0:
            continue
        if tier_of[i] == max_tier[base]:
            winner_idx.setdefault(base, i)
    kept: list[dict[str, Any]] = []
    placed: set[int] = set()
    for i, entry in enumerate(entries):
        base = base_of[i]
        if base is None or max_tier.get(base, 0) == 0:
            kept.append(entry)
            continue
        win = winner_idx[base]
        if win in placed:
            continue
        if i == win or tier_of[i] == 0:
            kept.append(entries[win])
            placed.add(win)
    return kept


def collect_features(
    actor: dict[str, Any],
    formula_ctx: dict[str, int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    ctx = formula_ctx if formula_ctx is not None else build_formula_context(actor)
    groups: dict[str, list[dict[str, Any]]] = {
        "Ancestry": [],
        "Class Features": [],
        "Feats": [],
    }
    for item in find_items(actor, "feat"):
        sys_data = item.get("system", {})
        feature_type = sys_data.get("type", {}).get("value")
        full_description = compact_text(sys_data.get("description", {}).get("value", ""))
        description = first_sentence(sys_data.get("description", {}).get("value", ""))
        activity = first_activity(sys_data) or {}
        uses_data = sys_data.get("uses", {}) or {}
        entry = {
            "name": item.get("name", "Feature"),
            "identifier": sys_data.get("identifier", ""),
            "uses": uses_data,
            "uses_max": resolve_formula(uses_data.get("max"), ctx),
            "requirements": sys_data.get("requirements", ""),
            "description": description,
            "full_description": full_description,
            "summary": excerpt_text(full_description, 420),
            "activation": format_activation(activity.get("activation", {})) if activity else "",
            "range": format_range(activity.get("range", {})) if activity else "",
            "duration": format_duration(activity.get("duration", {})) if activity else "",
            "activity_names": activity_names(sys_data),
            "source_label": source_label(sys_data.get("source", {})),
        }
        if feature_type == "race":
            groups["Ancestry"].append(entry)
        elif feature_type == "class":
            groups["Class Features"].append(entry)
        else:
            groups["Feats"].append(entry)
    for key, items in groups.items():
        groups[key] = _collapse_scaling_variants(items)
    return groups


def sheet_context(actor: dict[str, Any]) -> dict[str, Any]:
    system = _mapping(actor.get("system"))
    details = _mapping(system.get("details"))
    abilities = _mapping(system.get("abilities"))
    skills = _mapping(system.get("skills"))
    tools = _mapping(system.get("tools"))
    traits = _mapping(system.get("traits"))
    class_info = class_levels(actor)
    total_level = sum(entry["levels"] for entry in class_info)
    prof_bonus = proficiency_bonus(total_level)
    spell_ability_code = _mapping(system.get("attributes")).get("spellcasting") or (_mapping(_mapping(class_info[0]["item"]).get("system")).get("spellcasting", {}).get("ability") if class_info else "")

    race_item = next(iter(find_items(actor, "race")), None)
    background_item = next(iter(find_items(actor, "background")), None)
    subclass_item = next(iter(find_items(actor, "subclass")), None)
    class_item = class_info[0]["item"] if class_info else None
    all_items = actor.get("items") or []
    armor_items = [item for item in all_items if item.get("type") in {"equipment", "weapon", "loot", "tool", "container"}]
    equipped_shields = [
        item for item in all_items
        if item.get("type") == "equipment"
        and _mapping(item.get("system")).get("equipped")
        and _mapping(_mapping(item.get("system")).get("type")).get("value") == "shield"
    ]
    ability_rows = []
    saving_throw_rows = []

    for code in ABILITY_ORDER:
        ability = _mapping(abilities.get(code))
        score = to_int(ability.get("value"))
        mod = ability_mod(score)
        save_prof = to_number(ability.get("proficient"))
        save_bonus = mod + int(prof_bonus * save_prof) + to_int(_mapping(ability.get("bonuses")).get("save"))
        ability_rows.append({
            "code": code.upper(),
            "label": ABILITY_LABELS[code],
            "score": score,
            "mod": signed(mod),
        })
        saving_throw_rows.append({
            "label": ABILITY_LABELS[code],
            "bonus": signed(save_bonus),
            "proficient": save_prof > 0,
        })

    skill_rows = []
    passive_scores = {}
    for code, label, default_ability in SKILLS:
        skill = _mapping(skills.get(code))
        ability_code = skill.get("ability") or default_ability
        mod = ability_mod(to_int(_mapping(abilities.get(ability_code)).get("value")))
        multiplier = to_number(skill.get("value"))
        bonus = mod + int(prof_bonus * multiplier) + to_int(_mapping(skill.get("bonuses")).get("check"))
        passive = 10 + bonus + to_int(_mapping(skill.get("bonuses")).get("passive"))
        skill_rows.append({
            "label": label,
            "ability": ability_code.upper(),
            "bonus": signed(bonus),
            "proficient": multiplier > 0,
        })
        if code in {"prc", "ins", "inv"}:
            passive_scores[code] = passive

    tool_rows = []
    for label, tool in sorted(tools.items()):
        ability_code = tool.get("ability") or "int"
        mod = ability_mod(to_int(abilities.get(ability_code, {}).get("value")))
        multiplier = to_number(tool.get("value"))
        bonus = mod + int(prof_bonus * multiplier) + to_int(tool.get("bonuses", {}).get("check"))
        tool_rows.append({
            "label": pretty_code(label),
            "ability": ability_code.upper(),
            "bonus": signed(bonus),
        })

    attacks = []
    for item in actor.get("items") or []:
        if item.get("type") != "weapon" or not _mapping(item.get("system")).get("equipped"):
            continue
        ability_code = attack_ability_code(item)
        ability_bonus = ability_mod(to_int(_mapping(abilities.get(ability_code)).get("value")))
        attack_bonus = ability_bonus + (prof_bonus if is_weapon_proficient(actor, item) else 0)
        attacks.append({
            "name": item.get("name", "Weapon"),
            "attack_bonus": signed(attack_bonus),
            "damage": format_damage(item, ability_bonus),
            "range": format_range(item.get("system", {}).get("range", {})),
            "notes": first_sentence(item.get("system", {}).get("description", {}).get("value", "")),
        })

    active_spells, spell_library = aggregate_spells(actor)
    feature_groups = collect_features(actor)
    slot_defaults = spell_slot_defaults(_mapping(system.get("spells")))

    spell_ability_mod = ability_mod(to_int(_mapping(abilities.get(spell_ability_code)).get("value"))) if spell_ability_code else 0
    spell_dc = 8 + prof_bonus + spell_ability_mod if spell_ability_code else None
    spell_attack = prof_bonus + spell_ability_mod if spell_ability_code else None
    dex_mod = ability_mod(to_int(_mapping(abilities.get("dex")).get("value")))
    init_bonus = dex_mod + to_int(_mapping(_mapping(system.get("attributes")).get("init")).get("bonus"))
    race_movement = race_item.get("system", {}).get("movement", {}).get("walk") if race_item else None
    senses = race_item.get("system", {}).get("senses", {}).get("ranges", {}) if race_item else {}
    hp = _mapping(_mapping(system.get("attributes")).get("hp"))
    armor_class = derive_armor_class(actor, dex_mod)
    shield_bonus = sum(to_int(item.get("system", {}).get("armor", {}).get("value")) for item in equipped_shields)
    spellcast_label = ABILITY_LABELS.get(spell_ability_code, spell_ability_code.upper()) if spell_ability_code else "None"
    size_code = traits.get("size", "")
    size_label = {"tiny": "Tiny", "sm": "Small", "med": "Medium", "lg": "Large", "huge": "Huge", "grg": "Gargantuan"}.get(size_code, pretty_code(size_code) if size_code else "")
    hit_die_size = class_item.get("system", {}).get("hd", {}).get("denomination") if class_item else None
    hit_dice_spent = to_int(class_item.get("system", {}).get("hd", {}).get("spent")) if class_item else 0

    inventory = []
    containers = {item.get("_id"): item.get("name") for item in actor.get("items") or [] if item.get("type") == "container"}
    for item in armor_items:
        system_data = item.get("system", {})
        quantity = to_int(system_data.get("quantity"), 1)
        entry = {
            "name": item.get("name", "Item"),
            "quantity": quantity,
            "container": containers.get(system_data.get("container"), ""),
            "weight": to_number(system_data.get("weight", {}).get("value")) * quantity,
        }
        inventory.append(entry)

    proficiencies = []
    proficiencies.extend(ARMOR_PROF_LABELS.get(code, pretty_code(code)) for code in traits.get("armorProf", {}).get("value", []))
    proficiencies.extend(WEAPON_PROF_LABELS.get(code, pretty_code(code)) for code in traits.get("weaponProf", {}).get("value", []))

    spell_reference_count = len(active_spells)
    feature_reference_count = sum(len(entries) for entries in feature_groups.values())
    has_any_slots = any(to_int(slot.get("value")) > 0 for slot in slot_defaults)
    is_spellcaster = bool(spell_ability_code) or bool(active_spells) or has_any_slots

    return {
        "name": actor.get("name", "Character"),
        "species": re.sub(r"\s*;\s*", " / ", race_item.get("name", "")) if race_item else "",
        "background": background_item.get("name", "") if background_item else "",
        "class_line": ", ".join(f"{entry['name']} {entry['levels']}" for entry in class_info),
        "class_slug": primary_class_slug(actor),
        "class_color": class_theme_color(actor),
        "subclass": subclass_item.get("name", "") if subclass_item else "",
        "level": total_level,
        "xp": details.get("xp", {}).get("value"),
        "ability_rows": ability_rows,
        "saving_throw_rows": saving_throw_rows,
        "skill_rows": skill_rows,
        "tool_rows": tool_rows,
        "attacks": attacks,
        "active_spells": active_spells,
        "spell_library": {level: sorted(names) for level, names in spell_library.items()},
        "feature_groups": feature_groups,
        "slot_defaults": slot_defaults,
        "currency": format_currency(_mapping(system.get("currency"))),
        "inventory": inventory,
        "inventory_weight": total_weight(armor_items),
        "languages": [LANGUAGE_LABELS.get(code, pretty_code(code)) for code in _mapping(traits.get("languages")).get("value") or []],
        "proficiencies": proficiencies,
        "passive_perception": passive_scores.get("prc", 10),
        "passive_insight": passive_scores.get("ins", 10),
        "passive_investigation": passive_scores.get("inv", 10),
        "hp_value": hp.get("value", 0),
        "temp_hp": hp.get("temp") or 0,
        "hp_max": hp.get("max") or hp.get("value") or 0,
        "ac": armor_class,
        "shield_bonus": shield_bonus,
        "initiative": init_bonus,
        "speed": race_movement or 30,
        "darkvision": senses.get("darkvision"),
        "size": size_label,
        "prof_bonus": prof_bonus,
        "spell_ability": spellcast_label,
        "spell_mod": spell_ability_mod,
        "spell_dc": spell_dc,
        "spell_attack": spell_attack,
        "is_spellcaster": is_spellcaster,
        "inspiration": bool(_mapping(system.get("attributes")).get("inspiration")),
        "hit_dice_spent": hit_dice_spent,
        "hit_dice_total": total_level,
        "hit_die_size": hit_die_size,
        "currency_counts": coin_counts(_mapping(system.get("currency"))),
        "reference_counts": {
            "spells": spell_reference_count,
            "features": feature_reference_count,
        },
        "top_references": {
            "class": {"name": class_item.get("name", "") if class_item else "", "source": source_label(class_item.get("system", {}).get("source", {})) if class_item else ""},
            "subclass": {"name": subclass_item.get("name", "") if subclass_item else "", "source": source_label(subclass_item.get("system", {}).get("source", {})) if subclass_item else ""},
            "background": {"name": background_item.get("name", "") if background_item else "", "source": source_label(background_item.get("system", {}).get("source", {})) if background_item else ""},
            "species": {"name": race_item.get("name", "") if race_item else "", "source": source_label(race_item.get("system", {}).get("source", {})) if race_item else ""},
        },
        "notes": {
            "traits": compact_text(details.get("trait", "")),
            "ideal": compact_text(details.get("ideal", "")),
            "bond": compact_text(details.get("bond", "")),
            "flaw": compact_text(details.get("flaw", "")),
            "appearance": compact_text(details.get("appearance", "")),
            "biography": compact_text(details.get("biography", {}).get("value", "")),
        },
    }


def esc(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def render_reference_anchor(label: str, source: str = "") -> str:
    label_html = esc(label)
    if source:
        return f'{label_html} <span class="source-note">{esc(source)}</span>'
    return label_html


def render_tracker_pips(count: int, key_prefix: str, class_name: str = "diamond") -> str:
    if count <= 0:
        return '<span class="no-pips">—</span>'
    return "".join(
        f'''
        <label class="slot-pip {esc(class_name)}">
          <input type="checkbox" data-persist="{esc(f"{key_prefix}-{index}")}">
          <span></span>
        </label>
        '''
        for index in range(1, count + 1)
    )


def render_v2_field(
    value: Any,
    key: str,
    class_name: str,
    multiline: bool = False,
    numeric: bool = False,
    print_value: Any | None = None,
) -> str:
    print_attr = "" if print_value is None else f' data-print-value="{esc(print_value)}"'
    if multiline:
        return f'<textarea class="v2-field {esc(class_name)}" data-persist="{esc(key)}"{print_attr}>{esc(value)}</textarea>'
    if numeric:
        return (
            f'<input class="v2-field {esc(class_name)}" type="text" inputmode="numeric" '
            f'pattern="[0-9+\\-]*" autocomplete="off" spellcheck="false" '
            f'data-persist="{esc(key)}" value="{esc(value)}"{print_attr}>'
        )
    return f'<input class="v2-field {esc(class_name)}" type="text" data-persist="{esc(key)}" value="{esc(value)}"{print_attr}>'


def render_v2_list(
    entries: list[dict[str, Any]],
    max_items: int = 10,
    sheet_id: str = "",
    group_key: str = "",
) -> str:
    if not entries:
        return ""
    rows = []
    for idx, entry in enumerate(entries[:max_items]):
        suffix_html = ""
        if is_spendable_resource(entry):
            count = to_int(entry.get("uses_max"))
            key_prefix = f"{sheet_id}-feature-{group_key}-{idx}"
            if is_pool_resource(entry):
                pool_key = esc(f"{key_prefix}-pool")
                suffix_html = (
                    f' <span class="feature-pool">'
                    f'<input class="feature-pool-input" type="number" min="0" max="{count}" '
                    f'inputmode="numeric" data-persist="{pool_key}" value="{count}">'
                    f'<span class="feature-pool-sep">/</span>'
                    f'<span class="feature-pool-max">{count}</span>'
                    f'</span>'
                )
            else:
                suffix_html = f' <span class="feature-uses">{render_tracker_pips(count, key_prefix)}</span>'
        rows.append(
            f'<li>{render_reference_anchor(entry["name"])}{suffix_html}</li>'
        )
    return "<ul>" + "".join(rows) + "</ul>"


def render_attack_damage_cell(damage: str) -> str:
    text = str(damage or "").strip()
    match = re.match(r"^(.*\d)\s+([A-Za-z][A-Za-z/ ]*)$", text)
    if not match:
        return esc(text)
    roll, damage_type = match.groups()
    return (
        f'<span class="dnd-layout-damage-roll">{esc(roll)}</span> '
        f'<span class="dnd-layout-damage-type">{esc(damage_type.strip())}</span>'
    )


def render_v2_attack_rows(attacks: list[dict[str, Any]], max_rows: int = 5) -> str:
    rows = []
    for attack in attacks[:max_rows]:
        rows.append(
            f'''
            <tr>
              <td>{esc(attack["name"])}</td>
              <td>{esc(attack["attack_bonus"])}</td>
              <td>{render_attack_damage_cell(attack["damage"])}</td>
              <td>{esc(attack["notes"])}</td>
            </tr>
            '''
        )
    while len(rows) < max_rows:
        rows.append('<tr><td>&nbsp;</td><td></td><td></td><td></td></tr>')
    return "".join(rows)


def render_v2_spell_rows(spells: list[dict[str, Any]]) -> str:
    row_cap = 27 if len(spells) >= 12 else max(len(spells) + 3, 10)
    rows = []
    for spell in spells[:row_cap]:
        props = spell.get("components", "")
        note_badges = [badge for badge in spell["badges"] if badge in {"Always", "Prepared", "Innate"}]
        note_text = ", ".join(note_badges) or spell["school"]
        flag_specs = [
            ("Concentration", "Concentration" in props),
            ("Ritual", "Ritual" in props),
            ("Material", "M" in props),
        ]
        flag_html = "".join(
            f'<span class="spell-flag {"on" if active else "off"}">{esc(label)}</span>'
            for label, active in flag_specs
        )
        rows.append(
            f'''
            <tr>
              <td>{esc("C" if spell["level"] == 0 else spell["level"])}</td>
              <td>{render_reference_anchor(spell["name"])}</td>
              <td>{esc(spell["activation"])}</td>
              <td>{esc(spell["range"])}</td>
              <td class="spell-flags-cell">{flag_html}</td>
              <td>{esc(note_text)}</td>
            </tr>
            '''
        )
    while len(rows) < row_cap:
        rows.append('<tr><td>&nbsp;</td><td></td><td></td><td></td><td class="spell-flags-cell"></td><td></td></tr>')
    return "".join(rows)


BASE_LAYOUTS = ("ledger", "gazette", "grimoire")
MODE_CHOICES = ("light", "dark", "mono")
PAPER_PROFILES = {
    "a4": "size: A4; margin: 9mm;",
    "letter": "size: Letter; margin: 0.35in;",
}

CLASS_THEME_COLORS = {
    "artificer": "#6E7B85",
    "barbarian": "#992E2E",
    "bard":      "#AB6DAC",
    "cleric":    "#91A1B2",
    "druid":     "#7A853B",
    "fighter":   "#7F513E",
    "monk":      "#51A5C5",
    "paladin":   "#B59E54",
    "ranger":    "#507F62",
    "rogue":     "#555752",
    "sorcerer":  "#E7623E",
    "warlock":   "#7B469B",
    "wizard":    "#2A50A1",
}


HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# Minimum WCAG contrast ratios enforced on every theme, in every color mode.
# Accent text (titles, ability modifiers, labels) must meet the text threshold;
# the secondary accent only draws corner brackets and focus rings, so it needs
# the non-text (graphics) threshold.
TEXT_CONTRAST = 4.5
GRAPHIC_CONTRAST = 3.0

_LIGHT_SHADOW = "0 18px 42px rgba(20, 22, 26, 0.08)"
_DARK_SHADOW = "0 24px 52px rgba(0, 0, 0, 0.55)"


def _surfaces(
    paper: str,
    panel: str,
    panel_soft: str,
    ink: str,
    ink_soft: str,
    accent: str,
    accent_strong: str,
    *,
    dark: bool,
) -> dict[str, str]:
    """One color mode of a theme: page surfaces, text inks, and the two accents."""
    return {
        "paper": paper,
        "panel": panel,
        "panel_soft": panel_soft,
        "ink": ink,
        "ink_soft": ink_soft,
        "rule": hex_to_rgba(ink, 0.72 if dark else 0.84),
        "rule_soft": hex_to_rgba(ink, 0.16 if dark else 0.14),
        "shadow": _DARK_SHADOW if dark else _LIGHT_SHADOW,
        "accent": accent,
        "accent_strong": accent_strong,
    }


def _light(*colors: str) -> dict[str, str]:
    return _surfaces(*colors, dark=False)


def _dark(*colors: str) -> dict[str, str]:
    return _surfaces(*colors, dark=True)


def _class_theme_entry(accent: str, base: str = "ledger") -> dict:
    """Class (or custom #hex) theme: neutral surfaces tinted toward one accent."""
    return {
        "base": base,
        "decoration": "class",
        "light": _light(
            mix_hex(accent, "#f2f0eb", 0.89),  # paper
            mix_hex(accent, "#ffffff", 0.965),  # panel
            mix_hex(accent, "#f6f4f0", 0.93),  # panel_soft
            mix_hex(accent, "#15171b", 0.88),  # ink
            mix_hex(accent, "#4a4f57", 0.72),  # ink_soft
            accent,
            accent,
        ),
        "dark": _dark(
            mix_hex(accent, "#0c0d10", 0.88),
            mix_hex(accent, "#15171c", 0.90),
            mix_hex(accent, "#1d2027", 0.88),
            mix_hex(accent, "#efebe3", 0.90),
            mix_hex(accent, "#a9a59c", 0.80),
            accent,
            accent,
        ),
    }


# Layout themes keep the exact surfaces their base stylesheet was designed with.
_LAYOUT_DARK = {
    "paper": "#0f1114",
    "panel": "rgba(24, 27, 34, 0.94)",
    "panel_soft": "rgba(34, 38, 48, 0.62)",
    "ink": "#ecdcbd",
    "ink_soft": "#a8a091",
    "rule": "rgba(236, 220, 189, 0.72)",
    "rule_soft": "rgba(236, 220, 189, 0.16)",
    "shadow": "0 24px 52px rgba(0, 0, 0, 0.55)",
}

THEMES: dict[str, dict] = {
    # Layout themes — typography + ornaments come from the base layout
    "ledger": {
        "base": "ledger", "decoration": None,
        "light": {
            "paper": "#ffffff",
            "panel": "rgba(255, 255, 255, 0.94)",
            "panel_soft": "rgba(244, 241, 236, 0.78)",
            "ink": "#14161a",
            "ink_soft": "#4a4f57",
            "rule": "rgba(26, 28, 34, 0.84)",
            "rule_soft": "rgba(20, 22, 26, 0.14)",
            "shadow": "0 18px 42px rgba(20, 22, 26, 0.08)",
            "accent": "#7a1518",
            "accent_strong": "#7a1518",
        },
        "dark": {**_LAYOUT_DARK, "accent": "#f39c7e", "accent_strong": "#f39c7e"},
    },
    "gazette": {
        "base": "gazette", "decoration": None,
        "light": {
            "paper": "#f6f1e4",
            "panel": "rgba(255, 250, 236, 0.84)",
            "panel_soft": "rgba(255, 250, 236, 0.64)",
            "ink": "#18150f",
            "ink_soft": "#5a5447",
            "rule": "rgba(24, 21, 15, 0.72)",
            "rule_soft": "rgba(24, 21, 15, 0.18)",
            "shadow": "0 18px 42px rgba(38, 28, 14, 0.08)",
            "accent": "#18150f",
            "accent_strong": "#8a6c2d",
        },
        "dark": {
            "paper": "#15120f",
            "panel": "rgba(30, 26, 21, 0.94)",
            "panel_soft": "rgba(55, 47, 39, 0.64)",
            "ink": "#f3e8cf",
            "ink_soft": "#b8ab95",
            "rule": "rgba(243, 232, 207, 0.72)",
            "rule_soft": "rgba(243, 232, 207, 0.18)",
            "shadow": "0 24px 52px rgba(0, 0, 0, 0.58)",
            "accent": "#e7d3a3",
            "accent_strong": "#c7a558",
        },
    },
    "grimoire": {
        "base": "grimoire", "decoration": None,
        "light": {
            "paper": "#f5ead2",
            "panel": "rgba(255, 250, 236, 0.76)",
            "panel_soft": "rgba(233, 216, 174, 0.36)",
            "ink": "#2a1d0f",
            "ink_soft": "#6e5536",
            "rule": "rgba(42, 29, 15, 0.72)",
            "rule_soft": "rgba(42, 29, 15, 0.18)",
            "shadow": "0 20px 48px rgba(42, 29, 15, 0.14)",
            "accent": "#6d1a1a",
            "accent_strong": "#9e7a2b",
        },
        "dark": {
            "paper": "#121117",
            "panel": "rgba(24, 22, 19, 0.95)",
            "panel_soft": "rgba(46, 39, 31, 0.66)",
            "ink": "#f0e0bb",
            "ink_soft": "#aa9777",
            "rule": "rgba(240, 224, 187, 0.72)",
            "rule_soft": "rgba(240, 224, 187, 0.16)",
            "shadow": "0 26px 58px rgba(0, 0, 0, 0.58)",
            "accent": "#e9c26a",
            "accent_strong": "#c79a3a",
        },
    },
    # Curated palettes — each scheme's own light and dark variants.
    # Argument order: paper, panel, panel_soft, ink, ink_soft, accent, accent_strong.
    "dracula": {
        "base": "ledger", "decoration": "dracula",
        # Alucard (the official light variant) / Dracula
        "light": _light("#f1ecd9", "#fffbeb", "#f6f1de", "#1f1f1f", "#5f5a45", "#a3144d", "#644ac9"),
        "dark":  _dark("#191a21", "#282a36", "#303241", "#f8f8f2", "#b6bcd8", "#ff79c6", "#bd93f9"),
    },
    "catppuccin": {
        "base": "ledger", "decoration": "catppuccin",
        # Latte / Mocha
        "light": _light("#dce0e8", "#eff1f5", "#e6e9ef", "#4c4f69", "#5c5f77", "#8839ef", "#ea76cb"),
        "dark":  _dark("#11111b", "#1e1e2e", "#262637", "#cdd6f4", "#a6adc8", "#cba6f7", "#f5c2e7"),
    },
    "nord": {
        "base": "ledger", "decoration": "nord",
        # Snow Storm / Polar Night, Frost accents
        "light": _light("#d8dee9", "#eceff4", "#e5e9f0", "#2e3440", "#4c566a", "#5e81ac", "#81a1c1"),
        "dark":  _dark("#242933", "#2e3440", "#3b4252", "#eceff4", "#c0c8d6", "#88c0d0", "#81a1c1"),
    },
    "hearth": {
        "base": "ledger", "decoration": "hearth",
        "light": _light("#efe6da", "#fcf8f2", "#f5eee4", "#2b211c", "#6b5a4e", "#cc785c", "#915641"),
        "dark":  _dark("#17120f", "#221c18", "#2c2420", "#f1e6d8", "#bba893", "#e8a487", "#d4836a"),
    },
    "solarized": {
        "base": "ledger", "decoration": "solarized",
        "light": _light("#eee8d5", "#fdf6e3", "#f5efdc", "#073642", "#586e75", "#268bd2", "#2aa198"),
        "dark":  _dark("#00212b", "#002b36", "#073642", "#eee8d5", "#93a1a1", "#268bd2", "#2aa198"),
    },
    "everforest": {
        "base": "ledger", "decoration": "everforest",
        "light": _light("#efebd4", "#fdf6e3", "#f4f0d9", "#4a555b", "#5c6a72", "#8da101", "#35a77c"),
        "dark":  _dark("#1e2326", "#2d353b", "#343f44", "#d3c6aa", "#9da9a0", "#a7c080", "#83c092"),
    },
    "gruvbox": {
        "base": "ledger", "decoration": "gruvbox",
        "light": _light("#f2e5bc", "#f9f5d7", "#f5edcb", "#3c3836", "#665c54", "#af3a03", "#b57614"),
        "dark":  _dark("#1d2021", "#282828", "#32302f", "#ebdbb2", "#bdae93", "#fabd2f", "#fe8019"),
    },
    "tokyo-night": {
        "base": "ledger", "decoration": "tokyo-night",
        # Tokyo Night Day / Night
        "light": _light("#d0d5e3", "#e9eaee", "#e1e2e7", "#343b58", "#4f5672", "#2e7de9", "#9854f1"),
        "dark":  _dark("#16161e", "#1a1b26", "#222436", "#c0caf5", "#a9b1d6", "#7aa2f7", "#bb9af7"),
    },
    "one-dark": {
        "base": "ledger", "decoration": "one-dark",
        # One Light / One Dark
        "light": _light("#e5e5e6", "#fafafa", "#f0f0f1", "#383a42", "#5c5f68", "#4078f2", "#a626a4"),
        "dark":  _dark("#1e2227", "#282c34", "#2f343e", "#d7dae0", "#9da5b4", "#61afef", "#c678dd"),
    },
    "rose-pine": {
        "base": "ledger", "decoration": "rose-pine",
        # Dawn / Main
        "light": _light("#f2e9e1", "#fffaf3", "#faf4ed", "#575279", "#6e6a86", "#907aa9", "#d7827e"),
        "dark":  _dark("#191724", "#1f1d2e", "#26233a", "#e0def4", "#908caa", "#c4a7e7", "#ebbcba"),
    },
    "kanagawa": {
        "base": "ledger", "decoration": "kanagawa",
        # Lotus / Wave
        "light": _light("#e7e0bd", "#f7f3dc", "#efe9cc", "#545464", "#6f6f7f", "#4d699b", "#624c83"),
        "dark":  _dark("#16161d", "#1f1f28", "#2a2a37", "#dcd7ba", "#a6a69c", "#7e9cd8", "#957fb8"),
    },
    "ayu": {
        "base": "ledger", "decoration": "ayu",
        # Light / Mirage
        "light": _light("#f0f1f2", "#fcfcfc", "#f5f6f7", "#41464b", "#5c6166", "#fa8d3e", "#f07171"),
        "dark":  _dark("#1a1f29", "#242936", "#2b3140", "#cccac2", "#9a9a95", "#ffcc66", "#ffa659"),
    },
    "material": {
        "base": "ledger", "decoration": "material",
        # Lighter / Ocean
        "light": _light("#e7ecef", "#fafafa", "#f2f4f5", "#263238", "#546e7a", "#6182b8", "#39adb5"),
        "dark":  _dark("#1e272c", "#263238", "#2e3c43", "#eeffff", "#b0bec5", "#82aaff", "#89ddff"),
    },
    # Class themes — ledger baseline + surfaces tinted toward the class color
    **{name: _class_theme_entry(accent) for name, accent in CLASS_THEME_COLORS.items()},
}

# Retired names from when each light/dark variant was its own theme. They still
# resolve (so existing commands keep working) and pick the matching color mode
# when no explicit --mode is given.
THEME_ALIASES: dict[str, tuple[str, str]] = {
    "catppuccin-latte": ("catppuccin", "light"),
    "rose-pine-dawn":   ("rose-pine", "light"),
    "everforest-light": ("everforest", "light"),
    "gruvbox-light":    ("gruvbox", "light"),
    "ayu-light":        ("ayu", "light"),
    "ayu-mirage":       ("ayu", "dark"),
}


def resolve_theme_entry(theme: str | None) -> tuple[str, dict] | None:
    """Resolve theme name (class, curated, layout, alias, or hex) → (label, entry). Returns None if no theme.

    An alias resolves to its target theme's entry plus a ``default_mode`` hint.
    """
    if not theme:
        return None
    if theme in THEMES:
        return theme, dict(THEMES[theme])
    if theme in THEME_ALIASES:
        target, mode = THEME_ALIASES[theme]
        return theme, {**THEMES[target], "default_mode": mode}
    if HEX_COLOR_RE.match(theme):
        normalized = theme if theme.startswith("#") else f"#{theme}"
        return normalized, _class_theme_entry(normalized)
    raise ValueError(f"Unknown theme {theme!r}")


def _mode_backgrounds(palette: dict[str, str], dark: bool) -> tuple[str, str, str]:
    """Opaque paper, page, and panel colors as actually painted (rgba layers flattened)."""
    paper = flatten_color(palette["paper"], "#000000" if dark else "#ffffff")
    panel = flatten_color(palette["panel"], paper)
    panel_soft = flatten_color(palette["panel_soft"], panel)
    return paper, panel, panel_soft


def ensure_contrast(color: str, backgrounds: tuple[str, ...], target: float) -> str:
    """Darken (light surfaces) or lighten (dark surfaces) ``color`` until it meets ``target`` on every background.

    Only HLS lightness moves, so hue and saturation survive. Colors that already
    pass are returned unchanged, so a scheme's own hexes stay wherever they are
    readable.
    """
    if min(contrast_ratio(color, bg) for bg in backgrounds) >= target:
        return color
    direction = -1 if relative_luminance(backgrounds[0]) > 0.18 else 1
    r, g, b = (channel / 255 for channel in _hex_to_rgb(color))
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    for step in range(1, 101):
        new_lightness = min(1.0, max(0.0, lightness + direction * step / 100))
        r, g, b = colorsys.hls_to_rgb(hue, new_lightness, saturation)
        candidate = _rgb_to_hex(round(r * 255), round(g * 255), round(b * 255))
        if min(contrast_ratio(candidate, bg) for bg in backgrounds) >= target:
            return candidate
    return "#000000" if direction < 0 else "#ffffff"


def _on_accent(accent: str, paper: str) -> str:
    """Text color for accent-filled buttons and tokens: the paper color if legible, else black or white."""
    if contrast_ratio(paper, accent) >= TEXT_CONTRAST:
        return paper
    return max(("#ffffff", "#111111"), key=lambda ink: contrast_ratio(ink, accent))


def resolve_mode_palette(palette: dict[str, str], dark: bool) -> dict[str, str]:
    """Apply the contrast guardrails to one color mode of a theme."""
    backgrounds = _mode_backgrounds(palette, dark)
    out = dict(palette)
    out["ink_soft"] = ensure_contrast(palette["ink_soft"], backgrounds, TEXT_CONTRAST)
    out["accent"] = ensure_contrast(palette["accent"], backgrounds, TEXT_CONTRAST)
    out["accent_strong"] = ensure_contrast(palette["accent_strong"], backgrounds, GRAPHIC_CONTRAST)
    out["on_accent"] = _on_accent(out["accent"], backgrounds[0])
    return out


def build_theme_palette(entry: dict) -> dict[str, dict[str, str]]:
    """Render-ready palette for a theme entry: both color modes, contrast-checked."""
    return {
        "light": resolve_mode_palette(entry["light"], dark=False),
        "dark": resolve_mode_palette(entry["dark"], dark=True),
    }


# Per-palette flavor on top of the colors: font stacks, the letter-spacing of
# uppercase display text, how strongly the accents glow in the page margins,
# and whether panels get a faint diagonal accent sheen. Glows and sheens are
# mixed from the live --accent variables, so they follow the color mode.
PALETTE_DECORATIONS: dict[str, dict[str, Any]] = {
    "dracula": {
        "fonts": ('"Literata", "Source Serif 4", "Georgia", "Times New Roman", serif',
                  '"Space Grotesk", "Avenir Next Condensed", "Helvetica Neue", sans-serif',
                  '"IBM Plex Sans", "Segoe UI", sans-serif'),
        "tracking": "0.16em", "glow": 18, "sheen": True,
    },
    "catppuccin": {
        "fonts": ('"Fraunces", "Source Serif 4", "Georgia", serif',
                  '"Sora", "Avenir Next", "Helvetica Neue", sans-serif',
                  '"IBM Plex Sans", "Segoe UI", sans-serif'),
        "tracking": "0.14em", "glow": 12, "sheen": True,
    },
    "nord": {
        "fonts": ('"Source Serif 4", "Iowan Old Style", "Georgia", serif',
                  '"IBM Plex Sans Condensed", "IBM Plex Sans", "Helvetica Neue", sans-serif',
                  '"IBM Plex Sans", "Segoe UI", sans-serif'),
        "tracking": "0.18em", "glow": 16, "sheen": False,
    },
    "hearth": {
        "fonts": ('"Tiempos Text", "Source Serif 4", "Georgia", serif',
                  '"Styrene B", "Inter", "Helvetica Neue", sans-serif',
                  '"Styrene B", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.14em", "glow": 16, "sheen": False,
    },
    "solarized": {
        "fonts": ('"Source Serif 4", "Source Serif Pro", "Georgia", serif',
                  '"IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace',
                  '"IBM Plex Sans", "Segoe UI", sans-serif'),
        "tracking": "0.14em", "glow": 12, "sheen": False,
    },
    "everforest": {
        "fonts": ('"Bitter", "Source Serif 4", "Georgia", serif',
                  '"Quicksand", "Comfortaa", "Avenir Next", sans-serif',
                  '"Mulish", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.12em", "glow": 12, "sheen": False,
    },
    "gruvbox": {
        "fonts": ('"Zilla Slab", "Roboto Slab", "Rockwell", "Georgia", serif',
                  '"Zilla Slab", "Roboto Slab", "Rockwell", serif',
                  '"Work Sans", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.08em", "glow": 14, "sheen": True,
    },
    "tokyo-night": {
        "fonts": ('"Spectral", "Source Serif 4", "Georgia", serif',
                  '"Chakra Petch", "Space Grotesk", "Helvetica Neue", sans-serif',
                  '"Inter", "Segoe UI", sans-serif'),
        "tracking": "0.16em", "glow": 14, "sheen": True,
    },
    "one-dark": {
        "fonts": ('"Newsreader", "Source Serif 4", "Georgia", serif',
                  '"Manrope", "Inter", "Helvetica Neue", sans-serif',
                  '"Inter", "Segoe UI", sans-serif'),
        "tracking": "0.14em", "glow": 10, "sheen": False,
    },
    "rose-pine": {
        "fonts": ('"Cormorant Garamond", "EB Garamond", "Georgia", serif',
                  '"Marcellus", "Cormorant Garamond", "Georgia", serif',
                  '"Jost", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.18em", "glow": 14, "sheen": True,
    },
    "kanagawa": {
        "fonts": ('"Shippori Mincho", "Zen Old Mincho", "Source Serif 4", "Georgia", serif',
                  '"Zen Old Mincho", "Shippori Mincho", "Georgia", serif',
                  '"Zen Kaku Gothic New", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.18em", "glow": 16, "sheen": True,
    },
    "ayu": {
        "fonts": ('"Source Serif 4", "Source Serif Pro", "Georgia", serif',
                  '"Rubik", "Manrope", "Inter", "Helvetica Neue", sans-serif',
                  '"Rubik", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.14em", "glow": 14, "sheen": False,
    },
    "material": {
        "fonts": ('"Roboto Slab", "Source Serif 4", "Georgia", serif',
                  '"Roboto Condensed", "Roboto", "Helvetica Neue", sans-serif',
                  '"Roboto", "Inter", "Helvetica Neue", sans-serif'),
        "tracking": "0.12em", "glow": 12, "sheen": False,
    },
    # Class themes keep the ledger typography; they only get the accent glow.
    "class": {"fonts": None, "tracking": None, "glow": 12, "sheen": False},
}

_DISPLAY_SELECTORS = (
    ".dnd-layout-page-title",
    ".dnd-layout-section-title",
    ".dnd-layout-label",
    ".dnd-layout-token",
    ".dnd-layout-summary-card .value",
    ".dnd-layout-mini-stat .value",
    "button",
)


def _sheet_palette_css(palette: str | None) -> str:
    decor = PALETTE_DECORATIONS.get(palette or "")
    if decor is None:
        return ""
    body = f"body.dnd-layout-palette-{palette}"
    glow = decor["glow"]
    font_vars = ""
    if decor["fonts"]:
        serif, display, sans = decor["fonts"]
        font_vars = f"--serif: {serif};\n          --display: {display};\n          --sans: {sans};\n          "
    css = f"""
        {body} {{
          {font_vars}background:
            radial-gradient(circle at 14% 8%, color-mix(in srgb, var(--accent) {glow}%, transparent), transparent 38%),
            radial-gradient(circle at 86% 92%, color-mix(in srgb, var(--accent-strong) {round(glow * 0.7)}%, transparent), transparent 40%),
            var(--paper);
        }}
        """
    if decor["tracking"]:
        selectors = ",\n        ".join(f"{body} {sel}" for sel in _DISPLAY_SELECTORS)
        css += f"""
        {selectors} {{
          font-family: var(--display);
          letter-spacing: {decor["tracking"]};
          text-transform: uppercase;
        }}
        """
    if decor["sheen"]:
        css += f"""
        {body} .dnd-layout-panel::before {{
          content: "";
          position: absolute;
          inset: 0;
          background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 7%, transparent), transparent 42%);
          pointer-events: none;
        }}
        @media print {{
          {body}[data-theme="light"] .dnd-layout-panel::before {{ display: none; }}
        }}
        """
    return css


# Open-licensed fonts (see fonts/licenses/) are inlined into each sheet so it
# looks the same on every machine, offline and in PDF export. Rebuild the set
# with tools/fetch_fonts.py.
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
_FONT_ROLES = ("serif", "display", "sans", "mono")
_FONT_STACK_RE = re.compile(r"--(serif|display|sans|mono):\s*([^;]+);")


@lru_cache(maxsize=1)
def _font_manifest() -> dict[str, Any]:
    try:
        return json.loads((FONTS_DIR / "fonts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def theme_font_families(style: str, palette: str | None) -> list[str]:
    """Bundled families a theme renders with: the first bundled family of each font role's stack."""
    stacks: dict[str, str] = {}
    for role, stack in _FONT_STACK_RE.findall(_sheet_theme_css(style)):
        stacks.setdefault(role, stack)  # the first declaration is the layout's :root
    decor = PALETTE_DECORATIONS.get(palette or "")
    if decor and decor["fonts"]:
        stacks.update(zip(("serif", "display", "sans"), decor["fonts"], strict=True))
    manifest = _font_manifest()
    families: list[str] = []
    for role in _FONT_ROLES:
        for family in (part.strip().strip("\"'") for part in stacks.get(role, "").split(",")):
            if family in manifest:
                if family not in families:
                    families.append(family)
                break
    return families


@cache
def _font_face_css(family: str) -> str:
    rules = []
    for face in _font_manifest()[family]["faces"]:
        data = base64.b64encode((FONTS_DIR / face["file"]).read_bytes()).decode("ascii")
        rules.append(
            f'@font-face {{ font-family: "{family}"; font-style: {face["style"]}; '
            f'font-weight: {face["weight"]}; font-display: block; '
            f'src: url(data:font/woff2;base64,{data}) format("woff2"); }}'
        )
    return "\n".join(rules)


def embedded_font_css(style: str, palette: str | None) -> str:
    """@font-face rules (base64 WOFF2) for the fonts this theme uses; empty if fonts are not bundled."""
    return "\n".join(_font_face_css(family) for family in theme_font_families(style, palette))


def _sheet_theme_css(style: str) -> str:
    if style == "gazette":
        return r"""
        :root {
          --paper: #f6f1e4;
          --panel: rgba(255, 250, 236, 0.84);
          --panel-soft: rgba(255, 250, 236, 0.64);
          --ink: #18150f;
          --ink-soft: #5a5447;
          --accent: #18150f;
          --accent-strong: #8a6c2d;
          --rule: rgba(24, 21, 15, 0.72);
          --rule-soft: rgba(24, 21, 15, 0.18);
          --shadow: 0 18px 42px rgba(38, 28, 14, 0.08);
          --serif: "EB Garamond", "Libre Caslon Text", "Old Standard TT", "Times New Roman", serif;
          --display: "Playfair Display", "EB Garamond", "Times New Roman", serif;
          --sans: "Source Sans 3", "Helvetica Neue", Arial, sans-serif;
          --mono: "IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace;
          --radius: 10px;
        }
        body {
          background: var(--paper);
          background-image:
            radial-gradient(circle at 18% 12%, rgba(138, 108, 45, 0.06), transparent 36%),
            radial-gradient(circle at 84% 88%, rgba(24, 21, 15, 0.04), transparent 42%);
        }
        .dnd-layout-page::before,
        .dnd-layout-panel::before {
          content: "";
          position: absolute;
          inset: 6px;
          border: 1px solid var(--rule-soft);
          pointer-events: none;
          border-radius: calc(var(--radius) - 4px);
        }
        .dnd-layout-section-title,
        .dnd-layout-page-title,
        .dnd-layout-label,
        .dnd-layout-token,
        .dnd-layout-summary-card .value,
        .dnd-layout-mini-stat .value,
        button {
          font-family: var(--display);
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        .dnd-layout-shell::before,
        .dnd-layout-shell::after {
          content: "";
          position: absolute;
          left: 32px;
          right: 32px;
          height: 1px;
          background: linear-gradient(90deg, transparent, rgba(24, 21, 15, 0.18), transparent);
          pointer-events: none;
        }
        .dnd-layout-shell::before { top: 16px; }
        .dnd-layout-shell::after { bottom: 16px; }
        """
    if style == "grimoire":
        return r"""
        :root {
          --paper: #f5ead2;
          --panel: rgba(255, 250, 236, 0.76);
          --panel-soft: rgba(233, 216, 174, 0.36);
          --ink: #2a1d0f;
          --ink-soft: #6e5536;
          --accent: #6d1a1a;
          --accent-strong: #9e7a2b;
          --rule: rgba(42, 29, 15, 0.72);
          --rule-soft: rgba(42, 29, 15, 0.18);
          --shadow: 0 20px 48px rgba(42, 29, 15, 0.14);
          --serif: "Cormorant Garamond", "EB Garamond", "Garamond", "Times New Roman", serif;
          --display: "Cinzel", "Trajan Pro", "Cormorant Garamond", serif;
          --sans: "Inter", "Helvetica Neue", Arial, sans-serif;
          --mono: "IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace;
          --radius: 16px;
        }
        body {
          background: var(--paper);
          background-image:
            radial-gradient(circle at 18% 12%, rgba(158, 122, 43, 0.15), transparent 42%),
            radial-gradient(circle at 85% 88%, rgba(109, 26, 26, 0.08), transparent 45%),
            radial-gradient(circle at 50% 50%, rgba(42, 29, 15, 0.035), transparent 60%);
        }
        .dnd-layout-page::after {
          content: "✦";
          position: absolute;
          top: 12px;
          right: 18px;
          color: var(--accent-strong);
          font-size: 14px;
          opacity: 0.72;
          pointer-events: none;
        }
        .dnd-layout-page-title,
        .dnd-layout-section-title,
        .dnd-layout-label,
        .dnd-layout-token,
        .dnd-layout-summary-card .value,
        .dnd-layout-mini-stat .value,
        button {
          font-family: var(--display);
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        .dnd-layout-shell::before,
        .dnd-layout-shell::after {
          content: "";
          position: absolute;
          left: 30px;
          right: 30px;
          height: 3px;
          background: linear-gradient(90deg, transparent, var(--accent-strong) 20%, var(--accent-strong) 80%, transparent);
          opacity: 0.58;
          pointer-events: none;
        }
        .dnd-layout-shell::before { top: 20px; }
        .dnd-layout-shell::after { bottom: 20px; }
        """
    return r"""
    :root {
      --paper: #ffffff;
      --panel: rgba(255, 255, 255, 0.94);
      --panel-soft: rgba(244, 241, 236, 0.78);
      --ink: #14161a;
      --ink-soft: #4a4f57;
      --accent: #7a1518;
      --accent-strong: #7a1518;
      --rule: rgba(26, 28, 34, 0.84);
      --rule-soft: rgba(20, 22, 26, 0.14);
      --shadow: 0 18px 42px rgba(20, 22, 26, 0.08);
      --serif: "Source Serif 4", "Source Serif Pro", "Georgia", "Times New Roman", serif;
      --display: "Source Serif 4", "Source Serif Pro", "Georgia", "Times New Roman", serif;
      --sans: "Inter", "Helvetica Neue", Arial, sans-serif;
      --mono: "IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace;
      --radius: 18px;
    }
    body {
      background:
        linear-gradient(180deg, rgba(122, 21, 24, 0.03), transparent 220px),
        var(--paper);
    }
    .dnd-layout-page-title,
    .dnd-layout-section-title,
    .dnd-layout-label,
    .dnd-layout-token,
    button {
      font-family: var(--sans);
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }
    """


def render_dnd_layout_template(data: dict[str, Any], sheet_id: str, style: str = "ledger", palette: str | None = None) -> str:
    def field(
        value: Any,
        key: str,
        class_name: str,
        multiline: bool = False,
        numeric: bool = False,
        print_value: Any | None = None,
    ) -> str:
        return render_v2_field(value, key, class_name, multiline=multiline, numeric=numeric, print_value=print_value)

    def blank_zero(value: Any) -> Any:
        return "" if value in (None, "", 0, 0.0, "0") else value

    emblem = emblems.emblem_svg(data.get("class_slug"), "dnd-layout-emblem")

    save_map = {row["label"]: row for row in data["saving_throw_rows"]}
    skills_by_ability: dict[str, list[dict[str, Any]]] = {}
    for row in data["skill_rows"]:
        skills_by_ability.setdefault(row["ability"].lower(), []).append(row)

    ability_cards = []
    for row in data["ability_rows"]:
        code = row["code"].lower()
        save_row = save_map.get(row["label"], {"bonus": "+0", "proficient": False})
        skill_items = "".join(
            f'''
            <li>
              <span class="ability-skill-mark">{"●" if skill["proficient"] else "○"}</span>
              <span class="ability-skill-name">{esc(skill["label"])}</span>
              <span class="ability-skill-bonus">{esc(skill["bonus"])}</span>
            </li>
            '''
            for skill in skills_by_ability.get(code, [])
        ) or '<li class="ability-empty"><span class="ability-skill-name">No keyed skills</span><span class="ability-skill-bonus">—</span></li>'
        ability_cards.append(
            f'''
            <article class="dnd-layout-ability-card">
              <div class="ability-heading">
                <span class="ability-name">{esc(row["label"])}</span>
              </div>
              <div class="ability-core">
                <div class="ability-mod">{esc(row["mod"])}</div>
                <div class="ability-score-wrap">
                  <span class="ability-score-label">Score</span>
                  <span class="ability-score">{esc(row["score"])}</span>
                </div>
              </div>
              <div class="ability-save">
                <span class="ability-skill-mark">{"●" if save_row["proficient"] else "○"}</span>
                <span class="ability-skill-name">Saving Throw</span>
                <strong>{esc(save_row["bonus"])}</strong>
              </div>
              <div class="ability-skill-group">
                <ul class="ability-skill-list">{skill_items}</ul>
              </div>
            </article>
            '''
        )

    spells_by_level = {level: 0 for level in range(1, 10)}
    for slot in data["slot_defaults"]:
        match = re.search(r"(\d+)", slot["label"])
        if match:
            spells_by_level[int(match.group(1))] = to_int(slot["value"])

    slot_rows = []
    for level in range(1, 10):
        count = spells_by_level[level]
        slot_rows.append(
            f'''
            <div class="dnd-layout-slot-row">
              <span class="slot-level">Level {level}</span>
              <span class="slot-pips">{render_tracker_pips(count, f"{sheet_id}-dnd-layout-slot-l{level}")}</span>
            </div>
            '''
        )

    class_entries = data["feature_groups"].get("Class Features", [])
    species_entries = data["feature_groups"].get("Ancestry", [])
    feat_entries = data["feature_groups"].get("Feats", [])
    class_features_html = render_v2_list(class_entries, 12, sheet_id, "class") or '<p class="muted">No class features exported.</p>'
    species_traits_html = render_v2_list(species_entries, 10, sheet_id, "species") or '<p class="muted">No ancestry traits exported.</p>'
    feats_html = render_v2_list(feat_entries, 10, sheet_id, "feats") or '<p class="muted">No feats exported.</p>'

    armor_labels = {"Light Armor", "Medium Armor", "Heavy Armor", "Shields"}
    weapon_profs = [prof for prof in data["proficiencies"] if prof not in armor_labels]
    armor_training = "".join(
        f'<span class="dnd-layout-token {"active" if label in data["proficiencies"] else ""}">{esc(label)}</span>'
        for label in ["Light Armor", "Medium Armor", "Heavy Armor", "Shields"]
    )
    passive_line = f'Passive Perception {data["passive_perception"]} · Passive Insight {data["passive_insight"]} · Passive Investigation {data["passive_investigation"]}'
    senses_line = f'Speed {data["speed"]} ft'
    if data["darkvision"]:
        senses_line += f' · Darkvision {data["darkvision"]} ft'

    backstory_text = "\n".join(
        section
        for section in [
            data["notes"]["traits"],
            data["notes"]["ideal"],
            data["notes"]["bond"],
            data["notes"]["flaw"],
            data["notes"]["biography"],
        ]
        if section
    )
    equipment_text = "\n".join(
        f"{item['quantity']}x {item['name']}" + (f" ({item['container']})" if item["container"] else "")
        for item in sorted(data["inventory"], key=lambda row: (row["container"], row["name"]))
    )
    coin_fields = "".join(
        f'<label class="dnd-layout-coin-card"><span class="dnd-layout-label">{esc(code.upper())}</span>{field(data["currency_counts"][code], f"dnd-layout-coin-{code}", "dnd-layout-input", numeric=True)}</label>'
        for code in ["cp", "sp", "ep", "gp", "pp"]
    )

    spellcasting_section_html = ""
    if data["is_spellcaster"]:
        spellcasting_section_html = f"""
      <section class="dnd-layout-page dnd-layout-spell-page">
        <div class="dnd-layout-page-head">
          <div>
            <div class="dnd-layout-page-title">Spellcasting</div>
          </div>
          {emblem}
        </div>

        <section class="dnd-layout-spell-summary">
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Spellcasting</span>
            <div class="value">{esc(data["spell_ability"])}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Modifier</span>
            <div class="value">{esc(signed(data["spell_mod"]))}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Save DC</span>
            <div class="value">{esc(data["spell_dc"] if data["spell_dc"] is not None else "—")}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Spell Attack</span>
            <div class="value">{esc(signed(data["spell_attack"]) if data["spell_attack"] is not None else "—")}</div>
          </article>
        </section>

        <section class="dnd-layout-panel">
          <div class="dnd-layout-section-title">Spell Slots</div>
          <div class="dnd-layout-slot-grid">{''.join(slot_rows)}</div>
        </section>

        <section class="dnd-layout-panel dnd-layout-spellbook-panel dnd-layout-breakable-panel">
          <div class="dnd-layout-section-title">Prepared Spells</div>
          <div class="dnd-layout-spell-legend">
            <span class="spell-flag on">Concentration</span>
            <span class="spell-flag on">Ritual</span>
            <span class="spell-flag on">Material</span>
          </div>
          <table class="dnd-layout-table dnd-layout-spell-table">
            <tbody>{render_v2_spell_rows(data["active_spells"])}</tbody>
          </table>
        </section>
      </section>
"""

    body = f"""
    <div class="dnd-layout-shell">
      <div class="dnd-layout-toolbar screen-only">
        <div class="dnd-layout-toolbar-copy">{esc(data["name"])} · dnd-layout/{esc(style)} · {data["reference_counts"]["spells"]} spell refs · {data["reference_counts"]["features"]} feature refs</div>
        <div class="dnd-layout-toolbar-actions">
          <button type="button" id="print-dnd-layout">Print / Save PDF</button>
          <button type="button" id="reset-dnd-layout" class="secondary">Reset Trackers</button>
        </div>
      </div>

      <section class="dnd-layout-page">
        <div class="dnd-layout-page-head">
          <span class="dnd-layout-attribution">@stravinci.pt</span>
          <div>
            <div class="dnd-layout-page-title">{esc(data["name"])}</div>
            <div class="dnd-layout-page-subtitle">{esc(data["class_line"])}{(' · ' + esc(data["subclass"])) if data["subclass"] else ''}</div>
          </div>
          {emblem}
        </div>

        <div class="dnd-layout-header-grid">
          <section class="dnd-layout-panel dnd-layout-identity-panel">
            <div class="dnd-layout-section-title">Identity</div>
            <div class="dnd-layout-identity-grid">
              <label class="dnd-layout-field-card full">
                <span class="dnd-layout-label">Character Name</span>
                {field(data["name"], "dnd-layout-name", "dnd-layout-input")}
              </label>
              <label class="dnd-layout-field-card">
                <span class="dnd-layout-label">Background</span>
                {field(data["background"], "dnd-layout-background", "dnd-layout-input")}
              </label>
              <label class="dnd-layout-field-card">
                <span class="dnd-layout-label">Class</span>
                {field(data["class_line"], "dnd-layout-class", "dnd-layout-input")}
              </label>
              <label class="dnd-layout-field-card">
                <span class="dnd-layout-label">Species</span>
                {field(data["species"], "dnd-layout-species", "dnd-layout-input")}
              </label>
              <label class="dnd-layout-field-card">
                <span class="dnd-layout-label">Subclass</span>
                {field(data["subclass"], "dnd-layout-subclass", "dnd-layout-input")}
              </label>
            </div>
          </section>

          <section class="dnd-layout-panel dnd-layout-pill-panel dnd-layout-level-panel">
            <div class="dnd-layout-section-title">Level</div>
            <div class="dnd-layout-pill-value">{field(data["level"], "dnd-layout-level", "dnd-layout-pill-input", numeric=True)}</div>
            <label class="dnd-layout-mini-field">
              <span class="dnd-layout-label">XP</span>
              {field(data["xp"] or "", "dnd-layout-xp", "dnd-layout-input small", numeric=True)}
            </label>
          </section>

          <section class="dnd-layout-panel dnd-layout-pill-panel dnd-layout-armor-panel">
            <div class="dnd-layout-section-title">Armor</div>
            <div class="dnd-layout-pill-number">{esc(data["ac"])}</div>
            <div class="dnd-layout-mini-stat dnd-layout-armor-shield">
              <span class="dnd-layout-armor-shield-label">Shield</span>
              <span class="value">{esc(f"+{data['shield_bonus']}" if data['shield_bonus'] else "—")}</span>
            </div>
          </section>

          <section class="dnd-layout-panel dnd-layout-health-panel">
            <div class="dnd-layout-section-title">Hit Points</div>
            <div class="dnd-layout-health-grid">
              <label class="dnd-layout-mini-field dnd-layout-health-field">
                <span class="dnd-layout-label">Current</span>
                {field(data["hp_value"], "dnd-layout-hp-current", "dnd-layout-input", numeric=True, print_value="")}
              </label>
              <label class="dnd-layout-mini-field dnd-layout-health-field">
                <span class="dnd-layout-label">Temp</span>
                {field(blank_zero(data["temp_hp"]), "dnd-layout-hp-temp", "dnd-layout-input", numeric=True)}
              </label>
              <label class="dnd-layout-mini-field dnd-layout-health-field">
                <span class="dnd-layout-label">Max</span>
                {field(data["hp_max"], "dnd-layout-hp-max", "dnd-layout-input", numeric=True)}
              </label>
            </div>
          </section>

          <section class="dnd-layout-panel dnd-layout-hitdice-panel">
            <div class="dnd-layout-section-title">Hit Dice / Death Saves</div>
            <div class="dnd-layout-hitdice-grid">
              <label class="dnd-layout-mini-field dnd-layout-hitdice-field">
                <span class="dnd-layout-label">Spent</span>
                {field(blank_zero(data["hit_dice_spent"]), "dnd-layout-hitdice-spent", "dnd-layout-input", numeric=True)}
              </label>
              <div class="dnd-layout-mini-stat dnd-layout-hitdice-total">
                <span>Total</span>
                <span class="value">{esc(f"{data['hit_dice_total']}d{str(data['hit_die_size']).lstrip('dD')}" if data['hit_die_size'] else data['hit_dice_total'])}</span>
              </div>
            </div>
            <div class="dnd-layout-death-grid">
              <div class="death-track">
                <span class="dnd-layout-label">Successes</span>
                <span class="slot-pips">{render_tracker_pips(3, f"{sheet_id}-dnd-layout-death-success")}</span>
              </div>
              <div class="death-track">
                <span class="dnd-layout-label">Failures</span>
                <span class="slot-pips">{render_tracker_pips(3, f"{sheet_id}-dnd-layout-death-failure")}</span>
              </div>
            </div>
          </section>
        </div>

        <section class="dnd-layout-summary-grid">
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Proficiency</span>
            <div class="value">{esc(signed(data["prof_bonus"]))}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Initiative</span>
            <div class="value">{esc(signed(data["initiative"]))}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Speed</span>
            <div class="value">{esc(data["speed"])} ft</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Size</span>
            <div class="value">{esc(data["size"])}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Passive Perception</span>
            <div class="value">{esc(data["passive_perception"])}</div>
          </article>
          <article class="dnd-layout-summary-card">
            <span class="dnd-layout-label">Inspiration</span>
            <label class="dnd-layout-inspiration">
              <input type="checkbox" data-persist="dnd-layout-inspiration" {"checked" if data["inspiration"] else ""}>
              <span></span>
            </label>
          </article>
        </section>

        <div class="dnd-layout-first-grid">
          <div class="dnd-layout-left-column">
            <section class="dnd-layout-panel">
              <div class="dnd-layout-section-title">Ability Scores</div>
              <div class="dnd-layout-abilities-grid">{''.join(ability_cards)}</div>
            </section>
          </div>

          <div class="dnd-layout-right-column">
            <section class="dnd-layout-panel">
              <div class="dnd-layout-section-title">Weapons & Damage Cantrips</div>
              <table class="dnd-layout-table dnd-layout-attack-table">
                <tbody>{render_v2_attack_rows(data["attacks"], max_rows=3)}</tbody>
              </table>
            </section>

            <section class="dnd-layout-panel dnd-layout-tall-panel">
              <div class="dnd-layout-section-title">Class Features</div>
              {class_features_html}
            </section>

            <div class="dnd-layout-feature-pair">
              <section class="dnd-layout-panel">
                <div class="dnd-layout-section-title">Species Traits</div>
                {species_traits_html}
              </section>
              <section class="dnd-layout-panel">
                <div class="dnd-layout-section-title">Feats</div>
                {feats_html}
              </section>
            </div>

            <section class="dnd-layout-panel dnd-layout-training-panel">
              <div class="dnd-layout-section-title">Training & Senses</div>
              <div class="dnd-layout-token-row">{armor_training}</div>
              <div class="dnd-layout-note-line"><strong>Weapons:</strong> {esc(", ".join(weapon_profs) or "None")}</div>
              <div class="dnd-layout-note-line"><strong>Tools:</strong> {esc(", ".join(row["label"] for row in data["tool_rows"]) or "None")}</div>
              <div class="dnd-layout-note-line"><strong>Languages:</strong> {esc(", ".join(data["languages"]) or "None")}</div>
              <div class="dnd-layout-note-line">{esc(passive_line)}</div>
              <div class="dnd-layout-note-line">{esc(senses_line)}</div>
              <div class="dnd-layout-inline-divider"></div>
              <div class="dnd-layout-subtitle">Coin Purse</div>
              <div class="dnd-layout-coin-grid dnd-layout-coin-grid-compact">{coin_fields}</div>
            </section>
          </div>
        </div>
      </section>

      <section class="dnd-layout-page dnd-layout-equipment-page">
        <div class="dnd-layout-page-head">
          <div>
            <div class="dnd-layout-page-title">Equipment & Notes</div>
            <div class="dnd-layout-page-subtitle">Gear, appearance, and character background.</div>
          </div>
          {emblem}
        </div>

        <div class="dnd-layout-third-grid">
          <section class="dnd-layout-panel">
            <div class="dnd-layout-section-title">Appearance</div>
            {field(data["notes"]["appearance"], "dnd-layout-appearance", "dnd-layout-input dnd-layout-area", multiline=True)}
          </section>

          <section class="dnd-layout-panel">
            <div class="dnd-layout-section-title">Backstory</div>
            {field(backstory_text, "dnd-layout-backstory", "dnd-layout-input dnd-layout-area journal-area", multiline=True)}
          </section>
        </div>

        <section class="dnd-layout-panel dnd-layout-breakable-panel">
          <div class="dnd-layout-section-title">Equipment</div>
          {field(equipment_text, "dnd-layout-equipment", "dnd-layout-input dnd-layout-area equipment-area", multiline=True)}
        </section>
      </section>

      {spellcasting_section_html}
    </div>
    """

    style_css = _sheet_theme_css(style) + _sheet_palette_css(palette) + r"""
    * { box-sizing: border-box; }
    html, body { margin: 0; color: var(--ink); font-family: var(--serif); font-variant-numeric: lining-nums; -webkit-font-smoothing: antialiased; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; text-underline-offset: 0.14em; }
    .dnd-layout-shell {
      max-width: 1120px;
      margin: 0 auto;
      padding: 20px 18px 44px;
      position: relative;
    }
    .dnd-layout-toolbar,
    .dnd-layout-reference-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 0 0 12px;
      padding: 12px 16px;
      border: 1px solid var(--rule-soft);
      border-radius: var(--radius);
      background: rgba(255, 255, 255, 0.56);
      backdrop-filter: blur(8px);
    }
    .dnd-layout-reference-line {
      justify-content: flex-start;
      flex-wrap: wrap;
      font-size: 0.8rem;
      color: var(--ink-soft);
    }
    .dnd-layout-toolbar-copy {
      font-family: var(--sans);
      font-size: 0.78rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-soft);
      min-width: 0;
    }
    .dnd-layout-toolbar-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
      flex: 0 1 auto;
      min-width: 260px;
    }
    button {
      appearance: none;
      border: 1px solid var(--accent);
      border-radius: 999px;
      padding: 10px 14px;
      background: var(--accent);
      color: var(--on-accent, var(--paper));
      font-size: 0.76rem;
      line-height: 1.1;
      min-height: 38px;
      white-space: nowrap;
      cursor: pointer;
    }
    button.secondary {
      background: transparent;
      color: var(--accent);
    }
    .dnd-layout-page {
      position: relative;
      margin-bottom: 14px;
      padding: 18px;
      border: 1px solid var(--rule-soft);
      border-radius: var(--radius);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.08), transparent 90px),
        var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
      break-inside: avoid;
    }
    .dnd-layout-page-head {
      position: relative;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 14px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--rule-soft);
    }
    .dnd-layout-page-head > div:first-of-type { padding: 2px 0 0 4px; }
    .dnd-layout-emblem {
      flex: none;
      width: 40px;
      height: 40px;
      margin: 10px 4px 0 0;
      color: var(--accent);
    }
    .dnd-layout-attribution {
      position: absolute;
      top: 2px;
      right: 3px;
      font-family: var(--sans);
      font-size: 0.52rem;
      color: var(--ink-soft);
      opacity: 0.45;
      letter-spacing: 0.04em;
      pointer-events: none;
    }
    .dnd-layout-page-title {
      font-size: 1.65rem;
      line-height: 1;
      color: var(--accent);
    }
    .dnd-layout-page-subtitle {
      margin-top: 6px;
      font-size: 0.98rem;
      color: var(--ink-soft);
      font-style: italic;
    }
    .dnd-layout-header-grid {
      display: grid;
      grid-template-columns: repeat(10, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .dnd-layout-panel {
      position: relative;
      padding: 14px;
      border: 1px solid var(--rule-soft);
      border-radius: var(--radius);
      background: var(--panel-soft);
      overflow: hidden;
      break-inside: avoid;
    }
    .dnd-layout-section-title {
      margin: 0 0 10px;
      font-size: 0.74rem;
      color: var(--ink-soft);
    }
    .dnd-layout-header-grid .dnd-layout-section-title {
      padding-top: 2px;
      padding-bottom: 2px;
    }
    .dnd-layout-identity-panel { grid-column: span 4; }
    .dnd-layout-pill-panel { grid-column: span 1; text-align: center; display: flex; flex-direction: column; justify-content: flex-start; gap: 10px; }
    .dnd-layout-health-panel { grid-column: span 2; }
    .dnd-layout-hitdice-panel { grid-column: span 2; }
    .dnd-layout-identity-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .dnd-layout-field-card.full { grid-column: 1 / -1; }
    .dnd-layout-field-card,
    .dnd-layout-mini-field,
    .dnd-layout-coin-card {
      display: flex;
      flex-direction: column;
      gap: 5px;
    }
    .dnd-layout-label {
      font-size: 0.68rem;
      color: var(--ink-soft);
    }
    .dnd-layout-page .v2-field {
      width: 100%;
      border: 0;
      border-bottom: 1px solid var(--rule-soft);
      background: transparent;
      padding: 2px 0 4px;
      color: var(--ink);
      font: 600 1rem/1.2 var(--serif);
      font-variant-numeric: lining-nums;
      outline: none;
      border-radius: 0;
    }
    .dnd-layout-page .v2-field.small {
      font-size: 0.92rem;
      text-align: center;
    }
    .dnd-layout-page .v2-field:focus {
      border-bottom-color: var(--accent);
    }
    textarea.v2-field.dnd-layout-area {
      min-height: 112px;
      resize: vertical;
      overflow: hidden;
      line-height: 1.42;
      font-weight: 500;
    }
    textarea.v2-field.dnd-layout-area.small-area { min-height: 56px; }
    textarea.v2-field.dnd-layout-area.journal-area { min-height: 180px; }
    textarea.v2-field.dnd-layout-area.equipment-area { min-height: 260px; }
    .dnd-layout-pill-value {
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 82px;
      border: 1px solid var(--rule-soft);
      border-radius: 999px;
      background: rgba(255,255,255,0.34);
      margin-bottom: 10px;
    }
    .dnd-layout-pill-input {
      max-width: 74px;
      text-align: center;
      border-bottom: 0 !important;
      font-size: 1.9rem !important;
      font-family: var(--display) !important;
    }
    .dnd-layout-pill-number {
      font-family: var(--display);
      font-size: 2rem;
      color: var(--accent);
      line-height: 1;
      margin: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 1 1 auto;
    }
    .dnd-layout-level-panel,
    .dnd-layout-armor-panel {
      gap: 8px;
    }
    .dnd-layout-armor-shield.dnd-layout-mini-stat {
      margin-top: auto;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 2px;
      text-align: center;
    }
    .dnd-layout-armor-shield-label { line-height: 1; }
    .dnd-layout-mini-stat {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--rule-soft);
      font-size: 0.82rem;
      color: var(--ink-soft);
    }
    .dnd-layout-mini-stat .value {
      font-family: var(--display);
      font-size: 0.98rem;
      color: var(--accent);
    }
    .dnd-layout-health-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }
    .dnd-layout-hitdice-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }
    .dnd-layout-death-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .death-track {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 8px;
      border-top: 1px solid var(--rule-soft);
    }
    .dnd-layout-summary-grid,
    .dnd-layout-spell-summary {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .dnd-layout-spell-summary { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .dnd-layout-summary-card {
      padding: 12px;
      border: 1px solid var(--rule-soft);
      border-radius: calc(var(--radius) - 4px);
      background: rgba(255,255,255,0.28);
      text-align: center;
      min-height: 86px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 8px;
    }
    .dnd-layout-summary-card .value {
      font-family: var(--display);
      font-size: 1.55rem;
      line-height: 1;
      color: var(--accent);
    }
    .dnd-layout-inspiration {
      display: inline-flex;
      justify-content: center;
      align-items: center;
      min-height: 36px;
      position: relative;
    }
    .dnd-layout-inspiration input { position: absolute; opacity: 0; pointer-events: none; }
    .dnd-layout-inspiration span {
      display: inline-block;
      width: 22px;
      height: 22px;
      border: 2px solid var(--accent);
      border-radius: 50%;
      background: transparent;
    }
    .dnd-layout-inspiration input:checked + span {
      background: radial-gradient(circle, var(--accent) 0 42%, transparent 45%);
    }
    .dnd-layout-first-grid,
    .dnd-layout-second-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.04fr) minmax(0, 1.34fr);
      gap: 12px;
    }
    .dnd-layout-left-column,
    .dnd-layout-right-column,
    .dnd-layout-sidebar {
      display: grid;
      gap: 12px;
      align-content: start;
    }
    .dnd-layout-sidebar-group {
      display: grid;
      gap: 12px;
    }
    .dnd-layout-sidebar-stack {
      display: grid;
      gap: 12px;
    }
    .dnd-layout-subsection {
      display: grid;
      gap: 6px;
    }
    .dnd-layout-subtitle {
      font-family: var(--sans);
      font-size: 0.72rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .dnd-layout-abilities-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .dnd-layout-ability-card {
      border: 1px solid var(--rule-soft);
      border-radius: calc(var(--radius) - 6px);
      background: rgba(255,255,255,0.22);
      padding: 10px;
      box-shadow: inset 1px 0 0 var(--accent);
    }
    .ability-heading {
      display: flex;
      justify-content: center;
      align-items: baseline;
      margin-bottom: 8px;
    }
    .ability-name {
      font-family: var(--sans);
      font-size: 0.82rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--ink);
      font-weight: 700;
      text-align: center;
    }
    .ability-core {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 14px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--rule-soft);
      margin-bottom: 8px;
    }
    .ability-mod {
      font-family: var(--display);
      font-size: 2.2rem;
      line-height: 1;
      font-weight: 700;
      color: var(--accent);
      text-align: center;
      min-width: 2.4rem;
    }
    .ability-score-wrap {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
    }
    .ability-score-label {
      font-family: var(--sans);
      font-size: 0.58rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .ability-score {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 2.2rem;
      min-height: 1.5rem;
      padding: 0 0.4rem;
      border: 1px solid var(--rule-soft);
      background: rgba(255,255,255,0.16);
      font-family: var(--mono);
      font-size: 0.95rem;
      font-weight: 700;
      text-align: center;
      color: var(--ink);
    }
    .ability-save {
      display: grid;
      grid-template-columns: 14px 1fr auto;
      gap: 6px;
      align-items: baseline;
      font-size: 0.9rem;
      margin-bottom: 0;
    }
    .ability-skill-group {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--rule-soft);
    }
    .ability-skill-list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 4px;
      font-size: 0.88rem;
    }
    .ability-skill-list li {
      display: grid;
      grid-template-columns: 14px 1fr auto;
      gap: 6px;
      align-items: baseline;
    }
    .ability-empty { color: var(--ink-soft); }
    .ability-skill-bonus { font-family: var(--mono); }
    .dnd-layout-token-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 10px;
    }
    .dnd-layout-token {
      display: inline-flex;
      align-items: center;
      padding: 4px 9px;
      border: 1px solid var(--rule-soft);
      border-radius: 999px;
      color: var(--ink-soft);
      background: rgba(255,255,255,0.22);
      font-size: 0.7rem;
    }
    .dnd-layout-token.active {
      color: var(--on-accent, var(--paper));
      background: var(--accent);
      border-color: var(--accent);
    }
    .dnd-layout-note-line {
      margin-top: 6px;
      font-size: 0.92rem;
      color: var(--ink);
    }
    .dnd-layout-inline-divider {
      margin: 12px 0 8px;
      border-top: 1px solid var(--rule-soft);
    }
    .dnd-layout-feature-pair {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .dnd-layout-third-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 12px;
    }
    .dnd-layout-tall-panel ul {
      columns: 2;
      column-gap: 20px;
    }
    .dnd-layout-panel ul:not(.ability-skill-list) {
      margin: 0;
      padding: 0 0 0 18px;
      line-height: 1.36;
    }
    .dnd-layout-panel ul:not(.ability-skill-list) li {
      margin-bottom: 5px;
      break-inside: avoid;
    }
    .dnd-layout-slot-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px 14px;
    }
    .dnd-layout-slot-row {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 8px;
      align-items: center;
      min-height: 28px;
    }
    .slot-level {
      font-family: var(--sans);
      font-size: 0.8rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .slot-pips {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      align-items: center;
    }
    .slot-pip {
      position: relative;
      display: inline-flex;
      width: 18px;
      height: 18px;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .slot-pip input {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      margin: 0;
      opacity: 0;
      cursor: pointer;
      z-index: 2;
    }
    .slot-pip span {
      position: relative;
      display: block;
      width: 11px;
      height: 11px;
      border: 1.5px solid var(--rule);
      background: rgba(255,255,255,0.72);
      transform: rotate(45deg);
      pointer-events: none;
      transition: background 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
    }
    .slot-pip span::after {
      content: "";
      position: absolute;
      inset: 24%;
      background: rgba(255,255,255,0.92);
      opacity: 0;
      transition: opacity 0.12s ease;
      border-radius: inherit;
    }
    .slot-pip input:checked + span {
      background: var(--accent);
      border-color: var(--accent);
      box-shadow: 0 0 0 1px rgba(0,0,0,0.08);
    }
    .slot-pip input:checked + span::after { opacity: 1; }
    .slot-pip input:focus-visible + span {
      outline: 2px solid var(--accent-strong);
      outline-offset: 2px;
    }
    .no-pips { color: var(--ink-soft); }
    .feature-uses {
      display: inline-flex;
      gap: 3px;
      align-items: center;
      margin-left: 6px;
      vertical-align: middle;
    }
    .feature-uses .slot-pip { width: 12px; height: 12px; }
    .feature-uses .slot-pip span { width: 7px; height: 7px; border-width: 1px; }
    .feature-pool {
      display: inline-flex;
      align-items: baseline;
      gap: 3px;
      margin-left: 6px;
      vertical-align: middle;
      font-variant-numeric: tabular-nums;
    }
    .feature-pool-input {
      width: 2.4rem;
      padding: 0 2px;
      border: 0;
      border-bottom: 1px solid var(--rule-soft);
      background: transparent;
      color: var(--ink);
      text-align: right;
      font: inherit;
      outline: none;
      -moz-appearance: textfield;
      appearance: textfield;
    }
    .feature-pool-input::-webkit-inner-spin-button,
    .feature-pool-input::-webkit-outer-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }
    .feature-pool-input:focus { border-bottom-color: var(--accent); }
    .feature-pool-sep, .feature-pool-max { color: var(--ink-soft); font-size: 0.92em; }
    .dnd-layout-table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 0.82rem;
    }
    .dnd-layout-table td {
      padding: 7px 8px 7px 0;
      border-bottom: 1px solid var(--rule-soft);
      vertical-align: top;
      line-height: 1.2;
    }
    .dnd-layout-table td:last-child { padding-right: 0; }
    .dnd-layout-table td:nth-child(1) { width: 30%; }
    .dnd-layout-table td:nth-child(2) { width: 13%; }
    .dnd-layout-table td:nth-child(3) { width: 21%; }
    .dnd-layout-table td:nth-child(4) { width: 36%; }
    .dnd-layout-attack-table td:nth-child(1) { width: 30%; }
    .dnd-layout-attack-table td:nth-child(2) { width: 12%; }
    .dnd-layout-attack-table td:nth-child(3) { width: 22%; }
    .dnd-layout-attack-table td:nth-child(4) {
      width: 36%;
      padding-left: 10px;
    }
    .dnd-layout-damage-roll {
      display: inline-block;
      white-space: nowrap;
    }
    .dnd-layout-damage-type { white-space: normal; }
    .dnd-layout-spell-table td:nth-child(1) { width: 6%; text-align: center; }
    .dnd-layout-spell-table td:nth-child(2) { width: 29%; }
    .dnd-layout-spell-table td:nth-child(3) { width: 11%; }
    .dnd-layout-spell-table td:nth-child(4) { width: 12%; }
    .dnd-layout-spell-table td:nth-child(5) { width: 17%; text-align: center; letter-spacing: 0.08em; }
    .dnd-layout-spell-table td:nth-child(6) { width: 25%; }
    .dnd-layout-spell-legend,
    .spell-flags-cell {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      align-items: center;
    }
    .dnd-layout-spell-legend {
      margin-bottom: 8px;
    }
    .spell-flag {
      display: inline-flex;
      align-items: center;
      padding: 1px 6px;
      border: 1px solid var(--rule-soft);
      font-family: var(--sans);
      font-size: 0.62rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      line-height: 1.4;
      white-space: nowrap;
    }
    .spell-flag.on {
      color: var(--accent);
      border-color: var(--accent);
      background: rgba(255,255,255,0.28);
      font-weight: 700;
    }
    .spell-flag.off {
      color: var(--ink-soft);
      opacity: 0.62;
    }
    .dnd-layout-coin-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .dnd-layout-coin-grid-compact { margin-top: 4px; }
    .dnd-layout-coin-card { text-align: center; }
    .dnd-layout-coin-card .v2-field { text-align: center; }
    .muted,
    .source-note {
      color: var(--ink-soft);
      font-style: italic;
    }
    .dnd-layout-footer {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px 14px;
      margin-top: 12px;
      padding: 8px 10px 0;
      border-top: 1px solid var(--rule-soft);
      color: var(--ink-soft);
      font: 0.66rem/1.35 var(--sans);
      text-align: center;
    }
    .ref-anchor { color: inherit; }
    @media (max-width: 960px) {
      .dnd-layout-header-grid,
      .dnd-layout-summary-grid,
      .dnd-layout-spell-summary,
      .dnd-layout-first-grid,
      .dnd-layout-second-grid,
      .dnd-layout-third-grid,
      .dnd-layout-feature-pair,
      .dnd-layout-slot-grid,
      .dnd-layout-health-grid,
      .dnd-layout-hitdice-grid,
      .dnd-layout-death-grid,
      .dnd-layout-coin-grid {
        grid-template-columns: 1fr;
      }
      .dnd-layout-toolbar,
      .dnd-layout-page-head {
        flex-direction: column;
        align-items: stretch;
      }
      .dnd-layout-emblem { display: none; }
      .dnd-layout-toolbar-actions {
        justify-content: flex-start;
        min-width: 0;
      }
      .dnd-layout-identity-panel,
      .dnd-layout-pill-panel,
      .dnd-layout-health-panel,
      .dnd-layout-hitdice-panel {
        grid-column: span 10;
      }
      .dnd-layout-identity-grid,
      .dnd-layout-abilities-grid {
        grid-template-columns: 1fr;
      }
      .dnd-layout-tall-panel ul { columns: 1; }
    }
    @media print {
      @page { size: A4; margin: 9mm; }
      body {
        background: white !important;
        font-size: 12px;
      }
      .screen-only,
      .dnd-layout-shell::before,
      .dnd-layout-shell::after { display: none !important; }
      .dnd-layout-shell {
        max-width: none;
        padding: 0;
        width: auto;
      }
      .dnd-layout-page {
        box-shadow: none;
        margin: 0 0 7mm;
        padding: 10px;
        break-inside: auto;
      }
      .dnd-layout-page:last-child { margin-bottom: 0; }
      .dnd-layout-spell-page,
      .dnd-layout-equipment-page { break-before: page; }
      .dnd-layout-page-head {
        flex-direction: row;
        align-items: flex-start;
        margin-bottom: 8px;
        padding-bottom: 6px;
      }
      .dnd-layout-page-head > div:first-of-type { padding: 1px 0 0 2px; }
      .dnd-layout-emblem { display: block; width: 30px; height: 30px; margin-top: 6px; }
      .dnd-layout-page-title { font-size: 1.24rem; }
      .dnd-layout-page-subtitle {
        margin-top: 3px;
        font-size: 0.74rem;
      }
      .dnd-layout-header-grid {
        grid-template-columns: repeat(10, minmax(0, 1fr)) !important;
        gap: 6px !important;
      }
      .dnd-layout-summary-grid {
        grid-template-columns: repeat(6, minmax(0, 1fr)) !important;
        gap: 6px !important;
      }
      .dnd-layout-spell-summary {
        grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
        gap: 6px !important;
      }
      .dnd-layout-first-grid {
        grid-template-columns: minmax(0, 1.02fr) minmax(0, 1.28fr) !important;
        gap: 6px !important;
        break-inside: auto;
      }
      .dnd-layout-first-grid > .dnd-layout-left-column,
      .dnd-layout-first-grid > .dnd-layout-right-column {
        break-inside: auto;
      }
      .dnd-layout-second-grid {
        grid-template-columns: minmax(0, 1.26fr) minmax(0, 0.84fr) !important;
        gap: 8px !important;
      }
      .dnd-layout-third-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 8px !important;
      }
      .dnd-layout-feature-pair {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 8px !important;
      }
      .dnd-layout-slot-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        gap: 8px 10px !important;
      }
      .dnd-layout-health-grid {
        grid-template-columns: 1fr !important;
        gap: 4px !important;
      }
      .dnd-layout-hitdice-grid {
        grid-template-columns: 1fr !important;
        gap: 4px !important;
      }
      .dnd-layout-death-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 6px !important;
      }
      .dnd-layout-hitdice-total,
      .dnd-layout-hitdice-panel .death-track {
        border-top: 0 !important;
        padding-top: 0 !important;
      }
      .dnd-layout-coin-grid {
        grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
        gap: 4px !important;
      }
      .dnd-layout-identity-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 6px !important;
      }
      .dnd-layout-abilities-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: 6px !important;
      }
      .dnd-layout-identity-panel { grid-column: span 4 !important; }
      .dnd-layout-pill-panel { grid-column: span 1 !important; }
      .dnd-layout-health-panel,
      .dnd-layout-hitdice-panel { grid-column: span 2 !important; }
      .dnd-layout-level-panel,
      .dnd-layout-armor-panel { gap: 4px; }
      .dnd-layout-panel {
        padding: 10px;
      }
      .dnd-layout-panel ul:not(.ability-skill-list) {
        padding-left: 14px;
        line-height: 1.15;
        font-size: 0.78rem;
      }
      .dnd-layout-panel ul:not(.ability-skill-list) li {
        margin-bottom: 1.5px;
      }
      .dnd-layout-panel .source-note {
        font-size: 0.7rem;
      }
      .sheet-panel {
        background-position:
          top 2px left 2px, top 2px left 2px,
          top 2px right 2px, top 2px right 2px,
          bottom 2px left 2px, bottom 2px left 2px,
          bottom 2px right 2px, bottom 2px right 2px,
          top left !important;
        background-size:
          7px 1.2px, 1.2px 7px,
          7px 1.2px, 1.2px 7px,
          7px 1.2px, 1.2px 7px,
          7px 1.2px, 1.2px 7px,
          100% 100% !important;
      }
      .sheet-page {
        background-position:
          top 4px left 4px, top 4px left 4px,
          top 4px right 4px, top 4px right 4px,
          bottom 4px left 4px, bottom 4px left 4px,
          bottom 4px right 4px, bottom 4px right 4px,
          top left, top left !important;
        background-size:
          14px 1.6px, 1.6px 14px,
          14px 1.6px, 1.6px 14px,
          14px 1.6px, 1.6px 14px,
          14px 1.6px, 1.6px 14px,
          100% 90px, 100% 100% !important;
      }
      .dnd-layout-section-title { margin: 0 0 6px; }
      .dnd-layout-header-grid .dnd-layout-section-title {
        padding-top: 1px;
        padding-bottom: 1px;
      }
      .dnd-layout-field-card,
      .dnd-layout-mini-field,
      .dnd-layout-coin-card { gap: 3px; }
      .dnd-layout-section-title,
      .dnd-layout-label,
      .ability-name,
      .slot-level {
        font-size: 0.62rem;
      }
      .dnd-layout-subtitle,
      .spell-flag { font-size: 0.60rem; }
      .dnd-layout-summary-card {
        min-height: 54px;
        padding: 6px;
        gap: 4px;
      }
      .dnd-layout-summary-card .value { font-size: 1.02rem; }
      .dnd-layout-armor-panel .dnd-layout-pill-number {
        align-items: center;
        padding: 0;
      }
      .dnd-layout-armor-shield {
        gap: 1px;
        padding-top: 3px;
      }
      .dnd-layout-armor-shield .value {
        display: block;
        font-size: 0.98rem;
      }
      .dnd-layout-pill-value {
        min-height: 44px;
        margin-bottom: 4px;
      }
      .dnd-layout-pill-input { font-size: 1.22rem !important; }
      .dnd-layout-pill-number { font-size: 1.22rem; }
      .dnd-layout-mini-stat {
        padding-top: 4px;
        font-size: 0.72rem;
      }
      .dnd-layout-mini-stat .value { font-size: 0.84rem; }
      .dnd-layout-health-grid {
        grid-template-columns: 1fr !important;
        gap: 4px !important;
      }
      .dnd-layout-health-field,
      .dnd-layout-hitdice-field,
      .dnd-layout-hitdice-total {
        display: grid;
        grid-template-columns: 58px 52px;
        gap: 6px;
        align-items: end;
        justify-content: start;
      }
      .dnd-layout-health-field .v2-field,
      .dnd-layout-hitdice-field .v2-field {
        text-align: left;
        width: 52px;
        max-width: 52px;
      }
      .dnd-layout-hitdice-grid {
        grid-template-columns: 1fr !important;
        gap: 4px !important;
      }
      .dnd-layout-hitdice-total {
        padding-top: 0;
        border-top: 0;
        font-size: 0.66rem;
      }
      .dnd-layout-hitdice-total .value {
        justify-self: start;
        font-size: 0.92rem;
      }
      .dnd-layout-attack-table td:nth-child(3) {
        width: 24%;
      }
      .dnd-layout-attack-table td:nth-child(4) {
        width: 34%;
        padding-left: 12px;
      }
      .death-track {
        gap: 3px;
        padding-top: 4px;
      }
      .death-track .dnd-layout-label {
        font-size: 0.54rem;
        line-height: 1.08;
        letter-spacing: 0.05em;
      }
      .ability-mod { font-size: 1.32rem; }
      .ability-save,
      .ability-skill-list,
      .dnd-layout-note-line,
      .dnd-layout-page .v2-field {
        font-size: 0.72rem;
      }
      .dnd-layout-page .v2-field {
        padding: 1px 0 2px;
        line-height: 1.08;
      }
      .dnd-layout-left-column,
      .dnd-layout-right-column { gap: 8px; }
      .dnd-layout-ability-card { padding: 8px; }
      .ability-heading {
        margin-bottom: 6px;
        gap: 6px;
      }
      .ability-core {
        gap: 8px;
        padding-bottom: 6px;
        margin-bottom: 6px;
      }
      .ability-code {
        min-width: 2rem;
        min-height: 1.35rem;
        font-size: 0.78rem;
      }
      .ability-score {
        min-width: 1.9rem;
        min-height: 1.3rem;
        font-size: 0.8rem;
        font-weight: 700;
      }
      .ability-skill-group {
        margin-top: 6px;
        padding-top: 6px;
      }
      .ability-skill-list { gap: 3px; }
      .dnd-layout-token-row {
        gap: 6px;
        margin-bottom: 6px;
      }
      .dnd-layout-token {
        padding: 3px 7px;
        font-size: 0.62rem;
      }
      .dnd-layout-note-line { margin-top: 4px; }
      .dnd-layout-inline-divider {
        margin: 8px 0 6px;
      }
      .dnd-layout-coin-grid-compact { margin-top: 2px; }
      .dnd-layout-training-panel .dnd-layout-note-line {
        line-height: 1.16;
      }
      textarea.v2-field.dnd-layout-area { min-height: 86px; }
      textarea.v2-field.dnd-layout-area.small-area { min-height: 42px; }
      textarea.v2-field.dnd-layout-area.journal-area { min-height: 136px; }
      textarea.v2-field.dnd-layout-area.equipment-area { min-height: 220px; }
      .dnd-layout-table { font-size: 0.70rem; }
      .dnd-layout-table td {
        padding: 3px 4px 3px 0;
        line-height: 1.1;
      }
      .slot-pip {
        width: 12px;
        height: 12px;
      }
      .slot-pip span {
        width: 7px;
        height: 7px;
      }
      .dnd-layout-tall-panel ul {
        columns: 2;
        column-gap: 14px;
      }
      .dnd-layout-page:last-child { page-break-after: auto; }
      .dnd-layout-footer {
        margin-top: 0;
        padding-top: 3mm;
        font-size: 0.54rem;
      }
      .dnd-layout-panel,
      .dnd-layout-ability-card,
      .dnd-layout-summary-card { break-inside: avoid; }
      .dnd-layout-breakable-panel { break-inside: auto; }
    }
    """

    storage_key = json.dumps(f"foundry-dnd-layout:{sheet_id}:{style}")
    script = f"""
    (() => {{
      const storageKey = {storage_key};
      const state = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
      const persistNodes = document.querySelectorAll("[data-persist]");
      const printValueNodes = document.querySelectorAll("[data-print-value]");
      const livePrintValues = new Map();
      const autoSizeTextareas = () => {{
        for (const node of document.querySelectorAll("textarea.v2-field")) {{
          node.style.height = "auto";
          node.style.height = `${{Math.max(node.scrollHeight, node.offsetHeight)}}px`;
        }}
      }};
      const applyPrintValues = () => {{
        for (const node of printValueNodes) {{
          livePrintValues.set(node, node.value);
          node.value = node.dataset.printValue || "";
        }}
        autoSizeTextareas();
      }};
      const restorePrintValues = () => {{
        for (const [node, value] of livePrintValues.entries()) {{
          node.value = value;
        }}
        livePrintValues.clear();
        autoSizeTextareas();
      }};

      for (const node of persistNodes) {{
        const key = node.dataset.persist;
        if (Object.prototype.hasOwnProperty.call(state, key)) {{
          if (node.type === "checkbox") {{
            node.checked = Boolean(state[key]);
          }} else {{
            node.value = state[key];
          }}
        }}

        const save = () => {{
          state[key] = node.type === "checkbox" ? node.checked : node.value;
          localStorage.setItem(storageKey, JSON.stringify(state));
          if (node.tagName === "TEXTAREA") {{
            node.style.height = "auto";
            node.style.height = `${{Math.max(node.scrollHeight, node.offsetHeight)}}px`;
          }}
        }};

        node.addEventListener(node.type === "checkbox" ? "change" : "input", save);
      }}

      autoSizeTextareas();
      window.addEventListener("beforeprint", applyPrintValues);
      window.addEventListener("afterprint", restorePrintValues);
      window.addEventListener("beforeprint", autoSizeTextareas);

      document.getElementById("print-dnd-layout")?.addEventListener("click", () => window.print());
      document.getElementById("reset-dnd-layout")?.addEventListener("click", () => {{
        localStorage.removeItem(storageKey);
        window.location.reload();
      }});
    }})();
    """

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(data["name"])} Character Sheet</title>
    <style>{style_css}</style>
  </head>
  <body class="dnd-layout-theme-{esc(style)}{(' dnd-layout-palette-' + esc(palette)) if palette else ''}">
    {body}
    <script>{script}</script>
  </body>
</html>
"""


def _mode_vars(palette: dict[str, str]) -> str:
    return "\n".join(
        f"      --{key.replace('_', '-')}: {palette[key]};"
        for key in ("paper", "panel", "panel_soft", "ink", "ink_soft", "rule", "rule_soft",
                    "shadow", "accent", "accent_strong", "on_accent")
    )


def _sheet_mode_overrides(style: str, theme_palette: dict[str, dict[str, str]] | None = None) -> str:
    if theme_palette is None:
        theme_palette = build_theme_palette(THEMES.get(style, THEMES["ledger"]))
    light_vars = _mode_vars(theme_palette["light"])
    dark_vars = _mode_vars(theme_palette["dark"])
    base = f"""
    /* Native sheet overrides: sharp corners + corner brackets + mode-aware palettes */
    :root {{
      --sheet-bracket: 12px;
      --sheet-bracket-thick: 1.5px;
    }}
    * {{ border-radius: 0 !important; }}
    .sheet-page,
    .sheet-panel,
    .sheet-summary-card,
    .sheet-ability-card,
    .sheet-toolbar,
    .sheet-reference-line,
    .sheet-pill-panel {{ border-radius: 0 !important; }}

    .sheet-page {{
      background-image:
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(180deg, rgba(255,255,255,0.08), transparent 90px),
        linear-gradient(var(--panel), var(--panel));
      background-repeat: no-repeat;
      background-position:
        top 8px left 8px, top 8px left 8px,
        top 8px right 8px, top 8px right 8px,
        bottom 8px left 8px, bottom 8px left 8px,
        bottom 8px right 8px, bottom 8px right 8px,
        top left, top left;
      background-size:
        22px 2px, 2px 22px,
        22px 2px, 2px 22px,
        22px 2px, 2px 22px,
        22px 2px, 2px 22px,
        100% 90px, 100% 100%;
      border: 0 !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .sheet-panel {{
      background-image:
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--panel-soft), var(--panel-soft));
      background-repeat: no-repeat;
      background-position:
        top 4px left 4px, top 4px left 4px,
        top 4px right 4px, top 4px right 4px,
        bottom 4px left 4px, bottom 4px left 4px,
        bottom 4px right 4px, bottom 4px right 4px,
        top left;
      background-size:
        12px 1.5px, 1.5px 12px,
        12px 1.5px, 1.5px 12px,
        12px 1.5px, 1.5px 12px,
        12px 1.5px, 1.5px 12px,
        100% 100%;
      border: 0 !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}

    .sheet-summary-card,
    .sheet-ability-card {{
      border: 0 !important;
      border-left: 3px solid var(--accent) !important;
      background: var(--panel-soft) !important;
    }}

    .sheet-pill-value {{
      border: 1px solid var(--rule-soft) !important;
      clip-path: none;
      background: rgba(255,255,255,0.3);
    }}

    .sheet-token {{
      border-radius: 0 !important;
      border-left: 2px solid var(--accent) !important;
      padding-left: 8px !important;
    }}

    .sheet-inspiration span {{
      width: 16px;
      height: 16px;
      border-radius: 0 !important;
      transform: rotate(45deg);
    }}
    .sheet-inspiration input:checked + span {{
      background: var(--accent);
      box-shadow: inset 0 0 0 3px rgba(255,255,255,0.86);
    }}

    body.sheet-theme-ledger .slot-pip span {{
      transform: none;
      border-radius: 2px;
    }}
    body.sheet-theme-gazette .slot-pip span {{
      transform: none;
      border-radius: 999px;
    }}
    body.sheet-theme-grimoire .slot-pip span {{
      transform: rotate(45deg);
      border-radius: 0;
    }}

    .sheet-toolbar button {{
      border-radius: 0 !important;
      min-width: max-content;
      overflow: visible;
    }}
    .sheet-toolbar button.secondary {{
      border: 1px solid var(--accent);
    }}

    .sheet-section-title {{
      padding-bottom: 4px;
      border-bottom: 1px solid var(--rule-soft);
      margin-bottom: 10px;
    }}

    :root {{
{light_vars}
    }}
    body.sheet-theme-{style}[data-theme="dark"] {{
{dark_vars}
    }}
    body[data-theme="dark"] {{
      color: var(--ink);
    }}
    body[data-theme="dark"]:not([class*="sheet-palette-"]) {{
      background: var(--paper) !important;
    }}
    body[data-theme="dark"] .slot-pip span {{
      background: rgba(255, 255, 255, 0.06);
      border-color: var(--rule-soft);
    }}
    body[data-theme="dark"] .slot-pip input:checked + span {{
      box-shadow: 0 0 0 1px rgba(255,255,255,0.12);
    }}
    body[data-theme="dark"] .sheet-page .v2-field,
    body[data-theme="dark"] textarea.v2-field.sheet-area {{
      color: var(--ink);
      background: transparent;
    }}
    body[data-theme="dark"] .sheet-pill-value {{
      background: rgba(255, 255, 255, 0.04);
    }}
    body[data-theme="dark"] .sheet-toolbar,
    body[data-theme="dark"] .sheet-reference-line {{
      background: rgba(22, 24, 30, 0.72);
    }}
    body[data-theme="dark"] .sheet-token {{
      background: rgba(255, 255, 255, 0.04);
    }}
    body[data-theme="dark"] .sheet-token.active {{
      color: var(--on-accent) !important;
    }}
    body[data-theme="dark"] .sheet-inspiration span {{
      background: transparent;
    }}
    body[data-theme="dark"] .sheet-inspiration input:checked + span {{
      background: var(--accent);
      box-shadow: inset 0 0 0 3px var(--paper);
    }}

    body[data-theme="mono"] {{
      --paper: #ffffff !important;
      --panel: #ffffff !important;
      --panel-soft: #f7f7f7 !important;
      --ink: #111111 !important;
      --ink-soft: #4a4a4a !important;
      --rule: rgba(17, 17, 17, 0.82) !important;
      --rule-soft: rgba(17, 17, 17, 0.20) !important;
      --shadow: none !important;
      --accent: #111111 !important;
      --accent-strong: #111111 !important;
      background: #ffffff !important;
      color: var(--ink);
    }}
    body[data-theme="mono"] .sheet-page {{
      background-image:
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(var(--accent-strong), var(--accent-strong)),
        linear-gradient(#ffffff, #ffffff),
        linear-gradient(#ffffff, #ffffff) !important;
      box-shadow: none !important;
    }}
    body[data-theme="mono"] .sheet-panel {{
      background-image:
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(var(--accent), var(--accent)),
        linear-gradient(#fbfbfb, #fbfbfb) !important;
      box-shadow: none !important;
    }}
    body[data-theme="mono"] .sheet-summary-card,
    body[data-theme="mono"] .sheet-ability-card {{
      background: #fafafa !important;
      border-left-color: #111111 !important;
    }}
    body[data-theme="mono"] .sheet-toolbar,
    body[data-theme="mono"] .sheet-reference-line {{
      background: #f4f4f4 !important;
      color: var(--ink-soft);
      border-color: var(--rule-soft);
    }}
    body[data-theme="mono"] .sheet-toolbar button {{
      background: #111111 !important;
      color: #ffffff !important;
      border-color: #111111 !important;
    }}
    body[data-theme="mono"] .sheet-toolbar button.secondary {{
      background: transparent !important;
      color: #111111 !important;
      border-color: #111111 !important;
    }}
    body[data-theme="mono"] .sheet-page .v2-field,
    body[data-theme="mono"] textarea.v2-field.sheet-area {{
      color: #111111;
      background: transparent;
    }}
    body[data-theme="mono"] .sheet-pill-value {{
      background: #ffffff !important;
      border-color: var(--rule-soft) !important;
    }}
    body[data-theme="mono"] .sheet-token {{
      background: #f8f8f8 !important;
      color: #333333 !important;
      border-left-color: #555555 !important;
    }}
    body[data-theme="mono"] .sheet-token.active {{
      background: #111111 !important;
      color: #ffffff !important;
      border-left-color: #111111 !important;
    }}
    body[data-theme="mono"] .slot-pip span {{
      background: #ffffff !important;
      border-color: rgba(17, 17, 17, 0.62) !important;
      box-shadow: none !important;
    }}
    body[data-theme="mono"] .slot-pip input:checked + span {{
      background: #111111 !important;
      border-color: #111111 !important;
      box-shadow: none !important;
    }}
    body[data-theme="mono"] .sheet-inspiration span {{
      background: transparent;
      border-color: #111111;
    }}
    body[data-theme="mono"] .sheet-inspiration input:checked + span {{
      background: #111111 !important;
      box-shadow: inset 0 0 0 3px #ffffff !important;
    }}

    @media print {{
      body[data-theme="light"] {{
        --paper: #ffffff !important;
        --panel: #ffffff !important;
        --panel-soft: rgba(0, 0, 0, 0.025) !important;
        --rule-soft: rgba(17, 17, 17, 0.18) !important;
        --shadow: none !important;
        background: #ffffff !important;
      }}
      body[data-theme="dark"] {{ background: var(--paper) !important; }}
      body[data-theme="mono"] {{ background: #ffffff !important; }}
      .sheet-page,
      .sheet-panel {{
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
    """
    return base


def _sheet_theme_script(sheet_id: str, style: str, initial_theme: str | None = None) -> str:
    key = json.dumps(f"foundry-sheet-v{APP_STORAGE_VERSION}-theme:{sheet_id}")
    default_theme = json.dumps("light")
    initial_theme_json = json.dumps(initial_theme or "")
    return f"""
    (() => {{
      const key = {key};
      const defaultTheme = {default_theme};
      const initialTheme = {initial_theme_json};
      const themes = ["light", "dark", "mono"];
      const labels = {{
        light: "☾ Dark",
        dark: "◩ Mono",
        mono: "☀ Light",
      }};
      const params = new URLSearchParams(window.location.search);
      const override = params.get("theme");
      const saved = localStorage.getItem(key);
      const initial = override || saved || initialTheme || defaultTheme;
      document.body.setAttribute("data-theme", initial);
      const btn = document.getElementById("theme-sheet");
      const syncLabel = () => {{
        if (!btn) return;
        const t = document.body.getAttribute("data-theme");
        btn.textContent = labels[t] || labels.light;
      }};
      syncLabel();
      btn?.addEventListener("click", () => {{
        const current = document.body.getAttribute("data-theme");
        const next = themes[(themes.indexOf(current) + 1 + themes.length) % themes.length];
        document.body.setAttribute("data-theme", next);
        localStorage.setItem(key, next);
        syncLabel();
      }});
    }})();
    """


def render_character_sheet(
    data: dict[str, Any],
    sheet_id: str,
    style: str = "ledger",
    initial_theme: str | None = None,
    theme_palette: dict[str, dict[str, str]] | None = None,
    palette_decoration: str | None = None,
    include_footer: bool = True,
    paper: str = "a4",
) -> str:
    html = render_dnd_layout_template(data, sheet_id, style=style, palette=palette_decoration)
    html = html.replace(
        '"foundry-dnd-layout:',
        f'"foundry-sheet-v{APP_STORAGE_VERSION}-data:',
    )
    html = html.replace("dnd-layout/", f"v{APP_VERSION}/")
    html = html.replace("print-dnd-layout", "print-sheet")
    html = html.replace("reset-dnd-layout", "reset-sheet")
    html = html.replace("dnd-layout-", "sheet-")
    html = html.replace("dnd-layout", "sheet")
    html = html.replace("@page { size: A4; margin: 9mm; }", f"@page {{ {PAPER_PROFILES[paper]} }}")

    overrides = _sheet_mode_overrides(style, theme_palette=theme_palette)
    fonts = embedded_font_css(style, palette_decoration)
    html = html.replace("</style>", overrides + fonts + "\n</style>", 1)

    toggle_btn = '<button type="button" id="print-sheet">Print / Save PDF</button>'
    new_btns = (
        '<button type="button" id="print-sheet">Print / Save PDF</button>'
        '\n          <button type="button" id="theme-sheet" class="secondary">☾ Dark</button>'
    )
    html = html.replace(toggle_btn, new_btns, 1)

    if include_footer:
        footer_html = (
            '<footer class="sheet-footer">'
            '<span>Made by Stravinci @ stravinci.pt</span>'
            '<span>Unofficial fan-made character sheet. Not affiliated with or endorsed by Wizards of the Coast.</span>'
            '</footer>'
        )
        html = html.replace("\n    <script>", f"\n    {footer_html}\n    <script>", 1)

    theme_js = _sheet_theme_script(sheet_id, style, initial_theme=initial_theme)
    html = html.replace("</body>", f"<script>{theme_js}</script>\n  </body>", 1)

    return html


class Dnd5eAdapter:
    """System adapter for Foundry's ``dnd5e`` system (and D&D 2024-style data).

    This is the first and currently only adapter. It is a thin object that binds
    the module's dnd5e schema logic (parsing/derivation in ``sheet_context``,
    class-based theming in ``primary_class_slug``, and layout in
    ``render_character_sheet``) to the :class:`systems.SystemAdapter` contract, so
    the generic pipeline in :func:`write_output` (and the web UI) never touches
    dnd5e specifics directly — it only ever goes through this boundary.

    A second system (e.g. Pathfinder 2e) would add its own adapter with the same
    four methods and register it in :mod:`systems`; it would inherit the shared
    theme registry, color modes, paper profiles, PDF export, and web UI for free.
    """

    system_id = "dnd5e"
    display_name = "D&D Fifth Edition (dnd5e)"

    #: Ability keys every dnd5e actor carries — the schema fingerprint used to
    #: recognize an export that does not declare its system id.
    _FINGERPRINT_ABILITIES = frozenset(ABILITY_ORDER)

    def matches(self, actor: dict[str, Any]) -> bool:
        system = actor.get("system")
        if not isinstance(system, dict):
            return False
        abilities = system.get("abilities")
        if not isinstance(abilities, dict):
            return False
        return self._FINGERPRINT_ABILITIES.issubset(abilities.keys())

    def build_context(self, actor: dict[str, Any]) -> dict[str, Any]:
        return sheet_context(actor)

    def default_theme(self, actor: dict[str, Any]) -> str | None:
        return primary_class_slug(actor)

    def render(
        self,
        context: dict[str, Any],
        sheet_id: str,
        *,
        style: str,
        initial_theme: str | None,
        theme_palette: dict[str, dict[str, str]] | None,
        palette_decoration: str | None,
        include_footer: bool,
        paper: str,
    ) -> str:
        return render_character_sheet(
            context,
            sheet_id,
            style=style,
            initial_theme=initial_theme,
            theme_palette=theme_palette,
            palette_decoration=palette_decoration,
            include_footer=include_footer,
            paper=paper,
        )


DND5E_ADAPTER = systems.register(Dnd5eAdapter())


def _render_one_theme(
    context: dict[str, Any],
    sheet_id: str,
    output_dir: Path,
    theme_label: str,
    entry: dict,
    mode: str | None,
    include_footer: bool = True,
    paper: str = "a4",
    adapter: systems.SystemAdapter = DND5E_ADAPTER,
) -> Path:
    html_path = output_dir / f"{sheet_id}-character-sheet-{theme_label.lstrip('#')}.html"
    palette = build_theme_palette(entry)
    # Always write UTF-8: the sheet HTML contains non-latin1 glyphs (e.g. the
    # ☾ dark-mode toggle, em dashes), and Path.write_text otherwise uses the
    # platform default encoding (cp1252 on Windows), which cannot encode them.
    html_path.write_text(adapter.render(
        context,
        sheet_id,
        style=entry["base"],
        initial_theme=mode or entry.get("default_mode"),
        theme_palette=palette,
        palette_decoration=entry.get("decoration"),
        include_footer=include_footer,
        paper=paper,
    ), encoding="utf-8")
    return html_path


def load_actor_file(actor_path: Path) -> dict[str, Any]:
    """Read an actor export into a Foundry-shaped actor dict.

    Accepts both Foundry VTT JSON exports and Lion's Den "Fight Club 5e" XML
    exports (``.xml`` extension or a ``<pc>`` root). XML is converted up front so
    the rest of the pipeline only ever sees a Foundry-shaped dnd5e actor dict.
    """
    text = actor_path.read_text(encoding="utf-8")
    if actor_path.suffix.lower() == ".xml" or fightclub.looks_like_fightclub(text):
        return fightclub.parse_actor(text)
    return json.loads(text)


def write_output(
    actor_path: Path,
    output_dir: Path,
    mode: str | None = None,
    theme: str | None = None,
    all_themes: bool = False,
    include_footer: bool = True,
    paper: str = "a4",
    system: str | None = None,
) -> list[Path]:
    actor = load_actor_file(actor_path)
    adapter = systems.detect_adapter(actor, forced=system)
    context = adapter.build_context(actor)
    sheet_id = slugify(actor.get("name", actor_path.stem))

    if all_themes:
        return [
            _render_one_theme(context, sheet_id, output_dir, name, dict(entry), mode, include_footer=include_footer, paper=paper, adapter=adapter)
            for name, entry in THEMES.items()
        ]

    if theme:
        # An explicitly requested theme must resolve; a bad name is a user error.
        resolved = resolve_theme_entry(theme)
    else:
        try:
            resolved = resolve_theme_entry(adapter.default_theme(actor))
        except ValueError:
            resolved = None
    if resolved is None:
        # No actor class, or one without a dedicated palette (homebrew classes
        # have no registered theme) → fall back to the neutral ledger layout.
        resolved = ("ledger", dict(THEMES["ledger"]))
    label, entry = resolved
    return [_render_one_theme(context, sheet_id, output_dir, label, entry, mode, include_footer=include_footer, paper=paper, adapter=adapter)]


def chromium_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return detect_print_browser()


def detect_print_browser(
    which: Any = shutil.which,
    exists: Any | None = None,
) -> str | None:
    exists = exists or (lambda path: path.exists())
    for candidate in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "msedge",
        "microsoft-edge",
        "brave-browser",
        "brave",
        "vivaldi",
        "vivaldi-stable",
        "helium",
    ):
        found = which(candidate)
        if found:
            return found
    # macOS app bundles. Each browser can live in the system-wide /Applications
    # or a per-user ~/Applications, so probe both. Chrome/Edge come first to match
    # the historical preference order; the rest are other Chromium-based browsers.
    mac_bundles = [
        "Google Chrome.app/Contents/MacOS/Google Chrome",
        "Chromium.app/Contents/MacOS/Chromium",
        "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "Brave Browser.app/Contents/MacOS/Brave Browser",
        "Vivaldi.app/Contents/MacOS/Vivaldi",
        "Helium.app/Contents/MacOS/Helium",
        "Arc.app/Contents/MacOS/Arc",
    ]
    mac_app_dirs = [Path("/Applications"), Path.home() / "Applications"]
    platform_paths = [
        app_dir / bundle for bundle in mac_bundles for app_dir in mac_app_dirs
    ]
    platform_paths += [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
        Path(r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for candidate in platform_paths:
        if exists(candidate):
            return str(candidate)
    return None


class PdfExportError(RuntimeError):
    """Raised when headless-browser PDF export fails or times out."""


def _log_tail(text: str | None, lines: int = 5) -> str:
    """Last few non-blank lines of a log, joined — for error messages."""
    relevant = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return " | ".join(relevant[-lines:])


# Headless browsers normally print within seconds; a hung browser must not
# wedge a caller (the web UI serves requests on threads).
PDF_EXPORT_TIMEOUT_SECONDS = 120


def render_pdf(html_path: Path, pdf_path: Path, browser: str, mode: str | None = None) -> None:
    target_uri = html_path.resolve().as_uri()
    if mode:
        target_uri += f"?theme={mode}"
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        # Kept for compatibility (root/container runs need it); the sheet is
        # self-contained, and file:// access stays locked down below.
        "--no-sandbox",
        "--virtual-time-budget=1500",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        target_uri,
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True,
                                timeout=PDF_EXPORT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        detail = _log_tail(stderr)
        raise PdfExportError(
            f"{Path(browser).name} did not finish printing within "
            f"{PDF_EXPORT_TIMEOUT_SECONDS}s." + (f" {detail}" if detail else "")
        ) from exc
    if result.returncode != 0:
        detail = _log_tail(result.stderr)
        raise PdfExportError(
            f"{Path(browser).name} exited with status {result.returncode} while printing."
            + (f" {detail}" if detail else "")
        )


def parse_theme_arg(value: str) -> str:
    name = value.strip()
    if name in THEMES or name in THEME_ALIASES:
        return name
    if HEX_COLOR_RE.match(name):
        return name if name.startswith("#") else f"#{name}"
    raise argparse.ArgumentTypeError(
        f"Unknown theme {value!r}. Choose one of: {', '.join(sorted(THEMES))} or a #RRGGBB hex."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actor_json", nargs="?", type=Path, help="Path to the exported Foundry actor JSON file (omit when using --serve)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="Where to write generated files")
    parser.add_argument("--mode", choices=list(MODE_CHOICES), help="Initial color mode for the generated HTML/PDF (light, dark, or mono)")
    parser.add_argument("--paper", choices=list(PAPER_PROFILES), default="a4", help="Print/PDF paper profile (default: a4)")
    parser.add_argument(
        "--theme",
        type=parse_theme_arg,
        metavar="NAME|HEX",
        help=(
            "Sheet theme. Names: " + ", ".join(sorted(THEMES))
            + ". Or a #RRGGBB hex (uses ledger baseline). Defaults to the actor's primary class."
        ),
    )
    parser.add_argument(
        "--system",
        choices=systems.known_ids(),
        default=None,
        help=(
            "Force the game system instead of auto-detecting it. "
            "Registered: " + ", ".join(systems.known_ids()) + ". Defaults to auto-detect."
        ),
    )
    parser.add_argument("--all-themes", action="store_true", help="Render one HTML per registered theme")
    parser.add_argument(
        "--to-fightclub",
        action="store_true",
        help="Convert the actor to a Lion's Den Fight Club 5e XML file (written to the output dir) instead of rendering a sheet",
    )
    parser.add_argument("--pdf", action="store_true", help="Also generate a PDF using local Chromium")
    parser.add_argument("--chromium", help="Explicit Chromium executable path")
    parser.add_argument("--print-browser", dest="chromium", help="Explicit Chromium-compatible browser path for PDF export")
    parser.add_argument("--no-footer", action="store_true", help="Do not include the attribution/disclaimer footer")
    parser.add_argument("--serve", action="store_true", help="Launch the local web UI in your browser instead of generating from the CLI")
    parser.add_argument("--port", type=int, default=8765, help="Port for --serve (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="With --serve, do not auto-open the browser")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    args = parser.parse_args()
    if not args.serve and args.actor_json is None:
        parser.error("actor_json is required (or pass --serve to launch the web UI)")
    return args


def main() -> int:
    args = parse_args()
    if args.serve:
        import webui
        return webui.run(port=args.port, output_dir=args.output_dir, open_browser=not args.no_browser)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.to_fightclub:
        try:
            actor = load_actor_file(args.actor_json)
        except fightclub.FightClubParseError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        xml_path = args.output_dir / f"{slugify(actor.get('name', args.actor_json.stem))}.xml"
        xml_path.write_text(fightclub.to_xml(actor), encoding="utf-8")
        print(f"Fight Club XML written to {xml_path}")
        return 0

    try:
        html_paths = write_output(
            args.actor_json,
            args.output_dir,
            mode=args.mode,
            theme=args.theme,
            all_themes=args.all_themes,
            include_footer=not args.no_footer,
            paper=args.paper,
            system=args.system,
        )
    except systems.UnsupportedSystemError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for path in html_paths:
        print(f"HTML written to {path}")

    if args.pdf:
        browser = chromium_path(args.chromium)
        if not browser:
            print("Chromium not found; HTML was generated but PDF was skipped.", file=sys.stderr)
            return 1
        for path in html_paths:
            pdf_path = path.with_suffix(".pdf")
            try:
                render_pdf(path, pdf_path, browser, mode=args.mode)
            except PdfExportError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            print(f"PDF written to {pdf_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
