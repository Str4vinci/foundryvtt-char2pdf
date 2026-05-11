#!/usr/bin/env python3
"""Render a Foundry VTT actor export to interactive HTML/PDF sheets.

Current support is focused on the dnd5e system and D&D 2024-style actor data.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


APP_VERSION = "0.1.0"
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
    return [item for item in actor.get("items", []) if item.get("type") == item_type]


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
        item for item in actor.get("items", [])
        if item.get("type") == "equipment" and item.get("system", {}).get("equipped")
    ]
    armor_items = [item for item in equipped if item.get("system", {}).get("type", {}).get("value") != "shield"]
    shield_bonus = sum(
        to_int(item.get("system", {}).get("armor", {}).get("value"))
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
        value = spells_data.get(key, {}).get("value", 0)
        if value:
            slots.append({"label": f"Level {level}", "value": int(value)})
    pact = spells_data.get("pact", {}).get("value", 0)
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


def collect_features(actor: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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
        entry = {
            "name": item.get("name", "Feature"),
            "uses": sys_data.get("uses", {}),
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
    return groups


def sheet_context(actor: dict[str, Any]) -> dict[str, Any]:
    system = actor.get("system", {})
    details = system.get("details", {})
    abilities = system.get("abilities", {})
    skills = system.get("skills", {})
    tools = system.get("tools", {})
    traits = system.get("traits", {})
    class_info = class_levels(actor)
    total_level = sum(entry["levels"] for entry in class_info)
    prof_bonus = proficiency_bonus(total_level)
    spell_ability_code = system.get("attributes", {}).get("spellcasting") or (class_info[0]["item"].get("system", {}).get("spellcasting", {}).get("ability") if class_info else "")

    race_item = next(iter(find_items(actor, "race")), None)
    background_item = next(iter(find_items(actor, "background")), None)
    subclass_item = next(iter(find_items(actor, "subclass")), None)
    class_item = class_info[0]["item"] if class_info else None
    armor_items = [item for item in actor.get("items", []) if item.get("type") in {"equipment", "weapon", "loot", "tool", "container"}]
    equipped_shields = [
        item for item in actor.get("items", [])
        if item.get("type") == "equipment"
        and item.get("system", {}).get("equipped")
        and item.get("system", {}).get("type", {}).get("value") == "shield"
    ]
    ability_rows = []
    saving_throw_rows = []

    for code in ABILITY_ORDER:
        score = to_int(abilities.get(code, {}).get("value"))
        mod = ability_mod(score)
        save_prof = to_number(abilities.get(code, {}).get("proficient"))
        save_bonus = mod + int(prof_bonus * save_prof) + to_int(abilities.get(code, {}).get("bonuses", {}).get("save"))
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
        skill = skills.get(code, {})
        ability_code = skill.get("ability") or default_ability
        mod = ability_mod(to_int(abilities.get(ability_code, {}).get("value")))
        multiplier = to_number(skill.get("value"))
        bonus = mod + int(prof_bonus * multiplier) + to_int(skill.get("bonuses", {}).get("check"))
        passive = 10 + bonus + to_int(skill.get("bonuses", {}).get("passive"))
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
    for item in actor.get("items", []):
        if item.get("type") != "weapon" or not item.get("system", {}).get("equipped"):
            continue
        ability_code = attack_ability_code(item)
        ability_bonus = ability_mod(to_int(abilities.get(ability_code, {}).get("value")))
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
    slot_defaults = spell_slot_defaults(system.get("spells", {}))

    spell_ability_mod = ability_mod(to_int(abilities.get(spell_ability_code, {}).get("value"))) if spell_ability_code else 0
    spell_dc = 8 + prof_bonus + spell_ability_mod if spell_ability_code else None
    spell_attack = prof_bonus + spell_ability_mod if spell_ability_code else None
    dex_mod = ability_mod(to_int(abilities.get("dex", {}).get("value")))
    init_bonus = dex_mod + to_int(system.get("attributes", {}).get("init", {}).get("bonus"))
    race_movement = race_item.get("system", {}).get("movement", {}).get("walk") if race_item else None
    senses = race_item.get("system", {}).get("senses", {}).get("ranges", {}) if race_item else {}
    hp = system.get("attributes", {}).get("hp", {})
    armor_class = derive_armor_class(actor, dex_mod)
    shield_bonus = sum(to_int(item.get("system", {}).get("armor", {}).get("value")) for item in equipped_shields)
    spellcast_label = ABILITY_LABELS.get(spell_ability_code, spell_ability_code.upper()) if spell_ability_code else "None"
    size_code = traits.get("size", "")
    size_label = {"tiny": "Tiny", "sm": "Small", "med": "Medium", "lg": "Large", "huge": "Huge", "grg": "Gargantuan"}.get(size_code, pretty_code(size_code) if size_code else "")
    hit_die_size = class_item.get("system", {}).get("hd", {}).get("denomination") if class_item else None
    hit_dice_spent = to_int(class_item.get("system", {}).get("hd", {}).get("spent")) if class_item else 0

    inventory = []
    containers = {item.get("_id"): item.get("name") for item in actor.get("items", []) if item.get("type") == "container"}
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
        "currency": format_currency(system.get("currency", {})),
        "inventory": inventory,
        "inventory_weight": total_weight(armor_items),
        "languages": [LANGUAGE_LABELS.get(code, pretty_code(code)) for code in traits.get("languages", {}).get("value", [])],
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
        "inspiration": bool(system.get("attributes", {}).get("inspiration")),
        "hit_dice_spent": hit_dice_spent,
        "hit_dice_total": total_level,
        "hit_die_size": hit_die_size,
        "currency_counts": coin_counts(system.get("currency", {})),
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


def render_badges(badges: list[str]) -> str:
    if not badges:
        return ""
    return '<div class="badges">' + "".join(f'<span class="badge">{esc(badge)}</span>' for badge in badges) + "</div>"


def render_stat_input(label: str, value: Any, key: str, kind: str = "number") -> str:
    value_attr = "checked" if kind == "checkbox" and value else f'value="{esc(value)}"'
    input_html = (
        f'<input class="tracker tracker-check" type="checkbox" data-persist="{esc(key)}" {value_attr}>'
        if kind == "checkbox"
        else f'<input class="tracker" type="{kind}" data-persist="{esc(key)}" value="{esc(value)}">'
    )
    return f'<label class="tracker-card"><span>{esc(label)}</span>{input_html}</label>'


def render_meta_tags(values: list[str]) -> str:
    values = [value for value in values if value]
    if not values:
        return ""
    return '<div class="meta-tags">' + "".join(f'<span class="meta-tag">{esc(value)}</span>' for value in values) + "</div>"


def render_use_tracker(uses: dict[str, Any], key_prefix: str) -> str:
    count = to_int(uses.get("max"))
    if count <= 0 or count > 8:
        return ""

    trackers = "".join(
        f'''
        <label class="pip">
          <input type="checkbox" data-persist="{esc(f"{key_prefix}-use-{index}")}">
          <span></span>
        </label>
        '''
        for index in range(1, count + 1)
    )
    recovery = format_recovery(uses)
    recovery_html = f'<div class="use-recovery">{esc(recovery)}</div>' if recovery else ""
    return f'''
    <div class="use-track">
      <div class="use-label">Uses</div>
      <div class="pip-row">{trackers}</div>
      {recovery_html}
    </div>
    '''


def render_cards(data: dict[str, Any], sheet_id: str) -> str:
    spell_cards = []
    for spell in data["active_spells"]:
        spell_key = slugify(f"{sheet_id}-{spell['name']}-spell-{spell['level']}")
        level_label = "Cantrip" if spell["level"] == 0 else f"Level {spell['level']}"
        footer = f"{data['name']} · {data['class_line']}"
        if data["spell_dc"] is not None and data["spell_attack"] is not None:
            footer += f" · DC {data['spell_dc']} / +{data['spell_attack']}"

        spell_cards.append(
            f'''
            <article class="ref-card spell-ref" data-kind="spell" data-search="{esc((spell['name'] + ' ' + spell['description'] + ' ' + spell['school']).lower())}">
              <div class="card-ribbon">
                <span>Spell</span>
                <span>{esc(level_label)}</span>
              </div>
              <h2>{esc(spell["name"])}</h2>
              <p class="card-subtitle">{esc(spell["school"])}</p>
              {render_badges(spell["badges"])}
              {render_meta_tags([spell["activation"], spell["range"], spell["duration"], spell["components"]])}
              <p class="card-copy">{esc(spell["summary"] or "No description available in the export.")}</p>
              {render_use_tracker(spell["uses"], spell_key)}
              <footer>{esc(footer)}</footer>
            </article>
            '''
        )

    feature_cards = []
    for group_name, entries in data["feature_groups"].items():
        for entry in entries:
            feature_key = slugify(f"{sheet_id}-{entry['name']}-feature")
            badges = []
            if entry["uses"].get("max"):
                badges.append(f"Uses: {entry['uses']['max']}")
            recovery = format_recovery(entry["uses"])
            if recovery:
                badges.append(recovery)

            footer_bits = [data["name"], group_name]
            if entry["activity_names"]:
                footer_bits.append(" / ".join(entry["activity_names"][:2]))

            feature_cards.append(
                f'''
                <article class="ref-card feature-ref" data-kind="feature" data-search="{esc((entry['name'] + ' ' + entry['full_description'] + ' ' + group_name).lower())}">
                  <div class="card-ribbon">
                    <span>{esc(group_name)}</span>
                    <span>Ability</span>
                  </div>
                  <h2>{esc(entry["name"])}</h2>
                  <p class="card-subtitle">{esc(entry["requirements"] or group_name)}</p>
                  {render_badges(badges)}
                  {render_meta_tags([
                      entry["activation"] if entry["activation"] != "Passive" else "",
                      entry["range"] if entry["activation"] != "Passive" else "",
                      entry["duration"] if entry["activation"] != "Passive" else "",
                  ])}
                  <p class="card-copy">{esc(entry["summary"] or entry["description"] or "Passive feature.")}</p>
                  {render_use_tracker(entry["uses"], feature_key)}
                  <footer>{esc(" · ".join(bit for bit in footer_bits if bit))}</footer>
                </article>
                '''
            )

    body = f"""
    <header class="cards-hero screen-only">
      <div>
        <p class="eyebrow">Foundry VTT -> Reference Deck</p>
        <h1>{esc(data["name"])}</h1>
        <p class="hero-line">{esc(data["class_line"])}{(' · ' + esc(data["subclass"])) if data["subclass"] else ''}</p>
        <p class="hero-line">{esc(data["species"] or 'Species not set')} · {esc(data["background"] or 'Background not set')}</p>
      </div>
      <div class="cards-actions">
        <button type="button" id="print-cards">Print / Save PDF</button>
        <button type="button" id="show-all" class="secondary">Show All</button>
      </div>
    </header>

    <section class="cards-toolbar screen-only">
      <input id="card-search" type="search" placeholder="Search spells or abilities">
      <div class="filter-group">
        <button type="button" class="filter-btn active" data-filter="all">All</button>
        <button type="button" class="filter-btn" data-filter="spell">Spells</button>
        <button type="button" class="filter-btn" data-filter="feature">Abilities</button>
      </div>
    </section>

    <section class="cards-summary screen-only">
      <div class="summary-pill">AC {esc(data["ac"])}</div>
      <div class="summary-pill">HP {esc(data["hp_value"])}</div>
      <div class="summary-pill">Prof {esc(signed(data["prof_bonus"]))}</div>
      <div class="summary-pill">Spell DC {esc(data["spell_dc"] if data["spell_dc"] is not None else "—")}</div>
      <div class="summary-pill">Spell Attack {esc(signed(data["spell_attack"]) if data["spell_attack"] is not None else "—")}</div>
    </section>

    <main class="card-grid">
      {''.join(spell_cards)}
      {''.join(feature_cards)}
    </main>
    """

    style = """
    :root {
      --paper: #f4ead6;
      --paper-dark: #eadbbf;
      --ink: #1f221e;
      --spell: #315847;
      --feature: #875b26;
      --line: rgba(31, 34, 30, 0.18);
      --shadow: 0 10px 24px rgba(31, 34, 30, 0.12);
      color-scheme: light;
      font-family: "Palatino Linotype", "Book Antiqua", "URW Palladio L", Georgia, serif;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(135, 91, 38, 0.18), transparent 25%),
        radial-gradient(circle at bottom right, rgba(49, 88, 71, 0.18), transparent 25%),
        linear-gradient(180deg, #fbf6ee 0%, #efe3cf 100%);
    }

    button,
    input,
    textarea {
      font: inherit;
    }

    .page {
      max-width: 1360px;
      margin: 0 auto;
      padding: 24px;
    }

    .cards-hero,
    .cards-toolbar,
    .summary-pill,
    .ref-card {
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255, 251, 244, 0.96), rgba(243, 232, 210, 0.98));
      box-shadow: var(--shadow);
    }

    .cards-hero {
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: start;
      border-radius: 24px;
      padding: 22px 24px;
      margin-bottom: 16px;
    }

    .eyebrow {
      margin: 0 0 6px;
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 0.72rem;
      color: var(--spell);
    }

    h1 {
      margin: 0;
      font-size: clamp(2rem, 4.5vw, 3.4rem);
      line-height: 0.96;
    }

    h2 {
      margin: 0;
      font-size: 1.18rem;
      line-height: 1.04;
    }

    .hero-line {
      margin: 8px 0 0;
      font-size: 0.98rem;
    }

    .cards-actions,
    .filter-group {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    button {
      appearance: none;
      border: 0;
      border-radius: 999px;
      padding: 11px 15px;
      font-weight: 700;
      background: var(--spell);
      color: white;
      cursor: pointer;
    }

    button.secondary,
    .filter-btn {
      background: rgba(31, 34, 30, 0.8);
    }

    .filter-btn.active {
      background: var(--feature);
    }

    .cards-toolbar {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 14px 16px;
      border-radius: 18px;
      margin-bottom: 14px;
    }

    #card-search {
      width: min(420px, 100%);
      border: 1px solid rgba(49, 88, 71, 0.24);
      border-radius: 999px;
      padding: 10px 14px;
      background: rgba(255, 255, 255, 0.78);
    }

    .cards-summary {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }

    .summary-pill {
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 0.86rem;
      color: rgba(31, 34, 30, 0.76);
    }

    .card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
      gap: 16px;
    }

    .ref-card {
      min-height: 336px;
      border-radius: 20px;
      padding: 14px 14px 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      break-inside: avoid;
    }

    .spell-ref {
      border-top: 6px solid var(--spell);
    }

    .feature-ref {
      border-top: 6px solid var(--feature);
    }

    .card-ribbon {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      font-size: 0.68rem;
      color: rgba(31, 34, 30, 0.74);
    }

    .card-subtitle {
      margin: -4px 0 0;
      color: rgba(31, 34, 30, 0.74);
      font-size: 0.88rem;
    }

    .badges,
    .meta-tags {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }

    .badges {
      justify-content: start;
    }

    .badge,
    .meta-tag {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 4px 8px;
      border: 1px solid rgba(31, 34, 30, 0.14);
      font-size: 0.72rem;
      line-height: 1.2;
      background: rgba(255, 255, 255, 0.62);
    }

    .card-copy {
      margin: 0;
      font-size: 0.88rem;
      line-height: 1.42;
      flex: 1;
    }

    .use-track {
      margin-top: auto;
      padding-top: 6px;
      border-top: 1px dashed rgba(31, 34, 30, 0.18);
    }

    .use-label,
    .use-recovery,
    footer {
      font-size: 0.72rem;
      color: rgba(31, 34, 30, 0.74);
    }

    .use-recovery {
      margin-top: 4px;
    }

    .pip-row {
      display: flex;
      gap: 6px;
      margin-top: 6px;
    }

    .pip input {
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }

    .pip span {
      display: inline-block;
      width: 18px;
      height: 18px;
      border-radius: 999px;
      border: 2px solid rgba(31, 34, 30, 0.32);
      background: rgba(255, 255, 255, 0.72);
    }

    .pip input:checked + span {
      background: linear-gradient(180deg, var(--spell), #213a30);
      border-color: var(--spell);
    }

    footer {
      margin-top: 4px;
      padding-top: 4px;
      border-top: 1px solid rgba(31, 34, 30, 0.1);
    }

    .is-hidden {
      display: none !important;
    }

    @media (max-width: 860px) {
      .page {
        padding: 16px;
      }

      .cards-hero,
      .cards-toolbar {
        flex-direction: column;
        align-items: stretch;
      }

      #card-search {
        width: 100%;
      }
    }

    @media print {
      @page {
        size: letter;
        margin: 0.22in;
      }

      body {
        background: white;
      }

      .page {
        max-width: none;
        padding: 0;
      }

      .screen-only {
        display: none !important;
      }

      .card-grid {
        grid-template-columns: repeat(3, 2.48in);
        justify-content: center;
        gap: 0.12in;
      }

      .ref-card {
        width: 2.48in;
        min-height: 3.46in;
        box-shadow: none;
        background: white;
        page-break-inside: avoid;
      }

      .card-copy {
        font-size: 0.76rem;
        line-height: 1.3;
      }

      .badge,
      .meta-tag,
      footer,
      .use-label,
      .use-recovery {
        font-size: 0.62rem;
      }

      .pip span {
        width: 14px;
        height: 14px;
      }
    }
    """

    script = """
    (() => {
      const storageKey = __STORAGE_KEY__;
      const state = JSON.parse(localStorage.getItem(storageKey) || "{}");
      const persistNodes = document.querySelectorAll("[data-persist]");
      const cards = Array.from(document.querySelectorAll(".ref-card"));
      const searchInput = document.getElementById("card-search");
      const filterButtons = Array.from(document.querySelectorAll(".filter-btn"));
      let filterKind = "all";

      for (const node of persistNodes) {
        const key = node.dataset.persist;
        if (Object.prototype.hasOwnProperty.call(state, key)) {
          if (node.type === "checkbox") {
            node.checked = Boolean(state[key]);
          } else {
            node.value = state[key];
          }
        }

        const save = () => {
          state[key] = node.type === "checkbox" ? node.checked : node.value;
          localStorage.setItem(storageKey, JSON.stringify(state));
        };

        node.addEventListener(node.type === "checkbox" ? "change" : "input", save);
      }

      const applyFilters = () => {
        const query = (searchInput?.value || "").trim().toLowerCase();
        for (const card of cards) {
          const kindMatch = filterKind === "all" || card.dataset.kind === filterKind;
          const queryMatch = !query || (card.dataset.search || "").includes(query);
          card.classList.toggle("is-hidden", !(kindMatch && queryMatch));
        }
      };

      for (const button of filterButtons) {
        button.addEventListener("click", () => {
          filterKind = button.dataset.filter || "all";
          for (const node of filterButtons) {
            node.classList.toggle("active", node === button);
          }
          applyFilters();
        });
      }

      searchInput?.addEventListener("input", applyFilters);
      document.getElementById("print-cards")?.addEventListener("click", () => window.print());
      document.getElementById("show-all")?.addEventListener("click", () => {
        filterKind = "all";
        if (searchInput) searchInput.value = "";
        for (const node of filterButtons) {
          node.classList.toggle("active", node.dataset.filter === "all");
        }
        applyFilters();
      });
      applyFilters();
    })();
    """.replace("__STORAGE_KEY__", json.dumps(f"foundry-cards:{sheet_id}"))

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(data["name"])} Reference Cards</title>
    <style>{style}</style>
  </head>
  <body>
    <div class="page">
      {body}
    </div>
    <script>{script}</script>
  </body>
</html>
"""


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


