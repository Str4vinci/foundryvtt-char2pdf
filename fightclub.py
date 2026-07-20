"""Import Lion's Den "Fight Club 5e" / "Game Master 5" character XML.

Those mobile apps export a proprietary XML format: a ``<pc version="5">`` root
wrapping a single ``<character>``. It describes the same game as Foundry's
``dnd5e`` system, just in a different shape. This module converts that XML into
the **Foundry-shaped actor dict** that the rest of char2pdf already understands,
so the entire existing renderer (themes, color modes, PDF export, web UI) is
reused unchanged — the dnd5e adapter recognizes the produced dict by its schema.

Only the Python standard library is used (``xml.etree.ElementTree``), preserving
the project's dependency-free rule.

Encoding notes (deduced from a real export and confirmed by the format's own
internal consistency and known D&D 5e rules — e.g. a Kalashtar's +2 WIS / +1 CHA
racial bonus lands on ability indices 4 and 5, and Beguiling Influence's
Deception/Persuasion grants land on skill indices 4 and 13):

* ``<abilities>`` is a CSV of the six base scores in order STR,DEX,CON,INT,WIS,CHA.
* ``<mod category="1" type="N">`` adds an ability bonus; ``type`` N is the ability
  index (0=STR … 5=CHA). Untyped ability mods (some ASIs) carry no target — see
  :func:`_reconstruct_abilities` for how those are resolved.
* ``<proficiency>`` codes: values < 100 are proficient saving throws (ability
  index); values >= 100 are proficient skills (``100 + skillIndex``).
* Skill index is alphabetical (Acrobatics=0 … Survival=17); ``<mod category="4">``
  grants a skill by that same index.
* Spell ``school`` is 1..8 alphabetical (1=Abjuration … 8=Transmutation).
* ``<slots>`` is a CSV of slot counts by spell level (index == spell level).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

# Ability index used throughout the Fight Club format (0-based).
ABILITY_ORDER = ["str", "dex", "con", "int", "wis", "cha"]

# Skill index is alphabetical by skill name and lines up with the dnd5e skill
# codes the renderer expects. (code, default ability) in index order 0..17.
SKILLS: list[tuple[str, str]] = [
    ("acr", "dex"),  # 0  Acrobatics
    ("ani", "wis"),  # 1  Animal Handling
    ("arc", "int"),  # 2  Arcana
    ("ath", "str"),  # 3  Athletics
    ("dec", "cha"),  # 4  Deception
    ("his", "int"),  # 5  History
    ("ins", "wis"),  # 6  Insight
    ("itm", "cha"),  # 7  Intimidation
    ("inv", "int"),  # 8  Investigation
    ("med", "wis"),  # 9  Medicine
    ("nat", "int"),  # 10 Nature
    ("prc", "wis"),  # 11 Perception
    ("prf", "cha"),  # 12 Performance
    ("per", "cha"),  # 13 Persuasion
    ("rel", "int"),  # 14 Religion
    ("slt", "dex"),  # 15 Sleight of Hand
    ("ste", "dex"),  # 16 Stealth
    ("sur", "wis"),  # 17 Survival
]

# Spell school index (1-based, alphabetical) -> dnd5e school code.
SPELL_SCHOOLS = {
    1: "abj", 2: "con", 3: "div", 4: "enc",
    5: "evo", 6: "ill", 7: "nec", 8: "trs",
}

# Reverse lookups used by the exporter (:func:`to_xml`).
_SKILL_INDEX = {code: i for i, (code, _ability) in enumerate(SKILLS)}
_SCHOOL_NUM = {code: num for num, code in SPELL_SCHOOLS.items()}


class FightClubParseError(ValueError):
    """Raised when the XML is not a recognizable Fight Club 5e character."""


def looks_like_fightclub(text: str) -> bool:
    """Cheap sniff: does this text look like a Fight Club / GM5 character export?

    Detection is by the ``<pc>`` root element. The text must start as markup (to
    rule out Foundry JSON), and the ``<pc>`` tag is then found within the opening
    stretch, tolerating a leading XML declaration and comments.
    """
    stripped = text.lstrip()
    if not stripped.startswith("<"):
        return False
    return re.search(r"<pc\b", stripped[:5000], re.IGNORECASE) is not None


# --------------------------------------------------------------------------- #
# Small parsing helpers
# --------------------------------------------------------------------------- #
def _text(el: ET.Element | None, default: str = "") -> str:
    if el is None or el.text is None:
        return default
    return el.text.strip()


def _child_text(parent: ET.Element, tag: str, default: str = "") -> str:
    return _text(parent.find(tag), default)


def _int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _csv_ints(value: str) -> list[int]:
    return [_int(part) for part in value.split(",") if part.strip() != ""]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def _feature_slug(name: str) -> str:
    """Slugify a feature name, dropping a trailing ``(...)`` qualifier.

    "Healing Light (The Celestial)" -> "healing-light" so it lines up with the
    renderer's resource whitelists (POOL_RESOURCE_IDS / SPENDABLE_RESOURCE_IDS).
    """
    base = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    return _slugify(base or name)


# --------------------------------------------------------------------------- #
# Abilities
# --------------------------------------------------------------------------- #
def _all_mods(char: ET.Element, category: str) -> list[ET.Element]:
    return [m for m in char.iter("mod") if _child_text(m, "category") == category]


def _spellcasting_ability_index(char: ET.Element) -> int | None:
    """The class's spellcasting ability as a 0-based ability index, if any."""
    cls = char.find("class")
    if cls is None:
        return None
    raw = _child_text(cls, "spellAbility")
    if raw == "":
        return None
    idx = _int(raw, -1)
    return idx if 0 <= idx <= 5 else None


