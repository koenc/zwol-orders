import os
import re
import json
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
from app.config import Config
from app.database import get_db, get_all_settings

logger = logging.getLogger("zwol_orders")

STATIC_PRODUCTS_DIR = Path(Config.BASE_DIR) / "app" / "static" / "img" / "products"

# Vaste volgorde van groepen voor weergave
STANDARD_GROUP_ORDER = [
    "Horeca",
    "Retail",
    "Supermarkt",
    "Distributeur",
    "Consument",
    "B2B",
    "Verhuur-Catering",
    "Geschenken-business",
    "Standaard"
]

CATEGORY_ORDER = [
    ("Bier in fles", "bottle"),
    ("Bier in fust", "keg"),
    ("Glaswerk & Promotie", "glass"),
    ("Geschenken & Pakketten", "gift"),
    ("Verpakkingsmateriaal", "package"),
    ("Overig", "box")
]


def extract_pieces(unit_str: str, name_str: str) -> int:
    """Berekent het aantal stuks per verpakking uit de unit of naam (bijv. 24x33cl -> 24)."""
    text = f"{unit_str} {name_str}".lower()
    # Zoek patronen zoals '24 stuks', '24x', '6 stuks', '6x'
    m = re.search(r'(\d+)\s*stuks', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*x', text)
    if m:
        return int(m.group(1))
    return 1


class PriceListService:
    @staticmethod
    def get_or_create_thumbnail(art_no: str) -> Optional[str]:
        """
        Controleert of er een productafbeelding voor art_no is, en maakt/retourneert
        een geoptimaliseerde thumbnail (128x128) zodat HTML en PDF razendsnel en compact blijven.
        Retourneert het relatieve pad t.o.v. static/img/products/ (bijv. 'thumbs/12359.png') of None.
        """
        art_no = str(art_no).strip()
        source_file = None
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            cand = STATIC_PRODUCTS_DIR / f"{art_no}{ext}"
            if cand.exists():
                source_file = cand
                break

        if not source_file:
            return None

        thumbs_dir = STATIC_PRODUCTS_DIR / "thumbs"
        thumb_path = thumbs_dir / f"{art_no}.png"

        try:
            # Check of thumbnail al up-to-date is t.o.v. het bronbestand
            if thumb_path.exists() and thumb_path.stat().st_mtime >= source_file.stat().st_mtime:
                return f"thumbs/{art_no}.png"

            thumbs_dir.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            with Image.open(source_file) as im:
                if im.mode not in ("RGBA", "RGB"):
                    im = im.convert("RGBA")
                im.thumbnail((128, 128), Image.Resampling.LANCZOS)
                im.save(thumb_path, format="PNG", optimize=True)
            return f"thumbs/{art_no}.png"
        except Exception as e:
            logger.warning(f"Kon thumbnail niet genereren voor {art_no}: {e}")
            return source_file.name

    @staticmethod
    def get_available_groups() -> List[str]:
        """Geeft alle unieke prijsgroepen terug die voorkomen in actieve producten."""
        prefix = Config.DB_TABLE_PREFIX
        groups_set = set()
        with get_db() as db:
            rows = db.fetchall(f"SELECT prices_json FROM {prefix}products WHERE show_in_order_app = 1")
            for r in rows:
                p_json = r.get("prices_json")
                if p_json:
                    try:
                        p_dict = json.loads(p_json)
                        for g, val in p_dict.items():
                            if val and float(val) > 0:
                                groups_set.add(g)
                    except Exception:
                        pass

        # Sorteer volgens STANDARD_GROUP_ORDER, daarna rest alfabetisch
        ordered = [g for g in STANDARD_GROUP_ORDER if g in groups_set]
        for g in sorted(groups_set):
            if g not in ordered:
                ordered.append(g)
        return ordered

    @staticmethod
    def get_price_list_data(group_name: str) -> Dict[str, Any]:
        """Verzamelt alle producten en instellingen voor een specifieke prijsgroep."""
        prefix = Config.DB_TABLE_PREFIX
        settings = get_all_settings()

        with get_db() as db:
            rows = db.fetchall(f"""
                SELECT article_number, name, short_name, category, price, vat_percentage,
                       unit, beer_type, alcohol_pct, description, prices_json
                FROM {prefix}products
                WHERE show_in_order_app = 1
                ORDER BY category ASC, name ASC
            """)

        filtered_products = []
        for r in rows:
            prices_dict = {}
            if r.get("prices_json"):
                try:
                    prices_dict = json.loads(r["prices_json"])
                except Exception:
                    pass

            # Controleer of er een prijs voor deze groep is
            group_price = prices_dict.get(group_name)
            if group_price is None or float(group_price) <= 0:
                continue

            art_no = str(r["article_number"]).strip()
            total_price = float(group_price)

            # Check of lokale afbeelding bestaat en zorg voor een geoptimaliseerde thumbnail
            thumb_rel = PriceListService.get_or_create_thumbnail(art_no)
            has_image = thumb_rel is not None

            # Verpakking & stuks berekenen
            unit = r.get("unit") or "Stuks"
            pcs = extract_pieces(unit, r.get("name") or "")
            piece_price = round(total_price / pcs, 2) if pcs > 1 else None

            # Categorie normaliseren
            raw_cat = (r.get("category") or "").strip()
            if "fles" in raw_cat.lower():
                cat_name = "Bier in fles"
            elif "fust" in raw_cat.lower():
                cat_name = "Bier in fust"
            elif "glas" in raw_cat.lower():
                cat_name = "Glaswerk & Promotie"
            elif "pakket" in raw_cat.lower() or "krat" in raw_cat.lower() or "geschenk" in raw_cat.lower():
                cat_name = "Geschenken & Pakketten"
            else:
                cat_name = raw_cat or "Overig"

            # Alcoholpercentage formattering
            alc_val = r.get("alcohol_pct")
            alc_str = ""
            if alc_val is not None:
                try:
                    f_alc = float(alc_val)
                    if f_alc > 0:
                        alc_str = f"{f_alc:.1f}%".replace(".", ",")
                except Exception:
                    pass

            filtered_products.append({
                "article_number": art_no,
                "name": r.get("name"),
                "short_name": r.get("short_name"),
                "category": cat_name,
                "beer_type": r.get("beer_type") or "",
                "alcohol_pct": alc_str,
                "description": r.get("description") or "",
                "unit": unit,
                "pcs": pcs,
                "total_price": total_price,
                "piece_price": piece_price,
                "vat_percentage": float(r.get("vat_percentage") or 21.0),
                "has_image": has_image,
                "image_filename": thumb_rel
            })

        # Groepeer per categorie volgens CATEGORY_ORDER en sorteer alfabetisch op naam
        categories_dict = {}
        for p in filtered_products:
            c = p["category"]
            if c not in categories_dict:
                categories_dict[c] = []
            categories_dict[c].append(p)

        # Sorteer artikelen binnen elke categorie strikt alfabetisch op naam
        for c in categories_dict:
            categories_dict[c].sort(key=lambda x: (x["name"] or "").strip().lower())

        categorized_list = []
        for cat_name, icon in CATEGORY_ORDER:
            if cat_name in categories_dict and len(categories_dict[cat_name]) > 0:
                categorized_list.append({
                    "name": cat_name,
                    "icon": icon,
                    "products": categories_dict[cat_name]
                })

        # Eventuele overige categorieën toevoegen
        for cat_name, prods in categories_dict.items():
            if not any(c["name"] == cat_name for c in categorized_list):
                prods.sort(key=lambda x: (x["name"] or "").strip().lower())
                categorized_list.append({
                    "name": cat_name,
                    "icon": "box",
                    "products": prods
                })

        return {
            "group_name": group_name,
            "available_groups": PriceListService.get_available_groups(),
            "categories": categorized_list,
            "total_products": len(filtered_products),
            "settings": settings
        }

    @staticmethod
    def render_pdf(html_content: str, base_url: Optional[str] = None) -> bytes:
        """Genereert een PDF uit HTML via WeasyPrint met FontConfiguration voor lokale typografie."""
        try:
            from weasyprint import HTML
            try:
                from weasyprint.text.fonts import FontConfiguration
                font_config = FontConfiguration()
            except ImportError:
                try:
                    from weasyprint.fonts import FontConfiguration
                    font_config = FontConfiguration()
                except ImportError:
                    font_config = None

            html = HTML(string=html_content, base_url=base_url)
            kwargs = {}
            if font_config:
                kwargs["font_config"] = font_config

            try:
                return html.write_pdf(optimize_images=True, **kwargs)
            except (TypeError, Exception):
                return html.write_pdf(**kwargs)
        except ImportError:
            raise RuntimeError("WeasyPrint is niet geïnstalleerd. Installeer weasyprint om PDF's te genereren.")
        except Exception as e:
            logger.error(f"Fout bij PDF generatie via WeasyPrint: {e}")
            raise RuntimeError(f"Fout bij PDF generatie: {e}")