def render_v2_list(entries: list[dict[str, Any]], max_items: int = 10) -> str:
    if not entries:
        return ""
    rows = []
    for entry in entries[:max_items]:
        suffix = []
        if entry.get("uses", {}).get("max"):
            suffix.append(f"uses {entry['uses']['max']}")
        rows.append(
            f'<li>{render_reference_anchor(entry["name"])}'
            + (f' <span class="source-note">{" · ".join(suffix)}</span>' if suffix else "")
            + "</li>"
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


def ensure_official_sheet_assets(output_dir: Path, official_pdf: Path) -> tuple[str, str]:
    if not official_pdf.exists():
        raise FileNotFoundError(f"Official PDF not found: {official_pdf}")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm is required for the sheet-v2 layout")

    asset_dir = output_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    prefix = asset_dir / "dnd2024-sheet"
    page1 = asset_dir / "dnd2024-sheet-1.png"
    page2 = asset_dir / "dnd2024-sheet-2.png"

    if not page1.exists() or not page2.exists() or official_pdf.stat().st_mtime > min(page1.stat().st_mtime, page2.stat().st_mtime):
        subprocess.run(
            [pdftoppm, "-png", "-f", "1", "-l", "2", str(official_pdf), str(prefix)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    return ("assets/dnd2024-sheet-1.png", "assets/dnd2024-sheet-2.png")


def render_sheet_v2(data: dict[str, Any], sheet_id: str, backgrounds: tuple[str, str]) -> str:
    page1_bg, page2_bg = backgrounds
    skills_by_ability: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data["skill_rows"]:
        skills_by_ability[row["ability"].lower()].append(row)

    save_map = {row["label"].lower(): row for row in data["saving_throw_rows"]}
    ability_positions = {
        "str": "ability-str",
        "dex": "ability-dex",
        "con": "ability-con",
        "int": "ability-int",
        "wis": "ability-wis",
        "cha": "ability-cha",
    }
    ability_blocks = []
    for row in data["ability_rows"]:
        code = row["code"].lower()
        save_row = save_map.get(ABILITY_LABELS[code].lower(), {"bonus": "+0", "proficient": False})
        skill_rows = skills_by_ability.get(code, [])
        skill_list = "".join(
            f'<div class="ability-line"><span class="pip-mark">{"●" if skill["proficient"] else "○"}</span><span class="line-value">{esc(skill["bonus"])}</span></div>'
            for skill in skill_rows
        )
        ability_blocks.append(
            f'''
            <section class="ability-block {ability_positions[code]}">
              <div class="ability-mod">{esc(row["mod"])}</div>
              <div class="ability-score">{esc(row["score"])}</div>
              <div class="ability-line save-line"><span class="pip-mark">{"●" if save_row["proficient"] else "○"}</span><span class="line-value">{esc(save_row["bonus"])}</span></div>
              <div class="skill-list">{skill_list}</div>
            </section>
            '''
        )

    spells_by_level = {level: 0 for level in range(1, 10)}
    for slot in data["slot_defaults"]:
        match = re.search(r"(\d+)", slot["label"])
        if match:
            spells_by_level[int(match.group(1))] = to_int(slot["value"])

    slot_groups = []
    for levels in [(1, 2, 3), (4, 5, 6), (7, 8, 9)]:
        rows = []
        for level in levels:
            count = spells_by_level[level]
            rows.append(
                f'''
                <div class="slot-row">
                  <span class="slot-label">Level {level}</span>
                  <span class="slot-total">{count or ""}</span>
                  <span class="slot-pips">{render_tracker_pips(count, f"{sheet_id}-slot-l{level}")}</span>
                </div>
                '''
            )
        slot_groups.append(f'<div class="slot-group">{"".join(rows)}</div>')

    coin_inputs = "".join(
        render_v2_field(data["currency_counts"][coin], f"coin-{coin}", f"coin-{coin}", numeric=True)
        for coin in ["cp", "sp", "ep", "gp", "pp"]
    )

    species_entries = data["feature_groups"].get("Ancestry", [])
    class_entries = data["feature_groups"].get("Class Features", [])
    feat_entries = data["feature_groups"].get("Feats", [])
    backstory_text = "\n".join(
        section for section in [
            data["notes"]["traits"],
            data["notes"]["ideal"],
            data["notes"]["bond"],
            data["notes"]["flaw"],
            data["notes"]["biography"],
        ] if section
    )
    equipment_text = "\n".join(f"{item['quantity']}x {item['name']}" for item in data["inventory"])

    top_refs = []
    for key in ["background", "class", "subclass", "species"]:
        ref = data["top_references"].get(key, {})
        if ref.get("name"):
            top_refs.append(render_reference_anchor(ref["name"], ref.get("source", "")))

    body = f"""
    <div class="v2-toolbar screen-only">
      <div class="v2-toolbar-text">v2 faithful layout · {data["reference_counts"]["spells"]} spell refs · {data["reference_counts"]["features"]} feature refs</div>
      <div class="v2-toolbar-actions">
        <button type="button" id="print-v2">Print / Save PDF</button>
        <button type="button" id="reset-v2" class="secondary">Reset Trackers</button>
      </div>
    </div>

    <section class="v2-reference-line screen-only">{' · '.join(top_refs)}</section>

    <section class="v2-page v2-page-1" style="background-image:url('{esc(page1_bg)}')">
      {render_v2_field(data["name"], "v2-name", "field-name")}
      {render_v2_field(data["background"], "v2-background", "field-background")}
      {render_v2_field(data["class_line"], "v2-class", "field-class")}
      {render_v2_field(data["species"], "v2-species", "field-species")}
      {render_v2_field(data["subclass"], "v2-subclass", "field-subclass")}
      {render_v2_field(data["level"], "v2-level", "field-level", numeric=True)}
      {render_v2_field(data["xp"] or "", "v2-xp", "field-xp", numeric=True)}

      <div class="stat-display stat-ac">{esc(data["ac"])}</div>
      <div class="stat-display stat-shield">{esc(f"+{data['shield_bonus']}" if data['shield_bonus'] else "")}</div>
      {render_v2_field(data["hp_value"], "v2-hp-current", "stat-hp-current", numeric=True)}
      {render_v2_field(data["temp_hp"], "v2-hp-temp", "stat-hp-temp", numeric=True)}
      {render_v2_field(data["hp_max"], "v2-hp-max", "stat-hp-max", numeric=True)}
      {render_v2_field(data["hit_dice_spent"], "v2-hitdice-spent", "stat-hitdice-spent", numeric=True)}
      <div class="stat-display stat-hitdice-max">{esc(f"{data['hit_dice_total']}d{str(data['hit_die_size']).lstrip('dD')}" if data['hit_die_size'] else data['hit_dice_total'])}</div>

      <div class="tracker-line death-saves-success">{render_tracker_pips(3, f"{sheet_id}-death-success", "diamond")}</div>
      <div class="tracker-line death-saves-failure">{render_tracker_pips(3, f"{sheet_id}-death-failure", "diamond")}</div>

      <div class="stat-display stat-prof">{esc(signed(data["prof_bonus"]))}</div>
      <div class="stat-display stat-init">{esc(signed(data["initiative"]))}</div>
      <div class="stat-display stat-speed">{esc(data["speed"])} ft</div>
      <div class="stat-display stat-size">{esc(data["size"])}</div>
      <div class="stat-display stat-passive">{esc(data["passive_perception"])}</div>
      <label class="inspiration-toggle"><input type="checkbox" data-persist="{esc(f"{sheet_id}-heroic-inspiration")}" {"checked" if data["inspiration"] else ""}><span></span></label>

      {''.join(ability_blocks)}

      <section class="weapons-table">
        <table>
          <tbody>{render_v2_attack_rows(data["attacks"])}</tbody>
        </table>
      </section>

      <section class="feature-box class-features">{render_v2_list(class_entries, 10)}</section>
      <section class="feature-box species-traits">{render_v2_list(species_entries, 8)}</section>
      <section class="feature-box feats-list">{render_v2_list(feat_entries, 8)}</section>

      <section class="proficiency-box">
        <div class="armor-train">
          {''.join(
              f'<span class="train-mark {"trained" if label in data["proficiencies"] else ""}">{esc(label)}</span>'
              for label in ["Light Armor", "Medium Armor", "Heavy Armor", "Shields"]
          )}
        </div>
        <div class="weapon-profs">{esc(", ".join([prof for prof in data["proficiencies"] if "Weapon" in prof]) or "None")}</div>
        <div class="tool-profs">{esc(", ".join(row["label"] for row in data["tool_rows"]) or "None")}</div>
      </section>
    </section>

    <section class="v2-page v2-page-2" style="background-image:url('{esc(page2_bg)}')">
      <div class="spell-stat spell-ability">{esc(data["spell_ability"])}</div>
      <div class="spell-stat spell-mod">{esc(signed(data["spell_mod"]))}</div>
      <div class="spell-stat spell-dc">{esc(data["spell_dc"] if data["spell_dc"] is not None else "—")}</div>
      <div class="spell-stat spell-attack">{esc(signed(data["spell_attack"]) if data["spell_attack"] is not None else "—")}</div>

      <section class="slot-box">{''.join(slot_groups)}</section>

      <section class="spell-table">
        <table>
          <tbody>{render_v2_spell_rows(data["active_spells"])}</tbody>
        </table>
      </section>

      {render_v2_field(data["notes"]["appearance"], "v2-appearance", "appearance-box", multiline=True)}
      {render_v2_field(backstory_text, "v2-backstory", "backstory-box", multiline=True)}
      {render_v2_field(", ".join(data["languages"]), "v2-languages", "languages-box", multiline=True)}
      {render_v2_field(equipment_text, "v2-equipment", "equipment-box", multiline=True)}

      <section class="coin-box">{coin_inputs}</section>
    </section>
    """

    style = """
    :root {
      --ink: #2a2a2a;
      --line: rgba(0, 0, 0, 0.14);
      --accent: #111;
      color-scheme: light;
      font-family: "Trebuchet MS", "Avenir Next", "Gill Sans", sans-serif;
    }

    * { box-sizing: border-box; }
    body { margin: 0; background: #f4efe7; color: var(--ink); }
    a { color: inherit; }

    .page-wrap {
      max-width: 980px;
      margin: 0 auto;
      padding: 18px;
    }

    .v2-toolbar,
    .v2-reference-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      padding: 10px 14px;
      border-radius: 14px;
      border: 1px solid rgba(0,0,0,0.08);
      background: rgba(255,255,255,0.82);
    }

    .v2-toolbar-actions { display: flex; gap: 8px; }
    .v2-toolbar-text,
    .v2-reference-line,
    .source-note { font-size: 0.74rem; color: rgba(0,0,0,0.66); }
    .v2-reference-line { justify-content: flex-start; flex-wrap: wrap; }

    button {
      appearance: none;
      border: 0;
      border-radius: 999px;
      padding: 10px 14px;
      font: inherit;
      font-weight: 700;
      background: #222;
      color: white;
      cursor: pointer;
    }
    button.secondary { background: #666; }

    .v2-page {
      position: relative;
      container-type: inline-size;
      width: 100%;
      max-width: 960px;
      aspect-ratio: 603 / 774;
      margin: 0 auto 18px;
      background-size: 100% 100%;
      background-repeat: no-repeat;
      box-shadow: 0 10px 28px rgba(0,0,0,0.12);
      page-break-after: always;
      overflow: hidden;
    }

    .v2-page:last-child { page-break-after: auto; }

    .v2-field,
    .stat-display,
    .spell-stat {
      position: absolute;
      border: 0;
      background: transparent;
      color: #111;
      font: inherit;
      padding: 0;
      margin: 0;
      line-height: 1;
    }

    .v2-field {
      outline: none;
      appearance: none;
      -webkit-appearance: none;
      -moz-appearance: textfield;
      border-radius: 0;
      text-transform: none;
    }

    .v2-field::-webkit-outer-spin-button,
    .v2-field::-webkit-inner-spin-button {
      -webkit-appearance: none;
      margin: 0;
    }

    textarea.v2-field {
      resize: none;
      line-height: 1.32;
    }

    .field-name { left: 4.2%; top: 4.6%; width: 37.3%; font-size: 0.98cqw; font-weight: 700; letter-spacing: 0.01em; }
    .field-background { left: 4.2%; top: 7.55%; width: 19.2%; font-size: 0.80cqw; }
    .field-class { left: 24.0%; top: 7.55%; width: 16.4%; font-size: 0.80cqw; }
    .field-species { left: 4.2%; top: 10.45%; width: 19.2%; font-size: 0.76cqw; }
    .field-subclass { left: 24.0%; top: 10.45%; width: 16.4%; font-size: 0.76cqw; }
    .field-level { left: 44.85%; top: 5.65%; width: 5.9%; text-align: center; font-size: 1.08cqw; font-weight: 700; }
    .field-xp { left: 45.0%; top: 8.55%; width: 5.6%; text-align: center; font-size: 0.80cqw; }

    .stat-ac { left: 54.6%; top: 3.5%; width: 4.0%; text-align: center; font-size: 1.55cqw; font-weight: 700; }
    .stat-shield { left: 55.5%; top: 8.0%; width: 2.2%; text-align: center; font-size: 0.88cqw; }
    .stat-hp-current { left: 66.4%; top: 9.1%; width: 7.8%; text-align: center; font-size: 1.02cqw; }
    .stat-hp-temp { left: 75.1%; top: 5.95%; width: 7.8%; text-align: center; font-size: 0.94cqw; }
    .stat-hp-max { left: 75.1%; top: 9.1%; width: 7.8%; text-align: center; font-size: 0.94cqw; }
    .stat-hitdice-spent { left: 86.1%; top: 5.95%; width: 4.8%; text-align: center; font-size: 0.90cqw; }
    .stat-hitdice-max { left: 86.0%; top: 9.1%; width: 5.0%; text-align: center; font-size: 0.84cqw; }

    .death-saves-success { left: 93.25%; top: 4.45%; }
    .death-saves-failure { left: 93.25%; top: 7.35%; }
    .tracker-line { position: absolute; display: flex; gap: 0.30cqw; }

    .stat-prof { left: 9.2%; top: 17.7%; width: 4.8%; text-align: center; font-size: 1.55cqw; font-weight: 700; }
    .stat-init { left: 42.2%; top: 16.9%; width: 6.0%; text-align: center; font-size: 1.36cqw; font-weight: 700; }
    .stat-speed { left: 58.3%; top: 16.9%; width: 6.0%; text-align: center; font-size: 1.28cqw; font-weight: 700; }
    .stat-size { left: 74.5%; top: 16.9%; width: 6.0%; text-align: center; font-size: 1.14cqw; font-weight: 700; }
    .stat-passive { left: 89.0%; top: 16.9%; width: 6.4%; text-align: center; font-size: 1.16cqw; font-weight: 700; }

    .inspiration-toggle {
      position: absolute;
      left: 6.1%;
      top: 74.8%;
      width: 8.2%;
      height: 6.0%;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .inspiration-toggle input { position: absolute; opacity: 0; }
    .inspiration-toggle span {
      display: block;
      width: 2.1cqw;
      height: 2.1cqw;
      border: 0.14cqw solid rgba(0,0,0,0.5);
      border-radius: 50%;
      background: rgba(255,255,255,0.5);
    }
    .inspiration-toggle input:checked + span { background: #111; box-shadow: inset 0 0 0 0.45cqw #fff; }

    .ability-block {
      position: absolute;
      font-size: 0.88cqw;
    }
    .ability-mod {
      position: absolute;
      left: 14%;
      top: 16%;
      width: 32%;
      text-align: center;
      font-size: 1.55cqw;
      font-weight: 700;
    }
    .ability-score {
      position: absolute;
      left: 55%;
      top: 31%;
      width: 18%;
      text-align: center;
      font-size: 1.00cqw;
      font-weight: 700;
    }
    .save-line { top: 55%; }
    .skill-list { position: absolute; left: 6%; right: 8%; top: 68%; display: grid; gap: 0.34cqw; }
    .ability-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      align-items: center;
      white-space: nowrap;
    }
    .pip-mark { font-size: 0.92cqw; }
    .line-value { font-weight: 700; }
    .ability-str { left: 1.7%; top: 24.7%; width: 15.6%; height: 14.6%; }
    .ability-dex { left: 1.7%; top: 39.8%; width: 15.6%; height: 17.7%; }
    .ability-con { left: 1.7%; top: 59.3%; width: 15.6%; height: 11.8%; }
    .ability-int { left: 19.1%; top: 14.8%; width: 15.7%; height: 21.1%; }
    .ability-wis { left: 19.1%; top: 36.9%; width: 15.7%; height: 21.0%; }
    .ability-cha { left: 19.1%; top: 59.3%; width: 15.7%; height: 20.5%; }

    .weapons-table, .spell-table {
      position: absolute;
      overflow: hidden;
    }
    .weapons-table { left: 37.1%; top: 26.2%; width: 60.6%; height: 13.9%; }
    .spell-table { left: 2.9%; top: 22.0%; width: 61.2%; height: 75.0%; }
    .weapons-table table, .spell-table table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.66cqw;
      table-layout: fixed;
    }
    .weapons-table td, .spell-table td {
      padding: 0.24cqw 0.30cqw;
      vertical-align: top;
      border-bottom: 0.08cqw solid rgba(0,0,0,0.12);
      height: 2.2cqw;
      line-height: 1.18;
    }
    .weapons-table td:nth-child(1) { width: 29%; }
    .weapons-table td:nth-child(2) { width: 13%; }
    .weapons-table td:nth-child(3) { width: 21%; }
    .weapons-table td:nth-child(4) { width: 37%; }
    .spell-table td:nth-child(1) { width: 6%; text-align: center; }
    .spell-table td:nth-child(2) { width: 30%; }
    .spell-table td:nth-child(3) { width: 10%; }
    .spell-table td:nth-child(4) { width: 12%; }
    .spell-table td:nth-child(5) { width: 18%; text-align: center; letter-spacing: 0.18cqw; }
    .spell-table td:nth-child(6) { width: 24%; }
    .crm { font-weight: 700; }

    .feature-box, .proficiency-box, .slot-box, .coin-box {
      position: absolute;
      overflow: hidden;
    }
    .feature-box ul {
      margin: 0;
      padding: 0.4cqw 0.8cqw 0.4cqw 1.3cqw;
      font-size: 0.74cqw;
      line-height: 1.28;
    }
    .feature-box li { margin-bottom: 0.18cqw; break-inside: avoid; }
    .class-features { left: 37.1%; top: 46.0%; width: 60.5%; height: 24.6%; }
    .species-traits { left: 37.2%; top: 77.0%; width: 28.8%; height: 19.3%; }
    .feats-list { left: 67.8%; top: 77.0%; width: 29.5%; height: 19.3%; }
    .class-features ul { columns: 2; column-gap: 1.3cqw; }
    .species-traits ul, .feats-list ul { font-size: 0.72cqw; }

    .proficiency-box { left: 2.0%; top: 83.9%; width: 32.4%; height: 14.8%; padding: 2.4cqw 1.0cqw 0.6cqw; }
    .armor-train {
      display: flex;
      gap: 0.7cqw;
      flex-wrap: wrap;
      font-size: 0.86cqw;
      margin-bottom: 1.0cqw;
    }
    .train-mark::before {
      content: "◇ ";
      font-weight: 700;
    }
    .train-mark.trained::before { content: "◆ "; }
    .weapon-profs, .tool-profs {
      font-size: 0.80cqw;
      line-height: 1.3;
      min-height: 2.4cqw;
      padding-top: 0.4cqw;
    }
    .tool-profs { margin-top: 4.8cqw; }

    .spell-stat {
      font-size: 1.05cqw;
      font-weight: 700;
      text-align: center;
    }
    .spell-ability { left: 4.1%; top: 4.7%; width: 14.5%; }
    .spell-mod { left: 8.3%; top: 7.5%; width: 8.7%; font-size: 1.45cqw; }
    .spell-dc { left: 8.3%; top: 11.4%; width: 8.7%; font-size: 1.45cqw; }
    .spell-attack { left: 8.3%; top: 15.3%; width: 8.7%; font-size: 1.40cqw; }

    .slot-box { left: 25.4%; top: 9.5%; width: 39.2%; height: 6.8%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 0 0.8cqw; padding: 0.2cqw 0.4cqw; }
    .slot-group { display: grid; gap: 0.28cqw; }
    .slot-row {
      display: grid;
      grid-template-columns: 3.4cqw 1.2cqw 1fr;
      align-items: center;
      gap: 0.2cqw;
      font-size: 0.72cqw;
      line-height: 1;
    }
    .slot-pips { display: flex; gap: 0.15cqw; flex-wrap: wrap; }
    .slot-total { text-align: center; font-weight: 700; }
    .slot-pip {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 0.95cqw;
      height: 0.95cqw;
    }
    .slot-pip input { position: absolute; opacity: 0; }
    .slot-pip span {
      display: block;
      width: 0.70cqw;
      height: 0.70cqw;
      border: 0.11cqw solid rgba(0,0,0,0.72);
      background: rgba(255,255,255,0.72);
      transform: rotate(45deg);
    }
    .slot-pip input:checked + span { background: #111; }
    .no-pips { color: rgba(0,0,0,0.35); }

    .appearance-box { left: 68.3%; top: 4.1%; width: 28.3%; height: 8.6%; font-size: 0.86cqw; }
    .backstory-box { left: 68.2%; top: 18.2%; width: 28.5%; height: 20.2%; font-size: 0.84cqw; }
    .languages-box { left: 68.5%; top: 44.5%; width: 27.9%; height: 3.4%; font-size: 0.86cqw; }
    .equipment-box { left: 68.4%; top: 54.4%; width: 28.1%; height: 30.5%; font-size: 0.82cqw; }

    .coin-box {
      left: 68.6%;
      top: 92.2%;
      width: 28.0%;
      height: 4.6%;
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 0.7cqw;
    }
    .coin-box .v2-field {
      position: static;
      width: 100%;
      text-align: center;
      font-size: 0.98cqw;
      font-weight: 700;
    }

    .ref-anchor { text-decoration: none; color: inherit; }
    @media screen {
      .ref-anchor:hover { text-decoration: underline; text-underline-offset: 0.12em; }
    }

    @media print {
      @page {
        size: 603pt 774pt;
        margin: 0;
      }

      body { background: white; }
      .page-wrap { max-width: none; padding: 0; }
      .screen-only { display: none !important; }
      .v2-page {
        width: 603pt;
        max-width: none;
        margin: 0;
        box-shadow: none;
      }
    }
    """

    script = """
    (() => {
      const storageKey = "__STORAGE_KEY__";
      const state = JSON.parse(localStorage.getItem(storageKey) || "{}");
      const persistNodes = document.querySelectorAll("[data-persist]");

      for (const node of persistNodes) {
        const key = node.dataset.persist;
        if (Object.prototype.hasOwnProperty.call(state, key)) {
          if (node.type === "checkbox") {
            node.checked = Boolean(state[key]);
          } else {
            node.value = state[key];
          }
        }

        const save = () => {
          state[key] = node.type === "checkbox" ? node.checked : node.value;
          localStorage.setItem(storageKey, JSON.stringify(state));
        };

        node.addEventListener(node.type === "checkbox" ? "change" : "input", save);
      }

      document.getElementById("print-v2")?.addEventListener("click", () => window.print());
      document.getElementById("reset-v2")?.addEventListener("click", () => {
        localStorage.removeItem(storageKey);
        window.location.reload();
      });
    })();
    """.replace("__STORAGE_KEY__", json.dumps(f"foundry-sheet-v2:{sheet_id}"))

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(data["name"])} Character Sheet v2</title>
    <style>{style}</style>
  </head>
  <body>
    <div class="page-wrap">
      {body}
    </div>
    <script>{script}</script>
  </body>
</html>
"""


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


def normalize_hex_color(value: str) -> str:
    if not HEX_COLOR_RE.match(value):
        raise argparse.ArgumentTypeError(f"Expected a 6-digit hex color (e.g. #2A50A1), got {value!r}")
    return value if value.startswith("#") else f"#{value}"


def _class_theme_entry(accent: str, base: str = "ledger") -> dict:
    dark = mix_hex(accent, "#f5ecd7", 0.45)
    return {
        "base": base,
        "decoration": None,
        "light_accent":        accent,
        "light_accent_strong": accent,
        "dark_accent":         dark,
        "dark_accent_strong":  dark,
    }


THEMES: dict[str, dict] = {
    # Layout-flavored themes — typography + ornaments come from base layout, no extra decoration
    "ledger":   {"base": "ledger",   "decoration": None,
                 "light_accent": "#7a1518", "light_accent_strong": "#7a1518",
                 "dark_accent":  "#f39c7e", "dark_accent_strong":  "#f39c7e"},
    "gazette":  {"base": "gazette",  "decoration": None,
                 "light_accent": "#18150f", "light_accent_strong": "#8a6c2d",
                 "dark_accent":  "#e7d3a3", "dark_accent_strong":  "#c7a558"},
    "grimoire": {"base": "grimoire", "decoration": None,
                 "light_accent": "#6d1a1a", "light_accent_strong": "#9e7a2b",
                 "dark_accent":  "#e9c26a", "dark_accent_strong":  "#c79a3a"},
    # Curated palette themes — ledger baseline + bespoke typography overlay + body decoration
    "dracula":    {"base": "ledger", "decoration": "dracula",
                   "light_accent": "#bd4f99", "light_accent_strong": "#7d4cc6",
                   "dark_accent":  "#ff79c6", "dark_accent_strong":  "#8be9fd"},
    "catppuccin": {"base": "ledger", "decoration": "catppuccin",
                   "light_accent": "#8839ef", "light_accent_strong": "#1e66f5",
                   "dark_accent":  "#cba6f7", "dark_accent_strong":  "#89b4fa"},
    "nord":       {"base": "ledger", "decoration": "nord",
                   "light_accent": "#5e81ac", "light_accent_strong": "#88c0d0",
                   "dark_accent":  "#88c0d0", "dark_accent_strong":  "#81a1c1"},
    "hearth":     {"base": "ledger", "decoration": "hearth",
                   "light_accent": "#cc785c", "light_accent_strong": "#915641",
                   "dark_accent":  "#e8a487", "dark_accent_strong":  "#d4836a"},
    # Class themes — ledger baseline + class accent
    **{name: _class_theme_entry(accent) for name, accent in CLASS_THEME_COLORS.items()},
}


def resolve_theme_entry(theme: str | None) -> tuple[str, dict] | None:
    """Resolve theme name (class, curated, layout, or hex) → (label, entry). Returns None if no theme."""
    if not theme:
        return None
    if theme in THEMES:
        return theme, dict(THEMES[theme])
    if HEX_COLOR_RE.match(theme):
        normalized = theme if theme.startswith("#") else f"#{theme}"
        return normalized, _class_theme_entry(normalized)
    raise ValueError(f"Unknown theme {theme!r}")


_SHEET_STYLE_LEDGER = r"""
    :root {
      --ink: #14161a;
      --ink-soft: #4a4f57;
      --rule: #1a1c22;
      --rule-soft: rgba(20, 22, 26, 0.16);
      --paper: #ffffff;
      --tint: #f4f1ec;
      --accent: #7a1518;
      --serif: "Source Serif 4", "Source Serif Pro", "Georgia", "Times New Roman", serif;
      --sans: "Inter", "Helvetica Neue", Arial, sans-serif;
      --mono: "IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace;
      color-scheme: light;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--serif); font-size: 15px; line-height: 1.52; -webkit-font-smoothing: antialiased; }
    a { color: var(--accent); text-decoration: none; border-bottom: 1px solid transparent; }
    a:hover { border-bottom-color: currentColor; }
    .page { max-width: 1120px; margin: 0 auto; padding: 56px 64px 96px; }
    .hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 32px; padding: 0 0 18px; margin: 0 0 28px; border-bottom: 2px solid var(--rule); }
    .hero > div:first-child { flex: 1; min-width: 0; }
    .eyebrow { margin: 0 0 10px; font-family: var(--sans); font-size: 11px; letter-spacing: 0.28em; text-transform: uppercase; color: var(--ink-soft); }
    h1 { margin: 0; font-size: 56px; line-height: 0.96; letter-spacing: -0.01em; font-weight: 700; }
    .hero-line { margin: 10px 0 0; font-size: 15px; color: var(--ink-soft); font-style: italic; }
    .hero-actions { display: flex; gap: 8px; align-self: flex-start; margin-top: 4px; }
    button { appearance: none; border: 1px solid var(--ink); background: var(--paper); color: var(--ink); font: 600 12px/1 var(--sans); letter-spacing: 0.14em; text-transform: uppercase; padding: 9px 14px; cursor: pointer; }
    button:hover { background: var(--ink); color: var(--paper); }
    button.secondary { border-color: var(--ink-soft); color: var(--ink-soft); }
    button.secondary:hover { background: var(--ink-soft); color: var(--paper); border-color: var(--ink-soft); }
    h2 { font-family: var(--sans); font-size: 10.5px; font-weight: 700; letter-spacing: 0.32em; text-transform: uppercase; color: var(--ink); margin: 0 0 14px; padding-bottom: 6px; border-bottom: 1px solid var(--rule); }
    h3 { font-family: var(--sans); font-size: 10px; font-weight: 700; letter-spacing: 0.26em; text-transform: uppercase; color: var(--ink-soft); margin: 22px 0 10px; }
    .summary-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; margin-bottom: 32px; border-top: 1px solid var(--rule-soft); border-bottom: 1px solid var(--rule-soft); }
    .summary-card { padding: 14px 18px; border-right: 1px solid var(--rule-soft); display: flex; flex-direction: column; gap: 6px; background: var(--paper); }
    .summary-card:last-child { border-right: 0; }
    .summary-card span { font-family: var(--sans); font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); }
    .summary-card strong { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
    .sheet-grid { display: grid; grid-template-columns: 1.22fr 1fr; gap: 40px; }
    .panel { padding: 0; margin-bottom: 36px; break-inside: avoid; }
    .split-panel { display: grid; grid-template-columns: 1fr 1.3fr; gap: 36px; }
    .abilities-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .ability-card { padding: 14px 6px; text-align: center; border-right: 1px solid var(--rule-soft); display: flex; flex-direction: column; gap: 2px; }
    .ability-card:last-child { border-right: 0; }
    .ability-code { font-family: var(--sans); font-size: 10px; font-weight: 700; letter-spacing: 0.24em; color: var(--ink-soft); }
    .ability-mod { font-family: var(--serif); font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .ability-score { font-family: var(--mono); font-size: 11px; color: var(--ink-soft); }
    .ability-label { font-family: var(--sans); font-size: 9.5px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-soft); }
    .trackers-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; border-top: 1px solid var(--rule-soft); border-bottom: 1px solid var(--rule-soft); }
    .tracker-card { padding: 10px 12px; border-right: 1px solid var(--rule-soft); display: flex; flex-direction: column; gap: 4px; }
    .tracker-card:last-child { border-right: 0; }
    .tracker-card span { font-family: var(--sans); font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); }
    .tracker { appearance: none; width: 100%; border: 0; background: transparent; font: 700 20px/1.2 var(--serif); color: var(--ink); padding: 0; font-variant-numeric: tabular-nums; outline: none; }
    .tracker-check { width: 16px; height: 16px; accent-color: var(--accent); align-self: flex-start; }
    .mini-note { margin: 12px 0 0; font-size: 12.5px; color: var(--ink-soft); font-style: italic; }
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; font-variant-numeric: tabular-nums; }
    th, td { text-align: left; padding: 5px 8px 5px 0; border-bottom: 1px solid var(--rule-soft); vertical-align: baseline; }
    th { font-family: var(--sans); font-size: 10px; font-weight: 700; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); padding-bottom: 7px; }
    td:last-child, th:last-child { text-align: right; }
    .stack { display: flex; flex-direction: column; }
    .list-card, .spell-card, .feature-card, .library-block { display: block; padding: 10px 0 12px; border-bottom: 1px solid var(--rule-soft); }
    .list-card:last-child, .spell-card:last-child, .feature-card:last-child, .library-block:last-child { border-bottom: 0; }
    .list-head, summary { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; cursor: pointer; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    .list-head strong, summary strong { font-size: 15.5px; font-weight: 700; letter-spacing: 0.01em; }
    .list-head span:last-child { font-family: var(--sans); font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; }
    summary small { font-family: var(--sans); font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-soft); margin-left: 10px; }
    .list-meta, .spell-meta { font-family: var(--sans); font-size: 11.5px; color: var(--ink-soft); margin: 3px 0 5px; letter-spacing: 0.02em; }
    .spell-card p, .feature-card p, .list-card p, .library-block p { margin: 6px 0 0; font-size: 13.5px; color: var(--ink); }
    .badges { display: inline-flex; gap: 6px; flex-wrap: wrap; }
    .badge { font-family: var(--sans); font-size: 9.5px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-soft); padding: 2px 7px; border: 1px solid var(--rule-soft); white-space: nowrap; }
    textarea { display: block; width: 100%; min-height: 72px; border: 0; border-bottom: 1px solid var(--rule-soft); padding: 6px 0; font: inherit; font-size: 13.5px; color: var(--ink); background: transparent; resize: vertical; outline: none; font-family: var(--serif); }
    textarea:focus { border-bottom-color: var(--ink); }
    .notes-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px 28px; }
    .notes-card { display: flex; flex-direction: column; gap: 4px; }
    .notes-card span { font-family: var(--sans); font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); }
    .muted { color: var(--ink-soft); }
    @media (max-width: 960px) {
      .page { padding: 32px 20px; }
      .hero { flex-direction: column; align-items: stretch; }
      .sheet-grid, .split-panel, .notes-grid { grid-template-columns: 1fr; gap: 20px; }
      .summary-grid { grid-template-columns: repeat(3, 1fr); }
      .summary-card:nth-child(3n) { border-right: 0; }
      .abilities-grid { grid-template-columns: repeat(3, 1fr); }
      .ability-card:nth-child(3n) { border-right: 0; }
      h1 { font-size: 40px; }
    }
    @media print {
      @page { size: A4; margin: 14mm; }
      .page { padding: 0; max-width: none; }
      .hero-actions, .screen-only { display: none !important; }
      .panel, .ability-card, .summary-card, .spell-card, .feature-card, .list-card, .library-block, .tracker-card, .notes-card { break-inside: avoid; }
      .spell-card p, .feature-card p, .spell-meta { display: none !important; }
    }