def _reconstruct_abilities(char: ET.Element) -> dict[str, int]:
    """Final ability scores = base CSV + all category-1 ability mods.

    Typed mods (``type`` in 0..5) apply to a specific ability. Some ASIs export
    an untyped +1 with no ``type``; those are ambiguous, so we apply them to the
    class's spellcasting ability (the stat a caster maxes), or, failing that, to
    the currently highest ability. This is the one lossy spot in the import; the
    computed scores are surfaced so the user can sanity-check them.
    """
    base = _csv_ints(_child_text(char, "abilities"))
    scores = {code: (base[i] if i < len(base) else 10) for i, code in enumerate(ABILITY_ORDER)}

    untyped_total = 0
    for mod in _all_mods(char, "1"):
        value = _int(_child_text(mod, "value"))
        type_raw = _child_text(mod, "type")
        if type_raw == "":
            untyped_total += value
            continue
        idx = _int(type_raw, -1)
        if 0 <= idx <= 5:
            scores[ABILITY_ORDER[idx]] += value

    if untyped_total:
        cast_idx = _spellcasting_ability_index(char)
        if cast_idx is not None:
            target = ABILITY_ORDER[cast_idx]
        else:
            target = max(scores, key=lambda code: scores[code])
        scores[target] += untyped_total

    return scores


# --------------------------------------------------------------------------- #
# Proficiencies (saves + skills)
# --------------------------------------------------------------------------- #
def _proficiency_codes(char: ET.Element) -> list[int]:
    codes: list[int] = []
    for scope in (char.find("background"), char.find("class"), char.find("race")):
        if scope is None:
            continue
        for prof in scope.findall("proficiency"):
            raw = _text(prof)
            if raw != "":
                codes.append(_int(raw))
    return codes


def _proficient_saves_and_skills(char: ET.Element) -> tuple[set[str], set[str]]:
    """Return (proficient ability codes for saves, proficient skill codes)."""
    saves: set[str] = set()
    skills: set[str] = set()
    for code in _proficiency_codes(char):
        if code >= 100:
            idx = code - 100
            if 0 <= idx < len(SKILLS):
                skills.add(SKILLS[idx][0])
        elif 0 <= code <= 5:
            saves.add(ABILITY_ORDER[code])
    # Skills can also be granted by category-4 mods (e.g. Beguiling Influence).
    for mod in _all_mods(char, "4"):
        idx = _int(_child_text(mod, "type"), -1)
        if 0 <= idx < len(SKILLS):
            skills.add(SKILLS[idx][0])
    return saves, skills


