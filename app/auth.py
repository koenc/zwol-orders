import functools
import logging
from flask import session, request, redirect, url_for, g
from app.config import Config

logger = logging.getLogger("zwol_orders")


def get_current_user():
    """Haalt de huidige ingelogde gebruiker op uit headers of sessie."""
    # 1. Dev Bypass
    if Config.AUTH_BYPASS_FOR_DEV:
        return {
            "email": f"brouwer@{Config.AUTH_DOMAIN}",
            "name": "Brouwer ZWOL (Dev)",
            "is_dev": True
        }

    # 2. Cloudflare Access Header authenticatie
    # Cloudflare Access stuurt dit betrouwbaar mee na Microsoft 365 login
    cf_email = request.headers.get("Cf-Access-Authenticated-User-Email") or request.headers.get("X-Forwarded-Email")
    if cf_email:
        cf_email = cf_email.strip().lower()
        if cf_email.endswith(f"@{Config.AUTH_DOMAIN}"):
            user = {
                "email": cf_email,
                "name": cf_email.split("@")[0].replace(".", " ").title(),
                "is_dev": False
            }
            session["user"] = user
            return user
        else:
            logger.warning(f"Toegang geweigerd: E-mail {cf_email} hoort niet bij domein @{Config.AUTH_DOMAIN}")
            return None

    # 3. Bestaande gebruikerssessie
    user = session.get("user")
    if user and isinstance(user, dict):
        email = user.get("email", "").lower()
        if email.endswith(f"@{Config.AUTH_DOMAIN}"):
            return user

    return None


def login_required(f):
    """Decorator die controleert of de gebruiker geauthenticeerd is met een @brouwerijzwol.nl account."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("login", next=request.url))
        g.user = user
        return f(*args, **kwargs)
    return decorated_function