"""


_SHEET_STYLE_GAZETTE = r"""
    :root {
      --paper: #f6f1e4;
      --paper-edge: #ede5d1;
      --ink: #18150f;
      --ink-soft: #5a5447;
      --rule: #18150f;
      --rule-soft: rgba(24, 21, 15, 0.22);
      --accent: #18150f;
      --serif: "EB Garamond", "Libre Caslon Text", "Old Standard TT", "Times New Roman", serif;
      --display: "Playfair Display", "EB Garamond", "Times New Roman", serif;
      --sans: "Source Sans 3", "Helvetica Neue", Arial, sans-serif;
      color-scheme: light;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; background: var(--paper); color: var(--ink); font-family: var(--serif); font-size: 15.5px; line-height: 1.48; }
    body { background-image: radial-gradient(circle at 30% 20%, rgba(0,0,0,0.015), transparent 40%), radial-gradient(circle at 80% 80%, rgba(0,0,0,0.02), transparent 50%); }
    a { color: var(--ink); text-decoration: underline; text-decoration-thickness: 0.5px; text-underline-offset: 2px; }
    a:hover { text-decoration-thickness: 1px; }
    .page { max-width: 1180px; margin: 0 auto; padding: 44px 52px 72px; border-left: 1px solid var(--rule-soft); border-right: 1px solid var(--rule-soft); background: var(--paper); min-height: 100vh; }
    .hero { text-align: center; padding: 10px 0 22px; border-top: 3px double var(--rule); border-bottom: 3px double var(--rule); margin-bottom: 28px; position: relative; }
    .hero > div:first-child { display: flex; flex-direction: column; align-items: center; }
    .eyebrow { margin: 0 0 4px; font-family: var(--sans); font-size: 10.5px; letter-spacing: 0.36em; text-transform: uppercase; color: var(--ink-soft); }
    h1 { margin: 0; font-family: var(--display); font-size: 78px; line-height: 0.94; letter-spacing: -0.015em; font-weight: 900; }
    .hero-line { margin: 6px 0 0; font-family: var(--serif); font-size: 16px; font-style: italic; color: var(--ink); }
    .hero-line + .hero-line { font-size: 13.5px; color: var(--ink-soft); letter-spacing: 0.06em; }
    .hero-actions { position: absolute; top: 12px; right: 0; display: flex; gap: 6px; }
    button { appearance: none; background: transparent; border: 1px solid var(--ink); padding: 6px 11px; font: 600 10.5px/1 var(--sans); letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink); cursor: pointer; }
    button:hover { background: var(--ink); color: var(--paper); }
    button.secondary { opacity: 0.7; }
    h2 { font-family: var(--display); font-size: 14px; font-weight: 700; letter-spacing: 0.32em; text-transform: uppercase; text-align: center; margin: 0 0 12px; padding: 6px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    h3 { font-family: var(--display); font-size: 11.5px; font-weight: 700; letter-spacing: 0.24em; text-transform: uppercase; margin: 22px 0 8px; padding-bottom: 4px; border-bottom: 1px dashed var(--rule-soft); }
    .summary-grid { display: flex; flex-wrap: wrap; justify-content: center; align-items: baseline; gap: 0; margin-bottom: 26px; padding: 8px 0; border-bottom: 1px solid var(--rule); font-family: var(--display); }
    .summary-card { padding: 4px 22px; display: inline-flex; flex-direction: row; align-items: baseline; gap: 10px; position: relative; }
    .summary-card:not(:last-child)::after { content: "·"; position: absolute; right: -4px; top: 0; color: var(--ink-soft); font-size: 20px; }
    .summary-card span { font-family: var(--sans); font-size: 10px; letter-spacing: 0.26em; text-transform: uppercase; color: var(--ink-soft); }
    .summary-card strong { font-family: var(--display); font-size: 24px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .sheet-grid { columns: 2; column-gap: 36px; column-rule: 1px solid var(--rule-soft); }
    .panel { break-inside: avoid; padding: 0; margin: 0 0 26px; }
    .split-panel { display: block; }
    .split-panel > div + div { margin-top: 18px; }
    .abilities-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; text-align: center; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
    .ability-card { padding: 10px 4px; border-right: 1px solid var(--rule-soft); display: flex; flex-direction: column; gap: 2px; }
    .ability-card:last-child { border-right: 0; }
    .ability-code { font-family: var(--sans); font-size: 9.5px; letter-spacing: 0.26em; color: var(--ink-soft); }
    .ability-mod { font-family: var(--display); font-size: 26px; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
    .ability-score { font-family: var(--serif); font-size: 13px; font-style: italic; color: var(--ink-soft); }
    .ability-label { font-family: var(--sans); font-size: 9px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-soft); }
    .trackers-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px 16px; padding: 6px 0; border-bottom: 1px dashed var(--rule-soft); }
    .tracker-card { display: flex; align-items: baseline; gap: 8px; padding: 3px 0; }
    .tracker-card span { flex: 0 0 auto; font-family: var(--sans); font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); min-width: 72px; }
    .tracker { flex: 1; appearance: none; border: 0; border-bottom: 1px solid var(--rule-soft); background: transparent; font: 700 17px/1.2 var(--display); color: var(--ink); padding: 0 2px 2px; font-variant-numeric: tabular-nums; outline: none; }
    .tracker-check { width: 14px; height: 14px; accent-color: var(--ink); }
    .mini-note { margin: 10px 0 0; font-family: var(--serif); font-size: 13px; font-style: italic; color: var(--ink-soft); }
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; font-family: var(--serif); }
    th, td { padding: 3px 6px 3px 0; border-bottom: 1px dotted var(--rule-soft); text-align: left; vertical-align: baseline; }
    th { font-family: var(--sans); font-size: 9.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); font-weight: 700; }
    td:last-child, th:last-child { text-align: right; font-variant-numeric: tabular-nums; }
    .stack { display: block; }
    .list-card, .spell-card, .feature-card, .library-block { display: block; padding: 7px 0; border-bottom: 1px dotted var(--rule-soft); break-inside: avoid; }
    .list-head, summary { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; cursor: pointer; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    .list-head strong, summary strong { font-family: var(--display); font-size: 15px; font-weight: 700; letter-spacing: -0.005em; }
    summary small { font-family: var(--serif); font-style: italic; font-size: 12px; color: var(--ink-soft); margin-left: 6px; letter-spacing: 0; text-transform: none; }
    .list-head span:last-child { font-family: var(--serif); font-size: 14.5px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .list-meta, .spell-meta { font-family: var(--serif); font-size: 12.5px; font-style: italic; color: var(--ink-soft); margin: 2px 0 4px; }
    .spell-card p, .feature-card p, .list-card p, .library-block p { margin: 4px 0 0; font-size: 13.5px; text-align: justify; hyphens: auto; }
    .badges { display: inline-flex; gap: 4px; flex-wrap: wrap; }
    .badge { font-family: var(--sans); font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--ink-soft); padding: 1px 6px; border: 1px solid var(--rule-soft); white-space: nowrap; }
    textarea { display: block; width: 100%; min-height: 54px; border: 0; border-bottom: 1px solid var(--rule-soft); padding: 4px 0; font: 14px/1.45 var(--serif); color: var(--ink); background: transparent; resize: vertical; outline: none; }
    textarea:focus { border-bottom-color: var(--ink); }
    .notes-grid { columns: 2; column-gap: 28px; }
    .notes-card { display: flex; flex-direction: column; gap: 3px; break-inside: avoid; margin-bottom: 14px; }
    .notes-card span { font-family: var(--sans); font-size: 9.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); }
    .muted { color: var(--ink-soft); font-style: italic; }
    @media (max-width: 900px) {
      .page { padding: 28px 20px; border: 0; }
      h1 { font-size: 50px; }
      .sheet-grid { columns: 1; }
      .notes-grid { columns: 1; }
      .abilities-grid { grid-template-columns: repeat(3, 1fr); }
      .ability-card:nth-child(3n) { border-right: 0; }
      .summary-grid { gap: 4px 0; }
    }
    @media print {
      @page { size: A4; margin: 12mm; }
      body { background: white; }
      .page { border: 0; padding: 0; max-width: none; background: white; }
      .hero-actions, .screen-only { display: none !important; }
      .panel { break-inside: avoid; }
      .spell-card p, .feature-card p, .spell-meta { display: none !important; }
    }
