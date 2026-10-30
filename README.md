# Westlandse Bierbrouwerij ZWOL - Orders App

Een simpele, snelle, zeer gebruiksvriendelijke mobiele webapplicatie (PWA) bovenop **Silvasoft**, speciaal ontworpen voor het invoeren van bierorders, het bekijken van orders per week op een horizontaal Trello-achtig bord, en het direct afvinken van orders als **Geleverd**.

---

## 🍺 Functionaliteiten

1. **Order Aanmaken (Mobile-First):**
   * Snelle klantenselectie met realtime autocomplete (zoeken op bedrijfsnaam of plaats).
   * Automatische orderdatum (vandaag) en flexibele leverdatum (met snelle sneltoets-chips: *Vandaag*, *Morgen*, *A.s. Vrijdag*, *Volgende Week*).
   * Automatisch meebewegende referentie (`Levering DD-MM-YYYY`).
   * Alleen ZWOL-bieren tonen waar in Silvasoft het custom veld `Tonen in ZWOL order app` op `true` staat.
   * Grote, duimvriendelijke `[-]` en `[+]` steppers per bier.

2. **Lijst Orders Bekijken (Week Kanban):**
   * Alle orders met status **"Bevestigd"**.
   * Gegroepeerd in kolommen per **Kalenderweek** op basis van leverdatum.
   * Soepel horizontaal scrollen (`scroll-snap`) op smartphones.
   * Weken zonder openstaande orders worden automatisch verborgen.
   * Overzichtskaartjes met klantnaam, compacte afkortingenregel (bijv. `1x ZS, 3x BM, 2x OG`) en leverdatum.

3. **Order Openen & Afvinken:**
   * Detailvenster (Mobile Bottom Sheet) met bedrijfsnaam, contactpersoon, adres en telefoonnummer.
   * Directe **📞 Bellen** knop (`tel:...`) en **🗺️ Navigeer** knop (Google / Apple Maps).
   * Uitgebreide specificatie van alle bestelde artikelen en aantallen.
   * Grote actieknop: **✅ Markeer als Geleverd** (werkt status direct bij in Silvasoft via `PUT rest/updateorder/`).

---

## 🏛️ Architectuur & Database

* **Backend:** Python 3.11 met Flask & Gunicorn.
* **Database:** MariaDB 10 op de Synology NAS (`127.0.0.1:3307`), database **`zwol`**, tabellen met prefix **`ordersystem_`**:
  * `ordersystem_customers`: Klantengegevens voor directe 0ms autocomplete.
  * `ordersystem_products`: Bieren met vlag `show_in_order_app` en afkorting `short_name`.
  * `ordersystem_orders`: Openstaande en historische orders gecachet voor snelle weergave.
  * `ordersystem_sync_log`: Logboek van achtergrondsynchronisaties met Silvasoft.
* **Fallback:** Automatische overschakeling naar lokaal SQLite (`data/zwol_orders.db`) bij lokaal ontwikkelen zonder actieve NAS-verbinding.
* **Back-up:** Automatisch opgenomen in [Ketelhuis Database Backup](file:///c:/Users/koen/OneDrive/Anti-gravity/Ketelhuis%20Database%20Backup) via `DB_NAME=ketelhuis,zwol`.

---

## 🚀 Installatie & Deployment op Synology NAS

De app is geconfigureerd om te draaien in `/volume1/docker/zwol-orders` op de Synology NAS via Docker Compose.

### 1. Bestanden klaarzetten op de NAS
Kopieer of clone de repository naar:
```bash
/volume1/docker/zwol-orders
```

### 2. `.env` configureren
Kopieer `.env.example` naar `.env`:
```bash
cp .env.example .env
```
Vul de gegevens in:
* `DB_HOST=127.0.0.1`
* `DB_PORT=3307`
* `DB_NAME=zwol`
* `DB_USER=ketelhuis`
* `DB_PASSWORD=HeinekenStinkt123#`
* `SILVASOFT_USERNAME=info@brouwerijzwol.nl`
* `SILVASOFT_API_KEY=...`
* `CLOUDFLARE_TUNNEL_TOKEN=...` (jouw Cloudflare tunnel token gekoppeld aan `orders.brouwerijzwol.nl`)

### 3. Container starten via Docker Compose
In de map `/volume1/docker/zwol-orders`:
```bash
docker-compose up -d --build
```

---

## 🔒 Beveiliging & Cloudflare Tunnel

* **Cloudflare Tunnel:** Verbindt `orders.brouwerijzwol.nl` direct met poort `8503` op de NAS.
* **Authenticatie:** Beveiligd met Microsoft 365 via Cloudflare Access. Alleen gebruikers met een `@brouwerijzwol.nl` e-mailadres krijgen toegang.