# --------------------------------------------------------------------------- #
# Items / equipment
# --------------------------------------------------------------------------- #
# Fight Club item type codes. 1 = armor, 5 = weapon; the rest are inventory.
_ARMOR_TYPE = "1"


def _armor_category(base_ac: int) -> tuple[str, int | None]:
    """Rough (armor kind, dex cap) from base AC, since the XML omits the kind.

    Light armor takes full Dex, medium caps at +2, heavy at +0. Good for the
    common cases; unusual armors may be off by a point of Dex.
    """
    if base_ac <= 12:
        return "light", None
    if base_ac <= 15:
        return "medium", 2
    return "heavy", 0


def _build_inventory_items(char: ET.Element) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add_generic(el: ET.Element) -> None:
        name = _child_text(el, "name")
        if not name:
            return
        item_type = _child_text(el, "type")
        ac = _int(_child_text(el, "ac"), -1)
        text = _child_text(el, "text")
        weight = _child_text(el, "weight")
        value = _child_text(el, "value")
        sys: dict[str, Any] = {
            "description": {"value": text},
            "quantity": 1,
        }
        if weight:
            try:
                sys["weight"] = {"value": float(weight)}
            except ValueError:
                pass
        if value:
            try:
                sys["price"] = {"value": float(value), "denomination": "gp"}
            except ValueError:
                pass

        is_shield = "shield" in name.lower()
        if item_type == _ARMOR_TYPE and ac > 0 and not is_shield:
            kind, dex_cap = _armor_category(ac)
            sys["equipped"] = True
            sys["type"] = {"value": kind}
            sys["armor"] = {"value": ac, "dex": dex_cap}
            items.append({"type": "equipment", "name": name, "system": sys})
        elif is_shield:
            sys["equipped"] = True
            sys["type"] = {"value": "shield"}
            sys["armor"] = {"value": ac if ac > 0 else 2}
            items.append({"type": "equipment", "name": name, "system": sys})
        else:
            # Weapons and everything else become inventory (loot). Fight Club
            # stores no weapon damage dice, so we deliberately do not synthesize
            # attack rows we cannot back with real data.
            items.append({"type": "loot", "name": name, "system": sys})

    for el in char.findall("item"):
        add_generic(el)
    for container in char.findall("container"):
        for el in container.findall("item"):
            add_generic(el)
    return items


# --------------------------------------------------------------------------- #
# Spells
# --------------------------------------------------------------------------- #
def _build_spell_items(char: ET.Element) -> list[dict[str, Any]]:
    cls = char.find("class")
    spells: list[dict[str, Any]] = []
    scopes = [char]
    if cls is not None:
        scopes.append(cls)
    seen: set[tuple[str, int]] = set()
    for scope in scopes:
        for sp in scope.findall("spell"):
            name = _child_text(sp, "name")
            if not name:
                continue
            level = _int(_child_text(sp, "level"))
            key = (name.casefold(), level)
            if key in seen:
                continue
            seen.add(key)
            school = SPELL_SCHOOLS.get(_int(_child_text(sp, "school")), "")
            prepared = _int(_child_text(sp, "prepared"))
            spells.append({
                "type": "spell",
                "name": name,
                "system": {
                    "level": level,
                    "school": school,
                    "prepared": prepared,
                    "description": {"value": _child_text(sp, "text")},
                    "properties": [],
                },
            })
    return spells


def _build_spell_slots(char: ET.Element) -> dict[str, Any]:
    raw = _child_text(char, "slots")
    if not raw:
        cls = char.find("class")
        raw = _child_text(cls, "slots") if cls is not None else ""
    counts = _csv_ints(raw)
    spells: dict[str, Any] = {}
    # Index == spell level; index 0 (cantrips) has no slots.
    for level in range(1, 10):
        value = counts[level] if level < len(counts) else 0
        spells[f"spell{level}"] = {"value": value, "max": value}
    return spells