"""


_SHEET_STYLE_CODEX = r"""
    :root {
      --paper: #f5ead2;
      --paper-deep: #e9d8ae;
      --ink: #2a1d0f;
      --ink-soft: #6e5536;
      --accent: #6d1a1a;
      --gold: #9e7a2b;
      --rule: rgba(42, 29, 15, 0.35);
      --rule-soft: rgba(42, 29, 15, 0.18);
      --serif: "Cormorant Garamond", "EB Garamond", "Garamond", "Times New Roman", serif;
      --display: "Cinzel", "Trajan Pro", "Cormorant Garamond", serif;
      --sans: "Inter", "Helvetica Neue", Arial, sans-serif;
      color-scheme: light;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; color: var(--ink); font-family: var(--serif); font-size: 16px; line-height: 1.52; }
    body {
      background: var(--paper);
      background-image:
        radial-gradient(circle at 18% 12%, rgba(158, 122, 43, 0.15), transparent 42%),
        radial-gradient(circle at 85% 88%, rgba(109, 26, 26, 0.08), transparent 45%),
        radial-gradient(circle at 50% 50%, rgba(42, 29, 15, 0.035), transparent 60%);
    }
    a { color: var(--accent); text-decoration: none; border-bottom: 1px dotted var(--accent); }
    a:hover { border-bottom-style: solid; }
    .page { max-width: 1120px; margin: 0 auto; padding: 60px 72px 96px; position: relative; }
    .page::before, .page::after { content: ""; position: absolute; left: 28px; right: 28px; height: 3px; background: linear-gradient(90deg, transparent, var(--gold) 20%, var(--gold) 80%, transparent); opacity: 0.7; pointer-events: none; }
    .page::before { top: 24px; }
    .page::after { bottom: 24px; }
    .hero { text-align: center; padding: 8px 0 30px; margin: 0 0 30px; border-bottom: 1px solid var(--rule); position: relative; }
    .hero::after { content: "\2766"; position: absolute; left: 50%; bottom: -14px; transform: translateX(-50%); background: var(--paper); padding: 0 12px; color: var(--gold); font-size: 18px; }
    .hero > div:first-child { display: flex; flex-direction: column; align-items: center; }
    .eyebrow { margin: 0 0 8px; font-family: var(--display); font-size: 11px; letter-spacing: 0.44em; text-transform: uppercase; color: var(--ink-soft); }
    h1 { margin: 0; font-family: var(--display); font-size: 62px; font-weight: 500; letter-spacing: 0.04em; line-height: 1; text-transform: uppercase; color: var(--accent); }
    .hero-line { margin: 10px 0 0; font-family: var(--serif); font-size: 17px; font-style: italic; color: var(--ink-soft); letter-spacing: 0.02em; }
    .hero-actions { position: absolute; top: 0; right: 0; display: flex; gap: 6px; }
    button { appearance: none; background: transparent; border: 1px solid var(--accent); color: var(--accent); font: 500 10.5px/1 var(--display); letter-spacing: 0.24em; text-transform: uppercase; padding: 7px 12px; cursor: pointer; }
    button:hover { background: var(--accent); color: var(--paper); }
    button.secondary { border-color: var(--ink-soft); color: var(--ink-soft); }
    button.secondary:hover { background: var(--ink-soft); color: var(--paper); }
    h2 { font-family: var(--display); font-size: 15px; font-weight: 500; letter-spacing: 0.32em; text-transform: uppercase; text-align: center; color: var(--accent); margin: 0 0 18px; position: relative; padding: 0 0 14px; }
    h2::after { content: ""; position: absolute; bottom: 0; left: 22%; right: 22%; height: 1px; background: var(--rule-soft); }
    h3 { font-family: var(--display); font-size: 11.5px; font-weight: 500; letter-spacing: 0.28em; text-transform: uppercase; color: var(--ink-soft); text-align: center; margin: 22px 0 10px; }
    .summary-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin: 0 0 34px; }
    .summary-card { padding: 14px 10px 10px; text-align: center; border: 1px solid var(--gold); background: rgba(255, 250, 236, 0.55); position: relative; display: flex; flex-direction: column; gap: 6px; }
    .summary-card::before { content: ""; position: absolute; inset: 3px; border: 1px solid var(--rule-soft); pointer-events: none; }
    .summary-card span { font-family: var(--display); font-size: 10px; letter-spacing: 0.26em; text-transform: uppercase; color: var(--ink-soft); }
    .summary-card strong { font-family: var(--display); font-size: 26px; font-weight: 500; color: var(--accent); font-variant-numeric: tabular-nums; }
    .sheet-grid { display: grid; grid-template-columns: 1.15fr 1fr; gap: 44px; }
    .panel { margin: 0 0 34px; break-inside: avoid; }
    .split-panel { display: grid; grid-template-columns: 1fr 1.25fr; gap: 32px; }
    .abilities-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
    .ability-card { padding: 14px 10px 10px; text-align: center; border: 1px solid var(--rule-soft); background: rgba(255, 250, 236, 0.4); position: relative; display: flex; flex-direction: column; gap: 3px; }
    .ability-card::before, .ability-card::after { content: ""; position: absolute; width: 10px; height: 10px; border: 1px solid var(--gold); }
    .ability-card::before { top: 4px; left: 4px; border-right: 0; border-bottom: 0; }
    .ability-card::after { bottom: 4px; right: 4px; border-left: 0; border-top: 0; }
    .ability-code { font-family: var(--display); font-size: 10.5px; letter-spacing: 0.28em; color: var(--ink-soft); }
    .ability-mod { font-family: var(--display); font-size: 34px; font-weight: 500; color: var(--accent); line-height: 1; font-variant-numeric: tabular-nums; }
    .ability-score { font-family: var(--serif); font-size: 14px; font-style: italic; color: var(--ink-soft); }
    .ability-label { font-family: var(--serif); font-size: 11px; font-style: italic; color: var(--ink-soft); letter-spacing: 0.04em; }
    .trackers-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px 20px; }
    .tracker-card { display: flex; align-items: baseline; gap: 10px; padding: 6px 0; border-bottom: 1px solid var(--rule-soft); }
    .tracker-card span { font-family: var(--display); font-size: 10px; letter-spacing: 0.24em; text-transform: uppercase; color: var(--ink-soft); min-width: 76px; }
    .tracker { flex: 1; appearance: none; background: transparent; border: 0; font: 500 20px/1 var(--display); color: var(--accent); padding: 0 2px; font-variant-numeric: tabular-nums; outline: none; }
    .tracker-check { width: 18px; height: 18px; accent-color: var(--accent); }
    .mini-note { margin: 14px 0 0; font-size: 13.5px; font-style: italic; color: var(--ink-soft); text-align: center; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 5px 8px 5px 0; border-bottom: 1px solid var(--rule-soft); vertical-align: baseline; }
    th { font-family: var(--display); font-size: 10px; letter-spacing: 0.26em; text-transform: uppercase; color: var(--ink-soft); font-weight: 500; padding-bottom: 8px; border-bottom-color: var(--rule); }
    td:last-child, th:last-child { text-align: right; font-variant-numeric: tabular-nums; }
    .stack { display: flex; flex-direction: column; }
    .list-card, .spell-card, .feature-card, .library-block { padding: 10px 0 12px; border-bottom: 1px solid var(--rule-soft); }
    .list-head, summary { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; cursor: pointer; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    .list-head strong, summary strong { font-family: var(--display); font-size: 15px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); }
    summary small { font-family: var(--serif); font-style: italic; font-size: 13px; color: var(--ink-soft); letter-spacing: 0; text-transform: none; margin-left: 8px; }
    .list-head span:last-child { font-family: var(--display); font-size: 15px; font-weight: 500; color: var(--accent); font-variant-numeric: tabular-nums; }
    .list-meta, .spell-meta { font-size: 13px; font-style: italic; color: var(--ink-soft); margin: 4px 0 6px; }
    .spell-card p, .feature-card p, .list-card p, .library-block p { margin: 5px 0 0; font-size: 14px; line-height: 1.55; }
    .badges { display: inline-flex; gap: 5px; flex-wrap: wrap; }
    .badge { font-family: var(--display); font-size: 9.5px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--ink-soft); padding: 2px 8px; border: 1px solid var(--gold); background: rgba(158, 122, 43, 0.06); white-space: nowrap; }
    textarea { display: block; width: 100%; min-height: 72px; border: 0; border-bottom: 1px solid var(--rule-soft); padding: 6px 2px; font: 14.5px/1.5 var(--serif); color: var(--ink); background: rgba(255, 250, 236, 0.3); resize: vertical; outline: none; }
    textarea:focus { border-bottom-color: var(--accent); background: rgba(255, 250, 236, 0.55); }
    .notes-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px 28px; }
    .notes-card { display: flex; flex-direction: column; gap: 4px; }
    .notes-card span { font-family: var(--display); font-size: 10px; letter-spacing: 0.24em; text-transform: uppercase; color: var(--ink-soft); }
    .muted { color: var(--ink-soft); font-style: italic; }
    @media (max-width: 960px) {
      .page { padding: 40px 24px; }
      .page::before, .page::after { left: 12px; right: 12px; }
      h1 { font-size: 44px; }
      .sheet-grid, .split-panel, .notes-grid { grid-template-columns: 1fr; gap: 20px; }
      .summary-grid { grid-template-columns: repeat(3, 1fr); }
      .abilities-grid { grid-template-columns: repeat(2, 1fr); }
    }
    @media print {
      @page { size: A4; margin: 14mm; }
      body { background: var(--paper); }
      .page::before, .page::after { display: none; }
      .page { padding: 0; max-width: none; }
      .hero-actions, .screen-only { display: none !important; }
      .panel, .ability-card, .summary-card, .spell-card, .feature-card, .list-card, .library-block { break-inside: avoid; }
      .spell-card p, .feature-card p, .spell-meta { display: none !important; }
    }
