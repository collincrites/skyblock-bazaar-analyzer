import os
import requests
import json
import base64
import gzip
import io
import re

try:
    from nbt import nbt
except ImportError:
    nbt = None

HYPIXEL_API_KEY = os.getenv("HYPIXEL_API_KEY")
MINECRAFT_USERNAME = os.getenv("MINECRAFT_USERNAME")


def get_uuid(username):
    data = requests.get(
        f"https://api.mojang.com/users/profiles/minecraft/{username}",
        timeout=10
    ).json()
    return data["id"]


def get_profiles(uuid):
    return requests.get(
        "https://api.hypixel.net/v2/skyblock/profiles",
        headers={"API-Key": HYPIXEL_API_KEY},
        params={"uuid": uuid},
        timeout=20
    ).json()


def get_selected_profile(data):
    for profile in data.get("profiles", []):
        if profile.get("selected"):
            return profile
    return None


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"§.", "", str(text))


def tag_value(tag):
    try:
        return tag.value
    except Exception:
        return tag


def get_tag(compound, key):
    try:
        return compound[key]
    except Exception:
        return None


def decode_inventory(data):
    if not nbt or not data:
        return []

    try:
        raw = base64.b64decode(data)
        decompressed = gzip.decompress(raw)
        nbt_file = nbt.NBTFile(fileobj=io.BytesIO(decompressed))
        items = []

        for item in nbt_file["i"]:
            if not item:
                continue

            item_info = {
                "name": "Unknown Item",
                "id": "UNKNOWN",
                "enchants": {},
                "rarity": "",
                "stars": 0,
                "recomb": False,
            }

            tag = get_tag(item, "tag")
            if not tag:
                continue

            display = get_tag(tag, "display")
            if display:
                name_tag = get_tag(display, "Name")
                lore_tag = get_tag(display, "Lore")

                if name_tag:
                    item_info["name"] = clean_text(tag_value(name_tag))

                if lore_tag:
                    lore = "\n".join(clean_text(tag_value(x)) for x in lore_tag)
                    item_info["stars"] = lore.count("✪")
                    item_info["recomb"] = "Recombobulated" in lore

            extra = get_tag(tag, "ExtraAttributes")
            if extra:
                item_id = get_tag(extra, "id")
                if item_id:
                    item_info["id"] = str(tag_value(item_id))

                enchants = get_tag(extra, "enchantments")
                if enchants:
                    for enchant in enchants.tags:
                        item_info["enchants"][enchant.name] = tag_value(enchant)

            items.append(item_info)

        return items

    except Exception as e:
        print(f"Inventory decode failed: {e}")
        return []


def find_inventory_blobs(member):
    blobs = []

    def walk(obj, path="member"):
        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{path}.{key}"
                if key == "data" and isinstance(value, str):
                    blobs.append((path, value))
                else:
                    walk(value, new_path)
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")

    walk(member)
    return blobs


def print_items(title, items, keywords=None, limit=30):
    print(f"\n===== {title} =====")

    filtered = []

    for item in items:
        text = f"{item['name']} {item['id']}".lower()

        if keywords:
            if not any(word.lower() in text for word in keywords):
                continue

        filtered.append(item)

    if not filtered:
        print("None found")
        return

    for item in filtered[:limit]:
        enchants = item.get("enchants", {})
        enchant_text = ""

        if enchants:
            best = list(enchants.items())[:8]
            enchant_text = " | Enchants: " + ", ".join(f"{k} {v}" for k, v in best)

        recomb = " | Recombed" if item.get("recomb") else ""
        stars = f" | Stars: {item.get('stars')}" if item.get("stars") else ""

        print(f"- {item['name']} [{item['id']}]{stars}{recomb}{enchant_text}")


def print_pets(member):
    pets = member.get("pets_data", {}).get("pets", [])

    print("\n===== PETS =====")

    if not pets:
        print("No pets found or pet API disabled.")
        return

    pets_sorted = sorted(
        pets,
        key=lambda p: (p.get("active", False), p.get("exp", 0)),
        reverse=True
    )

    for pet in pets_sorted[:25]:
        active = "ACTIVE" if pet.get("active") else ""
        held = pet.get("heldItem", "")
        candy = pet.get("candyUsed", 0)

        print(
            f"- {pet.get('tier')} {pet.get('type')} "
            f"XP: {pet.get('exp', 0):,.0f} "
            f"{active} Held: {held} Candy: {candy}"
        )