# --------------------------------------------------------------------------- #
# Features (racial traits, class features, feats)
# --------------------------------------------------------------------------- #
def _tracker_uses(char: ET.Element) -> dict[str, dict[str, int]]:
    """Map a feature slug -> its usage counts from class ``<tracker>`` elements."""
    uses: dict[str, dict[str, int]] = {}
    cls = char.find("class")
    if cls is None:
        return uses
    for tracker in cls.findall("tracker"):
        label = _child_text(tracker, "label")
        if not label:
            continue
        maximum = _int(_child_text(tracker, "formula"))
        if maximum <= 0:
            continue
        uses[_feature_slug(label)] = {
            "max": maximum,
            "value": _int(_child_text(tracker, "value"), maximum),
        }
    return uses


def _build_feature_items(char: ET.Element) -> list[dict[str, Any]]:
    uses_by_slug = _tracker_uses(char)
    features: list[dict[str, Any]] = []

    def add_feats(scope: ET.Element | None, feature_type: str) -> None:
        if scope is None:
            return
        for feat in scope.findall("feat"):
            name = _child_text(feat, "name")
            if not name:
                continue
            slug = _feature_slug(name)
            system: dict[str, Any] = {
                "type": {"value": feature_type},
                "identifier": slug,
                "description": {"value": _child_text(feat, "text")},
            }
            tracked = uses_by_slug.get(slug)
            if tracked:
                system["uses"] = {"max": tracked["max"], "spent": max(0, tracked["max"] - tracked["value"])}
            features.append({"type": "feat", "name": name, "system": system})

    add_feats(char.find("race"), "race")
    add_feats(char.find("class"), "class")
    add_feats(char.find("background"), "background")
    # Character-level feats (e.g. Fey Touched, Telekinetic).
    for feat in char.findall("feat"):
        name = _child_text(feat, "name")
        if not name:
            continue
        features.append({
            "type": "feat",
            "name": name,
            "system": {
                "type": {"value": "feat"},
                "identifier": _feature_slug(name),
                "description": {"value": _child_text(feat, "text")},
            },
        })
    return features