"""


def _sheet_stylesheet(style: str) -> str:
    if style == "gazette":
        return _SHEET_STYLE_GAZETTE
    if style == "grimoire":
        return _SHEET_STYLE_CODEX
    return _SHEET_STYLE_LEDGER


def render_sheet(data: dict[str, Any], sheet_id: str, style: str = "ledger") -> str:
    ability_cards = "".join(
        f'''
        <article class="ability-card">
          <div class="ability-code">{esc(row["code"])}</div>
          <div class="ability-mod">{esc(row["mod"])}</div>
          <div class="ability-score">{esc(row["score"])}</div>
          <div class="ability-label">{esc(row["label"])}</div>
        </article>
        '''
        for row in data["ability_rows"]
    )

    saving_rows = "".join(
        f'''
        <tr>
          <td>{'●' if row["proficient"] else '○'} {esc(row["label"])}</td>
          <td>{esc(row["bonus"])}</td>
        </tr>
        '''
        for row in data["saving_throw_rows"]
    )

    skill_rows = "".join(
        f'''
        <tr>
          <td>{'●' if row["proficient"] else '○'} {esc(row["label"])}</td>
          <td>{esc(row["ability"])}</td>
          <td>{esc(row["bonus"])}</td>
        </tr>
        '''
        for row in data["skill_rows"]
    )

    tool_rows = "".join(
        f'''
        <tr>
          <td>{esc(row["label"])}</td>
          <td>{esc(row["ability"])}</td>
          <td>{esc(row["bonus"])}</td>
        </tr>
        '''
        for row in data["tool_rows"]
    ) or '<tr><td colspan="3" class="muted">None</td></tr>'

    attack_cards = "".join(
        f'''
        <article class="list-card">
          <div class="list-head">
            <strong>{esc(row["name"])}</strong>
            <span>{esc(row["attack_bonus"])}</span>
          </div>
          <div class="list-meta">{esc(row["damage"])} · {esc(row["range"] or "Melee")}</div>
          <p>{esc(row["notes"] or "No extra rider text.")}</p>
        </article>
        '''
        for row in data["attacks"]
    ) or '<p class="muted">No equipped attacks found.</p>'

    spell_cards = "".join(
        f'''
        <details class="spell-card" {'open' if row["level"] <= 1 else ''}>
          <summary>
            <span><strong>{esc(row["name"])}</strong> <small>Level {row["level"]} · {esc(row["school"])}</small></span>
            {render_badges(row["badges"])}
          </summary>
          <div class="spell-meta">{esc(row["activation"])} · {esc(row["range"])} · {esc(row["duration"])}</div>
          <p>{esc(row["description"] or "No description available in the export.")}</p>
        </details>
        '''
        for row in data["active_spells"]
    )

    library_sections = "".join(
        f'''
        <details class="library-block">
          <summary>Level {level} Library</summary>
          <p>{esc(", ".join(names))}</p>
        </details>
        '''
        for level, names in sorted(data["spell_library"].items())
    ) or '<p class="muted">No extra library spells were found beyond the active list.</p>'

    feature_sections = []
    for label, entries in data["feature_groups"].items():
        if not entries:
            continue
        body = "".join(
            f'''
            <details class="feature-card">
              <summary>
                <span>{esc(entry["name"])}</span>
                {render_badges(
                    [
                        *(["Uses: " + str(entry["uses"].get("max"))] if entry["uses"].get("max") else []),
                        *(["Recovery: " + format_recovery(entry["uses"])] if format_recovery(entry["uses"]) else []),
                    ]
                )}
              </summary>
              <p>{esc(entry["requirements"] or entry["description"] or "Passive feature.")}</p>
            </details>
            '''
            for entry in entries
        )
        feature_sections.append(f'<section><h3>{esc(label)}</h3>{body}</section>')
    features_html = "".join(feature_sections)

    inventory_rows = "".join(
        f'''
        <tr>
          <td>{esc(item["name"])}</td>
          <td>{esc(item["quantity"])}</td>
          <td>{esc(item["container"] or "On Person")}</td>
          <td>{item["weight"]:.1f} lb</td>
        </tr>
        '''
        for item in sorted(data["inventory"], key=lambda row: (row["container"], row["name"]))
    )

    notes_blocks = "".join(
        f'''
        <label class="notes-card">
          <span>{esc(label)}</span>
          <textarea data-persist="notes-{slugify(label)}">{esc(text)}</textarea>
        </label>
        '''
        for label, text in [
            ("Traits", data["notes"]["traits"]),
            ("Ideal", data["notes"]["ideal"]),
            ("Bond", data["notes"]["bond"]),
            ("Flaw", data["notes"]["flaw"]),
            ("Appearance", data["notes"]["appearance"]),
            ("Biography", data["notes"]["biography"]),
            ("Session Notes", ""),
        ]
    )

    slot_trackers = "".join(
        render_stat_input(slot["label"], slot["value"], f"slot-{slugify(slot['label'])}")
        for slot in data["slot_defaults"]
    ) or '<p class="muted">No spell slots exported.</p>'

    passive_line = f'Passive Perception {data["passive_perception"]} · Passive Insight {data["passive_insight"]} · Passive Investigation {data["passive_investigation"]}'
    senses = [f'{data["speed"]} ft speed']
    if data["darkvision"]:
        senses.append(f'{data["darkvision"]} ft darkvision')

    body = f"""
    <header class="hero">
      <div>
        <p class="eyebrow">Foundry VTT -> D&D 2024 Sheet</p>
        <h1>{esc(data["name"])}</h1>
        <p class="hero-line">{esc(data["class_line"])}{(' · ' + esc(data["subclass"])) if data["subclass"] else ''}</p>
        <p class="hero-line">{esc(data["species"] or 'Species not set')} · {esc(data["background"] or 'Background not set')} · Level {esc(data["level"])}</p>
      </div>
      <div class="hero-actions">
        <button type="button" id="print-sheet">Print / Save PDF</button>
        <button type="button" id="reset-sheet" class="secondary">Reset Trackers</button>
      </div>
    </header>

    <section class="summary-grid">
      <div class="summary-card">
        <span>Armor Class</span>
        <strong>{esc(data["ac"])}</strong>
      </div>
      <div class="summary-card">
        <span>Initiative</span>
        <strong>{esc(signed(data["initiative"]))}</strong>
      </div>
      <div class="summary-card">
        <span>Proficiency</span>
        <strong>{esc(signed(data["prof_bonus"]))}</strong>
      </div>
      <div class="summary-card">
        <span>Spell Save DC</span>
        <strong>{esc(data["spell_dc"] if data["spell_dc"] is not None else "—")}</strong>
      </div>
      <div class="summary-card">
        <span>Spell Attack</span>
        <strong>{esc(signed(data["spell_attack"]) if data["spell_attack"] is not None else "—")}</strong>
      </div>
      <div class="summary-card">
        <span>Spellcasting</span>
        <strong>{esc(data["spell_ability"])}</strong>
      </div>
    </section>

    <main class="sheet-grid">
      <section class="panel">
        <h2>Trackers</h2>
        <div class="trackers-grid">
          {render_stat_input("HP", data["hp_value"], "hp-current")}
          {render_stat_input("Temp HP", data["temp_hp"], "hp-temp")}
          {render_stat_input("Inspiration", data["inspiration"], "inspiration", "checkbox")}
          {slot_trackers}
        </div>
        <p class="mini-note">{esc(passive_line)}</p>
      </section>

      <section class="panel">
        <h2>Ability Scores</h2>
        <div class="abilities-grid">{ability_cards}</div>
      </section>

      <section class="panel split-panel">
        <div>
          <h2>Saving Throws</h2>
          <table>
            <tbody>{saving_rows}</tbody>
          </table>
        </div>
        <div>
          <h2>Skills</h2>
          <table>
            <thead><tr><th>Skill</th><th>Abil</th><th>Bonus</th></tr></thead>
            <tbody>{skill_rows}</tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <h2>Combat</h2>
        <p class="mini-note">{esc(" · ".join(senses))}</p>
        <div class="stack">{attack_cards}</div>
      </section>

      <section class="panel">
        <h2>Spellbook</h2>
        <div class="stack">{spell_cards}</div>
        <div class="screen-only">
          <h3>Imported Library</h3>
          {library_sections}
        </div>
      </section>

      <section class="panel">
        <h2>Features</h2>
        {features_html}
      </section>

      <section class="panel split-panel">
        <div>
          <h2>Proficiencies</h2>
          <p>{esc(", ".join(data["proficiencies"]) or "None")}</p>
          <h2>Languages</h2>
          <p>{esc(", ".join(data["languages"]) or "None")}</p>
          <h2>Currency</h2>
          <p>{esc(data["currency"])}</p>
          <h2>Carry Weight</h2>
          <p>{data["inventory_weight"]:.1f} lb</p>
        </div>
        <div>
          <h2>Tool Checks</h2>
          <table>
            <thead><tr><th>Tool</th><th>Abil</th><th>Bonus</th></tr></thead>
            <tbody>{tool_rows}</tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <h2>Inventory</h2>
        <table>
          <thead><tr><th>Item</th><th>Qty</th><th>Location</th><th>Weight</th></tr></thead>
          <tbody>{inventory_rows}</tbody>
        </table>
      </section>

      <section class="panel">
        <h2>Notes</h2>
        <div class="notes-grid">{notes_blocks}</div>
      </section>
    </main>
    """

    style = _sheet_stylesheet(style)
    script = """
    (() => {
      const storageKey = "__STORAGE_KEY__";
      const state = JSON.parse(localStorage.getItem(storageKey) || "{}");
      const persistNodes = document.querySelectorAll("[data-persist]");

      for (const node of persistNodes) {
        const key = node.dataset.persist;
        if (Object.prototype.hasOwnProperty.call(state, key)) {
          if (node.type === "checkbox") {
            node.checked = Boolean(state[key]);
          } else {
            node.value = state[key];
          }
        }

        const save = () => {
          state[key] = node.type === "checkbox" ? node.checked : node.value;
          localStorage.setItem(storageKey, JSON.stringify(state));
        };

        node.addEventListener(node.type === "checkbox" ? "change" : "input", save);
      }

      document.getElementById("print-sheet")?.addEventListener("click", () => window.print());
      document.getElementById("reset-sheet")?.addEventListener("click", () => {
        localStorage.removeItem(storageKey);
        window.location.reload();
      });
    })();
    """.replace("__STORAGE_KEY__", json.dumps(f"foundry-sheet:{sheet_id}"))

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(data["name"])} Character Sheet</title>
    <style>{style}</style>
  </head>
  <body>
    <div class="page">
      {body}
    </div>
    <script>{script}</script>
  </body>
</html>
"""