def print_profile_stats(profile, member):
    print("\n==============================")
    print(" SKYBLOCK GEAR ADVISOR")
    print("==============================")

    print(f"Profile: {profile.get('cute_name')}")
    print(f"Purse: {member.get('currencies', {}).get('coin_purse', 0):,.0f}")

    bank = profile.get("banking", {}).get("balance")
    if bank is not None:
        print(f"Bank: {bank:,.0f}")

    dungeons = member.get("dungeons", {})
    cata_xp = dungeons.get("dungeon_types", {}).get("catacombs", {}).get("experience", 0)
    selected_class = dungeons.get("selected_dungeon_class", "unknown")

    print("\n===== DUNGEONS =====")
    print(f"Selected class: {selected_class}")
    print(f"Catacombs XP: {cata_xp:,.0f}")

    class_xp = dungeons.get("player_classes", {})
    for class_name, data in class_xp.items():
        print(f"- {class_name}: {data.get('experience', 0):,.0f} XP")

    mining = member.get("mining_core", {})

    print("\n===== MINING =====")
    print(f"HOTM XP: {mining.get('experience', 0):,.0f}")
    print(f"Mithril Powder: {mining.get('powder_mithril', 0):,.0f}")
    print(f"Gemstone Powder: {mining.get('powder_gemstone', 0):,.0f}")
    print(f"Glacite Powder: {mining.get('powder_glacite', 0):,.0f}")


def print_advice(all_items, member):
    all_text = " ".join((item["name"] + " " + item["id"]).lower() for item in all_items)

    print("\n==============================")
    print(" ADVICE")
    print("==============================")

    print("\nDungeon Mage:")
    if "hyperion" in all_text:
        print("- You have/own a Hyperion-type setup. Focus on Cata level, survivability, and utility.")
    elif "midas staff" in all_text:
        print("- Midas Staff is good damage, but Spirit Sceptre clearing or Hyperion later will feel smoother.")
    elif "spirit sceptre" in all_text:
        print("- Spirit Sceptre is good for your stage. Next: better armor, goggles, pet, and Cata levels.")
    else:
        print("- Get/keep a reliable mage weapon: Spirit Sceptre → Midas Staff/Yeti Sword → Hyperion later.")

    if "sheep" in str(member.get("pets_data", {})).lower():
        print("- Sheep pet found. Use it for mage damage.")
    else:
        print("- Consider a Legendary Sheep pet for mage damage.")

    if "blue whale" in str(member.get("pets_data", {})).lower():
        print("- Blue Whale found. Use it when dying.")
    else:
        print("- Consider Blue Whale if survivability is your issue.")

    print("\nMining:")
    if "gemstone gauntlet" in all_text:
        print("- Gemstone Gauntlet found. Focus powder and HOTM progression.")
    elif "mithril drill" in all_text:
        print("- Mithril Drill found. You are still early mining. Prioritize HOTM/powder before dumping coins.")
    else:
        print("- Mining gear not clearly found. Early path: HOTM → powder → Gemstone Gauntlet → Divan.")

    print("\nGeneral:")
    print("- Do not spend your full 900M on one setup until you know you enjoy that method.")
    print("- Since your AH/Bazaar bots are running, run dungeons while alerts work passively.")


def main():
    if not HYPIXEL_API_KEY or not MINECRAFT_USERNAME:
        print("Missing HYPIXEL_API_KEY or MINECRAFT_USERNAME")
        return

    if not nbt:
        print("Missing NBT library. Run:")
        print("pip install nbt")
        return

    uuid = get_uuid(MINECRAFT_USERNAME)
    data = get_profiles(uuid)

    if not data.get("success"):
        print("Hypixel API error:")
        print(json.dumps(data, indent=2))
        return

    profile = get_selected_profile(data)

    if not profile:
        print("No selected profile found.")
        return

    member = profile["members"].get(uuid)

    if not member:
        print("Could not find member data.")
        return

    print_profile_stats(profile, member)
    print_pets(member)

    blobs = find_inventory_blobs(member)
    all_items = []

    print("\n===== INVENTORY SOURCES FOUND =====")
    for path, blob in blobs:
        decoded = decode_inventory(blob)
        if decoded:
            print(f"- {path}: {len(decoded)} items")
            all_items.extend(decoded)

    print_items("ARMOR / DUNGEON GEAR", all_items, [
        "helmet", "chestplate", "leggings", "boots",
        "storm", "necromancer", "wise", "shadow assassin",
        "wither goggles", "goggles"
    ])

    print_items("WEAPONS", all_items, [
        "sword", "staff", "sceptre", "hyperion", "midas",
        "juju", "terminator", "bow", "wand", "dagger"
    ])

    print_items("MINING GEAR", all_items, [
        "drill", "gauntlet", "pickaxe", "divan", "sorrow",
        "goblin", "mineral", "titanium"
    ])

    print_items("EQUIPMENT / UTILITY", all_items, [
        "necklace", "cloak", "belt", "gloves", "wand",
        "orb", "aote", "aspect of the end", "aspect of the void"
    ])

    print_advice(all_items, member)


if __name__ == "__main__":
    main()