# --------------------------------------------------------------------------- #
# Top-level assembly
# --------------------------------------------------------------------------- #
def parse_actor(xml_text: str) -> dict[str, Any]:
    """Parse Fight Club 5e character XML into a Foundry-shaped dnd5e actor dict."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise FightClubParseError(f"Not valid XML: {exc}") from exc

    char = root.find("character") if root.tag == "pc" else (root if root.tag == "character" else None)
    if char is None:
        raise FightClubParseError(
            "This XML is not a Fight Club 5e character (expected a <pc><character> root)."
        )

    scores = _reconstruct_abilities(char)
    prof_saves, prof_skills = _proficient_saves_and_skills(char)
    cast_idx = _spellcasting_ability_index(char)
    cast_ability = ABILITY_ORDER[cast_idx] if cast_idx is not None else None

    abilities = {
        code: {"value": scores[code], "proficient": 1 if code in prof_saves else 0}
        for code in ABILITY_ORDER
    }
    skills = {
        code: {"value": 1 if code in prof_skills else 0, "ability": ability}
        for code, ability in SKILLS
    }

    cls = char.find("class")
    class_name = _child_text(cls, "name", "Adventurer") if cls is not None else "Adventurer"
    class_level = _int(_child_text(cls, "level"), 1) if cls is not None else 1

    items: list[dict[str, Any]] = []
    class_system: dict[str, Any] = {"levels": class_level, "identifier": _slugify(class_name)}
    if cast_ability:
        class_system["spellcasting"] = {"ability": cast_ability}
    items.append({"type": "class", "name": class_name, "system": class_system})

    race = char.find("race")
    if race is not None:
        items.append({"type": "race", "name": _child_text(race, "name", "Unknown"), "system": {}})
    background = char.find("background")
    if background is not None:
        items.append({"type": "background", "name": _child_text(background, "name", ""), "system": {}})

    items.extend(_build_feature_items(char))
    items.extend(_build_spell_items(char))
    items.extend(_build_inventory_items(char))

    hp_max = _int(_child_text(char, "hpMax"))
    hp_current_raw = _child_text(char, "hpCurrent")
    hp_current = _int(hp_current_raw, hp_max) if hp_current_raw else hp_max

    alignment = _child_text(background, "align") if background is not None else ""
    biography = ""
    for note in char.findall("note"):
        biography = _child_text(note, "text")
        if biography:
            break

    money = _child_text(char, "money")
    currency: dict[str, Any] = {}
    if money:
        currency = {"gp": _int(money)}

    actor: dict[str, Any] = {
        "name": _child_text(char, "name", "Character"),
        "type": "character",
        "items": items,
        "system": {
            "abilities": abilities,
            "skills": skills,
            "tools": {},
            "traits": {},
            "currency": currency,
            "attributes": {
                "hp": {"value": hp_current, "max": hp_max, "temp": 0},
                "spellcasting": cast_ability or "",
            },
            "spells": _build_spell_slots(char),
            "details": {
                "xp": {"value": _int(_child_text(char, "xp"))},
                "alignment": alignment,
                "biography": {"value": biography},
            },
        },
    }
    return actor


# --------------------------------------------------------------------------- #
# Export: Foundry-shaped actor dict -> Fight Club 5e XML
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<[^>]+>")

# Foundry item types -> Fight Club numeric type codes (best effort; the code
# mainly drives categorization in the app). Armor is handled separately.
_EXPORT_TYPE_CODES = {"weapon": "5", "consumable": "12"}


def _plain_text(html_text: str) -> str:
    """Strip HTML tags to plain text for feature/description bodies."""
    text = _TAG_RE.sub(" ", html_text or "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _elem(parent: ET.Element, tag: str, text: Any = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _weight_value(system: dict[str, Any]) -> Any:
    weight = system.get("weight")
    return weight.get("value") if isinstance(weight, dict) else weight


def to_xml(actor: dict[str, Any]) -> str:
    """Convert a Foundry-shaped dnd5e actor dict into Fight Club 5e XML.

    This is the inverse of :func:`parse_actor`, letting a Foundry (or already
    imported) character be exported back to the Lion's Den apps. It is a
    best-effort conversion — the Fight Club format cannot represent everything:

    * Final ability scores are written as the base ``<abilities>`` CSV with no
      ``<mod>`` entries, so the totals display correctly without double-counting.
    * Equipped state and weapon damage are not exported (the format does not
      model damage, and its equip encoding is ambiguous).
    """
    items = actor.get("items", [])
    system = actor.get("system", {})
    abilities = system.get("abilities", {})
    skills = system.get("skills", {})
    details = system.get("details", {}) or {}

    def items_of(*types: str) -> list[dict[str, Any]]:
        return [i for i in items if i.get("type") in types]

    pc = ET.Element("pc", version="5")
    char = ET.SubElement(pc, "character")
    _elem(char, "version", 1)
    _elem(char, "uid", 1)
    _elem(char, "name", actor.get("name", "Character"))
    _elem(char, "abilities",
          ",".join(str(_int(abilities.get(code, {}).get("value"), 10)) for code in ABILITY_ORDER) + ",")

    hp = system.get("attributes", {}).get("hp", {})
    _elem(char, "hpMax", _int(hp.get("max")))
    _elem(char, "hpCurrent", _int(hp.get("value", hp.get("max"))))
    _elem(char, "xp", _int((details.get("xp") or {}).get("value")))
    _elem(char, "unarmed", 1)

    # Race: prefer a race item, fall back to the legacy details.race string.
    race_item = next(iter(items_of("race")), None)
    race_name = (race_item.get("name") if race_item else None) or details.get("race") or "Unknown"
    race_el = _elem(char, "race")
    _elem(race_el, "name", race_name)
    for tag in ("age", "height", "weight", "eyes", "skin", "hair"):
        if details.get(tag) not in (None, ""):
            _elem(race_el, tag, details.get(tag))

    bg_item = next(iter(items_of("background")), None)
    bg_name = (bg_item.get("name") if bg_item else None) or details.get("background")
    if bg_name:
        _elem(_elem(char, "background"), "name", bg_name)

    # Class + subclass, casting, slots, proficiencies, features, spells.
    class_item = next(iter(items_of("class")), None)
    subclass_item = next(iter(items_of("subclass")), None)
    class_el = _elem(char, "class")
    _elem(class_el, "name", class_item.get("name", "Adventurer") if class_item else "Adventurer")
    level = _int(class_item.get("system", {}).get("levels"), 1) if class_item else 1
    _elem(class_el, "level", level)
    _elem(class_el, "hd", level)
    _elem(class_el, "hdCurrent", level)
    if subclass_item:
        _elem(class_el, "subclass", subclass_item.get("name", ""))

    cast = system.get("attributes", {}).get("spellcasting") or ""
    if cast in ABILITY_ORDER:
        _elem(class_el, "spellAbility", ABILITY_ORDER.index(cast))

    spells_data = system.get("spells", {})
    slots = ["0"] + [str(_int((spells_data.get(f"spell{lvl}", {}) or {}).get("value"))) for lvl in range(1, 10)]
    slots_csv = ",".join(slots) + ","
    _elem(class_el, "slots", slots_csv)
    _elem(class_el, "slotsCurrent", slots_csv)

    for code in ABILITY_ORDER:
        if abilities.get(code, {}).get("proficient"):
            _elem(class_el, "proficiency", ABILITY_ORDER.index(code))
    for code, skill in skills.items():
        if skill.get("value") and code in _SKILL_INDEX:
            _elem(class_el, "proficiency", 100 + _SKILL_INDEX[code])

    def add_feats(parent: ET.Element, feats: list[dict[str, Any]]) -> None:
        for feat in feats:
            fe = _elem(parent, "feat")
            _elem(fe, "name", feat.get("name", "Feature"))
            body = _plain_text((feat.get("system", {}).get("description", {}) or {}).get("value", ""))
            if body:
                _elem(fe, "text", body[:1500])

    all_feats = items_of("feat")
    race_feats = [f for f in all_feats if f.get("system", {}).get("type", {}).get("value") == "race"]
    class_feats = [f for f in all_feats if f.get("system", {}).get("type", {}).get("value") == "class"]
    other_feats = [f for f in all_feats if f not in race_feats and f not in class_feats]
    add_feats(race_el, race_feats)
    add_feats(class_el, class_feats)

    for spell in items_of("spell"):
        sy = spell.get("system", {})
        se = _elem(class_el, "spell")
        _elem(se, "name", spell.get("name", "Spell"))
        school_num = _SCHOOL_NUM.get(sy.get("school", ""))
        if school_num:
            _elem(se, "school", school_num)
        spell_level = _int(sy.get("level"))
        _elem(se, "level", spell_level)
        if spell_level > 0 and _int(sy.get("prepared")) >= 1:
            _elem(se, "prepared", 1)

    add_feats(char, other_feats)

    # Inventory.
    for item in items_of("equipment", "weapon", "consumable", "loot", "tool"):
        sy = item.get("system", {})
        name = item.get("name", "")
        if not name:
            continue
        ie = _elem(char, "item")
        _elem(ie, "name", name)
        armor = sy.get("armor", {}) if isinstance(sy.get("armor"), dict) else {}
        is_shield = "shield" in name.lower()
        if item.get("type") == "equipment" and armor.get("value") and not is_shield:
            _elem(ie, "type", 1)
            _elem(ie, "ac", _int(armor.get("value")))
        elif is_shield:
            _elem(ie, "type", 1)
            _elem(ie, "ac", _int(armor.get("value"), 2))
        elif item.get("type") in _EXPORT_TYPE_CODES:
            _elem(ie, "type", _EXPORT_TYPE_CODES[item["type"]])
        weight = _weight_value(sy)
        if weight:
            _elem(ie, "weight", weight)

    currency = system.get("currency", {}) or {}
    total_gp = _int(currency.get("gp")) + _int(currency.get("pp")) * 10
    if total_gp:
        _elem(char, "money", f"{total_gp:.1f}")

    ET.indent(pc, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(pc, encoding="unicode")