def _sheet_palette_css(palette: str | None) -> str:
    if palette == "dracula":
        return r"""
        body.dnd-layout-palette-dracula {
          --serif: "Literata", "Source Serif 4", "Georgia", "Times New Roman", serif;
          --display: "Space Grotesk", "Avenir Next Condensed", "Helvetica Neue", sans-serif;
          --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at 16% 10%, rgba(189, 147, 249, 0.18), transparent 36%),
            radial-gradient(circle at 82% 22%, rgba(139, 233, 253, 0.14), transparent 30%),
            radial-gradient(circle at 80% 84%, rgba(255, 121, 198, 0.12), transparent 34%),
            var(--paper);
        }
        body.dnd-layout-palette-dracula .dnd-layout-page-title,
        body.dnd-layout-palette-dracula .dnd-layout-section-title,
        body.dnd-layout-palette-dracula .dnd-layout-label,
        body.dnd-layout-palette-dracula .dnd-layout-token,
        body.dnd-layout-palette-dracula .dnd-layout-summary-card .value,
        body.dnd-layout-palette-dracula .dnd-layout-mini-stat .value,
        body.dnd-layout-palette-dracula button {
          font-family: var(--display);
          letter-spacing: 0.16em;
          text-transform: uppercase;
        }
        body.dnd-layout-palette-dracula .dnd-layout-page { backdrop-filter: blur(3px); }
        body.dnd-layout-palette-dracula .dnd-layout-panel::before {
          content: "";
          position: absolute;
          inset: 0;
          background: linear-gradient(135deg, rgba(139, 233, 253, 0.08), transparent 42%);
          pointer-events: none;
        }
        """
    if palette == "catppuccin":
        return r"""
        body.dnd-layout-palette-catppuccin {
          --serif: "Fraunces", "Source Serif 4", "Georgia", serif;
          --display: "Sora", "Avenir Next", "Helvetica Neue", sans-serif;
          --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at 18% 14%, rgba(136, 57, 239, 0.028), transparent 30%),
            radial-gradient(circle at 82% 84%, rgba(30, 102, 245, 0.024), transparent 30%),
            linear-gradient(180deg, rgba(220, 224, 232, 0.12), transparent 180px),
            var(--paper);
        }
        body.dnd-layout-palette-catppuccin .dnd-layout-page-title,
        body.dnd-layout-palette-catppuccin .dnd-layout-section-title,
        body.dnd-layout-palette-catppuccin .dnd-layout-label,
        body.dnd-layout-palette-catppuccin .dnd-layout-token,
        body.dnd-layout-palette-catppuccin .dnd-layout-summary-card .value,
        body.dnd-layout-palette-catppuccin .dnd-layout-mini-stat .value,
        body.dnd-layout-palette-catppuccin button {
          font-family: var(--display);
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        body.dnd-layout-palette-catppuccin .dnd-layout-panel::before,
        body.dnd-layout-palette-catppuccin .dnd-layout-summary-card::before {
          content: "";
          position: absolute;
          inset: 0;
          background: linear-gradient(180deg, rgba(136, 57, 239, 0.035), rgba(255, 255, 255, 0.015) 18%, transparent 34%);
          pointer-events: none;
        }
        """
    if palette == "nord":
        return r"""
        body.dnd-layout-palette-nord {
          --serif: "Source Serif 4", "Iowan Old Style", "Georgia", serif;
          --display: "IBM Plex Sans Condensed", "IBM Plex Sans", "Helvetica Neue", sans-serif;
          --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at 16% 12%, rgba(136, 192, 208, 0.18), transparent 32%),
            radial-gradient(circle at 84% 16%, rgba(129, 161, 193, 0.12), transparent 30%),
            linear-gradient(180deg, rgba(216, 222, 233, 0.78), transparent 240px),
            var(--paper);
        }
        body.dnd-layout-palette-nord .dnd-layout-page-title,
        body.dnd-layout-palette-nord .dnd-layout-section-title,
        body.dnd-layout-palette-nord .dnd-layout-label,
        body.dnd-layout-palette-nord .dnd-layout-token,
        body.dnd-layout-palette-nord .dnd-layout-summary-card .value,
        body.dnd-layout-palette-nord .dnd-layout-mini-stat .value,
        body.dnd-layout-palette-nord button {
          font-family: var(--display);
          letter-spacing: 0.18em;
          text-transform: uppercase;
        }
        body.dnd-layout-palette-nord .dnd-layout-page,
        body.dnd-layout-palette-nord .dnd-layout-panel {
          border-color: rgba(94, 129, 172, 0.26);
        }
        """
    if palette == "hearth":
        return r"""
        body.dnd-layout-palette-hearth {
          --serif: "Tiempos Text", "Source Serif 4", "Georgia", serif;
          --display: "Styrene B", "Inter", "Helvetica Neue", sans-serif;
          --sans: "Styrene B", "Inter", "Helvetica Neue", sans-serif;
          background:
            radial-gradient(circle at 88% 6%, rgba(204, 120, 92, 0.18), transparent 38%),
            radial-gradient(circle at 12% 92%, rgba(145, 86, 65, 0.06), transparent 42%),
            linear-gradient(180deg, rgba(244, 237, 225, 0.55), transparent 240px),
            var(--paper);
        }
        body.dnd-layout-palette-hearth .dnd-layout-page-title,
        body.dnd-layout-palette-hearth .dnd-layout-section-title,
        body.dnd-layout-palette-hearth .dnd-layout-label,
        body.dnd-layout-palette-hearth .dnd-layout-token,
        body.dnd-layout-palette-hearth .dnd-layout-summary-card .value,
        body.dnd-layout-palette-hearth .dnd-layout-mini-stat .value,
        body.dnd-layout-palette-hearth button {
          font-family: var(--display);
          letter-spacing: 0.14em;
          text-transform: uppercase;
        }
        """
    return ""


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
    class_features_html = render_v2_list(class_entries, 12) or '<p class="muted">No class features exported.</p>'
    species_traits_html = render_v2_list(species_entries, 10) or '<p class="muted">No ancestry traits exported.</p>'
    feats_html = render_v2_list(feat_entries, 10) or '<p class="muted">No feats exported.</p>'

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
    html, body { margin: 0; color: var(--ink); font-family: var(--serif); -webkit-font-smoothing: antialiased; }
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
      color: var(--paper);
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
    .dnd-layout-page-head > div:first-of-type { padding: 18px 0 0 22px; }
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
      box-shadow: inset 3px 0 0 var(--accent);
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
      font-weight: 600;
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
      color: var(--paper);
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
        margin-bottom: 8px;
        padding-bottom: 6px;
      }
      .dnd-layout-page-head > div:first-of-type { padding: 1px 0 0 2px; }
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


def _sheet_mode_overrides(style: str, theme_palette: dict[str, str] | None = None) -> str:
    dark_palette = {
        "ledger": {
            "paper": "#0f1114",
            "panel": "rgba(24, 27, 34, 0.94)",
            "panel_soft": "rgba(34, 38, 48, 0.62)",
            "ink": "#ecdcbd",
            "ink_soft": "#a8a091",
            "rule": "rgba(236, 220, 189, 0.72)",
            "rule_soft": "rgba(236, 220, 189, 0.16)",
            "shadow": "0 24px 52px rgba(0, 0, 0, 0.55)",
            "accent": "#f39c7e",
            "accent_strong": "#f39c7e",
        },
        "gazette": {
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
        "grimoire": {
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
    }.get(style, {
        "paper": "#0f1114",
        "panel": "rgba(24, 27, 34, 0.94)",
        "panel_soft": "rgba(34, 38, 48, 0.62)",
        "ink": "#ecdcbd",
        "ink_soft": "#a8a091",
        "rule": "rgba(236, 220, 189, 0.72)",
        "rule_soft": "rgba(236, 220, 189, 0.16)",
        "shadow": "0 24px 52px rgba(0, 0, 0, 0.55)",
        "accent": "#f39c7e",
        "accent_strong": "#f39c7e",
    })
    if theme_palette:
        dark_palette = {
            **dark_palette,
            "accent": theme_palette["dark_accent"],
            "accent_strong": theme_palette["dark_accent_strong"],
        }
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

    body.sheet-theme-{style}[data-theme="dark"] {{
      --paper: {dark_palette["paper"]};
      --panel: {dark_palette["panel"]};
      --panel-soft: {dark_palette["panel_soft"]};
      --ink: {dark_palette["ink"]};
      --ink-soft: {dark_palette["ink_soft"]};
      --rule: {dark_palette["rule"]};
      --rule-soft: {dark_palette["rule_soft"]};
      --shadow: {dark_palette["shadow"]};
      --accent: {dark_palette["accent"]};
      --accent-strong: {dark_palette["accent_strong"]};
    }}
    body[data-theme="dark"] {{
      background: var(--paper) !important;
      color: var(--ink);
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
      color: #fff !important;
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
        --panel: #ffffff !important;
        --panel-soft: rgba(0, 0, 0, 0.025) !important;
        --rule-soft: rgba(17, 17, 17, 0.18) !important;
        --shadow: none !important;
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
    if theme_palette:
        base += f"""
    /* Theme-driven accent (light mode) */
    :root {{
      --accent: {theme_palette["light_accent"]};
      --accent-strong: {theme_palette["light_accent_strong"]};
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
    theme_palette: dict[str, str] | None = None,
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
    html = html.replace("</style>", overrides + "</style>", 1)

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


def _render_one_theme(
    context: dict[str, Any],
    sheet_id: str,
    output_dir: Path,
    theme_label: str,
    entry: dict,
    mode: str | None,
    include_footer: bool = True,
    paper: str = "a4",
) -> Path:
    html_path = output_dir / f"{sheet_id}-character-sheet-{theme_label.lstrip('#')}.html"
    palette = {
        "light_accent":        entry["light_accent"],
        "light_accent_strong": entry["light_accent_strong"],
        "dark_accent":         entry["dark_accent"],
        "dark_accent_strong":  entry["dark_accent_strong"],
    }
    html_path.write_text(render_character_sheet(
        context,
        sheet_id,
        style=entry["base"],
        initial_theme=mode,
        theme_palette=palette,
        palette_decoration=entry.get("decoration"),
        include_footer=include_footer,
        paper=paper,
    ))
    return html_path


def write_output(
    actor_path: Path,
    output_dir: Path,
    mode: str | None = None,
    theme: str | None = None,
    all_themes: bool = False,
    include_footer: bool = True,
    paper: str = "a4",
) -> list[Path]:
    actor = json.loads(actor_path.read_text())
    context = sheet_context(actor)
    sheet_id = slugify(actor.get("name", actor_path.stem))

    if all_themes:
        return [
            _render_one_theme(context, sheet_id, output_dir, name, dict(entry), mode, include_footer=include_footer, paper=paper)
            for name, entry in THEMES.items()
        ]

    resolved = resolve_theme_entry(theme) if theme else resolve_theme_entry(primary_class_slug(actor))
    if resolved is None:
        # No actor class detected and no --theme passed → fall back to ledger
        resolved = ("ledger", dict(THEMES["ledger"]))
    label, entry = resolved
    return [_render_one_theme(context, sheet_id, output_dir, label, entry, mode, include_footer=include_footer, paper=paper)]


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
    ):
        found = which(candidate)
        if found:
            return found
    platform_paths = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in platform_paths:
        if exists(candidate):
            return str(candidate)
    return None


def render_pdf(html_path: Path, pdf_path: Path, browser: str, mode: str | None = None) -> None:
    target_uri = html_path.resolve().as_uri()
    if mode:
        target_uri += f"?theme={mode}"
    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--allow-file-access-from-files",
        "--virtual-time-budget=1500",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        target_uri,
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def parse_theme_arg(value: str) -> str:
    name = value.strip()
    if name in THEMES:
        return name
    if HEX_COLOR_RE.match(name):
        return name if name.startswith("#") else f"#{name}"
    raise argparse.ArgumentTypeError(
        f"Unknown theme {value!r}. Choose one of: {', '.join(sorted(THEMES))} or a #RRGGBB hex."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actor_json", type=Path, help="Path to the exported Foundry actor JSON file")
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
    parser.add_argument("--all-themes", action="store_true", help="Render one HTML per registered theme")
    parser.add_argument("--pdf", action="store_true", help="Also generate a PDF using local Chromium")
    parser.add_argument("--chromium", help="Explicit Chromium executable path")
    parser.add_argument("--print-browser", dest="chromium", help="Explicit Chromium-compatible browser path for PDF export")
    parser.add_argument("--no-footer", action="store_true", help="Do not include the attribution/disclaimer footer")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    html_paths = write_output(
        args.actor_json,
        args.output_dir,
        mode=args.mode,
        theme=args.theme,
        all_themes=args.all_themes,
        include_footer=not args.no_footer,
        paper=args.paper,
    )
    for path in html_paths:
        print(f"HTML written to {path}")

    if args.pdf:
        browser = chromium_path(args.chromium)
        if not browser:
            print("Chromium not found; HTML was generated but PDF was skipped.", file=sys.stderr)
            return 1
        for path in html_paths:
            pdf_path = path.with_suffix(".pdf")
            render_pdf(path, pdf_path, browser, mode=args.mode)
            print(f"PDF written to {pdf_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
