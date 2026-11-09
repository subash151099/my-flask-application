import base64
import binascii
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from datetime import date, timedelta, datetime
from functools import wraps
from urllib.parse import urlencode, urlsplit

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, g, jsonify, send_file, send_from_directory, abort
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "irumanam.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("IRUMANAM_SECRET_KEY", "dev-only-change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PUBLIC_BASE_URL"] = os.environ.get("IRUMANAM_PUBLIC_BASE_URL", "").rstrip("/")
app.config["GOOGLE_SITE_VERIFICATION"] = os.environ.get("GOOGLE_SITE_VERIFICATION", "")
app.config["GOOGLE_ANALYTICS_ID"] = os.environ.get("GOOGLE_ANALYTICS_ID", "")
app.config["TRUSTED_HOSTS"] = (
    [urlsplit(app.config["PUBLIC_BASE_URL"]).netloc]
    if app.config["PUBLIC_BASE_URL"] else None
)
_FEATURE_SCHEMA_READY = False

SEO_PAGES = {
    "index": {
        "title": "Tamil Matrimony | Find Your Life Partner | Irumanam",
        "description": (
            "Find compatible Tamil matrimony matches on Irumanam. Discover profiles, "
            "explore your preferences, and take the next step toward a meaningful relationship."
        ),
        "keywords": "Tamil matrimony, Tamil marriage, matrimony profiles, life partner, Irumanam",
        "path": "/",
        "language": "en-IN",
    },
    "login": {
        "title": "Member Login | Irumanam",
        "description": "Sign in to your Irumanam matrimony account.",
        "keywords": "Irumanam login, Tamil matrimony account",
        "path": "/login",
        "language": "en-IN",
    },
    "register": {
        "title": "Create a Matrimony Profile | Irumanam",
        "description": "Create your Irumanam profile and start your search for a compatible life partner.",
        "keywords": "Tamil matrimony registration, create matrimony profile, Irumanam",
        "path": "/register",
        "language": "en-IN",
    },
    "tamil_home": {
        "title": "தமிழ் திருமண தகவல் மையம் | இருமணம்",
        "description": (
            "இருமணம் தமிழ் திருமண தளத்தில் உங்கள் வாழ்க்கைத் துணையைத் தேடுங்கள். "
            "விருப்பங்களுக்கு ஏற்ற சுயவிவரங்களைப் பார்த்து, உங்கள் திருமணப் பயணத்தைத் தொடங்குங்கள்."
        ),
        "keywords": "தமிழ் திருமண தகவல் மையம், தமிழ் திருமணம், வாழ்க்கைத் துணை, இருமணம்",
        "path": "/ta",
        "language": "ta-IN",
    },
}

SEO_CANONICAL_ENDPOINTS = frozenset(SEO_PAGES)
SEO_INDEXABLE_ENDPOINTS = frozenset({"index", "tamil_home"})


def public_url(path):
    base_url = app.config["PUBLIC_BASE_URL"] or request.url_root.rstrip("/")
    return f"{base_url}/{path.lstrip('/')}"


@app.context_processor
def inject_seo_metadata():
    page = SEO_PAGES.get(request.endpoint, {})
    is_indexable = (
        request.endpoint in SEO_INDEXABLE_ENDPOINTS
        and not session.get("user_id")
    )
    canonical_url = public_url(page["path"]) if request.endpoint in SEO_CANONICAL_ENDPOINTS else ""
    google_verification = app.config["GOOGLE_SITE_VERIFICATION"]
    analytics_id = app.config["GOOGLE_ANALYTICS_ID"]
    if not re.fullmatch(r"G-[A-Z0-9]+", analytics_id):
        analytics_id = ""
    structured_data = []
    if request.endpoint in ("index", "tamil_home") and not session.get("user_id"):
        site_url = canonical_url
        structured_data = [
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": "Irumanam",
                "url": site_url,
                "inLanguage": page["language"],
            },
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Irumanam",
                "url": site_url,
                "logo": public_url(url_for("static", filename="images/irumanam-logo.png")),
            },
            {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": page["title"],
                "description": page["description"],
                "url": site_url,
                "inLanguage": page["language"],
                "isPartOf": {"@id": f"{public_url('/')}#website"},
                "publisher": {"@id": f"{public_url('/')}#organization"},
            },
        ]
        structured_data[0]["@id"] = f"{public_url('/')}#website"
        structured_data[1]["@id"] = f"{public_url('/')}#organization"
        if getattr(g, "seo_faqs", None):
            structured_data.append({
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": faq["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": faq["answer"],
                        },
                    }
                    for faq in g.seo_faqs
                ],
            })
    share_image = public_url(url_for("static", filename="images/irumanam-logo.png"))
    return {
        "seo_title": page.get("title", "Irumanam | Matrimony and Life Partner Search"),
        "seo_description": page.get("description", "Discover Irumanam, a matrimony platform for finding a compatible life partner."),
        "seo_keywords": page.get("keywords", "Irumanam, matrimony, life partner"),
        "seo_robots": (
            "index,follow"
            if is_indexable
            else "noindex,follow"
            if request.endpoint in ("login", "register")
            else "noindex,nofollow"
        ),
        "seo_canonical": canonical_url,
        "seo_structured_data": structured_data,
        "seo_share_image": share_image,
        "seo_language": page.get("language", "en"),
        "seo_locale": page.get("language", "en-IN").replace("-", "_"),
        "seo_alternates": (
            {
                "en-IN": public_url("/"),
                "ta-IN": public_url("/ta"),
                "x-default": public_url("/"),
            }
            if request.endpoint in ("index", "tamil_home")
            else {}
        ),
        "google_site_verification": google_verification,
        "google_analytics_id": analytics_id,
    }


@app.before_request
def protect_state_changes():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        submitted_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not submitted_token or not hmac.compare_digest(token, submitted_token):
            abort(400, description="Your session token is missing or expired. Reload the page and try again.")


DEFAULT_FAQS = (
    ("How do I register and create a profile on Irumanam?",
     'Click on the "Create Your Profile" button on the homepage, enter your basic account details, and complete your registration. Once registered, you can complete your profile preferences, upload photos, and start discovering matches.'),
    ("Is my personal information and photo safe?",
     "Yes, privacy and security are our top priorities. Your sensitive personal data is protected, and you retain control over who can view your full details or express interest in your profile."),
    ('How does "Express Interest" work?',
     "When you find a profile you like, click the \"Express Interest\" button. The other member will be notified of your interest, and once they accept, you can connect further."),
    ("Are profiles verified?",
     "We perform profile checks and encourage members to verify their accounts using official identification to ensure a safe and genuine matchmaking environment."),
)

ADMIN_PERMISSIONS = {
    "dashboard": "Dashboard",
    "members": "Member management",
    "payments": "Premium payments",
    "support": "Support conversations",
    "keys": "Keyword auto-replies",
    "faqs": "FAQs",
    "notifications": "Notifications",
    "reports": "Reports and exports",
    "activity": "Activity and login history",
    "advertisements": "Login advertisements",
}

ADMIN_ENDPOINT_PERMISSIONS = {
    "admin_dashboard": "dashboard",
    "admin_view_profile": "members",
    "admin_profile_action": "members",
    "admin_users": "members",
    "admin_user_edit": "members",
    "admin_user_action": "members",
    "admin_premium_payments": "payments",
    "admin_payment_screenshot": "payments",
    "admin_review_premium_payment": "payments",
    "admin_support": "support",
    "admin_support_conversation": "support",
    "admin_support_messages": "support",
    "admin_support_auto_replies": "keys",
    "admin_support_auto_reply_delete": "keys",
    "admin_faqs": "faqs",
    "admin_faq_delete": "faqs",
    "admin_notifications": "notifications",
    "admin_notifications_poll": "notifications",
    "admin_open_notification": "notifications",
    "admin_reports": "reports",
    "admin_reports_export": "reports",
    "admin_reports_delete": "support",
    "admin_reports_xlsx": "reports",
    "admin_activity": "activity",
    "admin_accounts": "admins",
    "admin_account_action": "admins",
    "admin_advertisements": "advertisements",
    "admin_advertisement_form": "advertisements",
    "admin_advertisement_action": "advertisements",
    "admin_advertisement_image": "advertisements",
    "admin_advertisement_history_image": "advertisements",
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10, cached_statements=256)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA busy_timeout = 10000")
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def _ensure_feature_tables(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS profile_album_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        filename TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_profile_album_photos_user
        ON profile_album_photos(user_id, id);
    CREATE TABLE IF NOT EXISTS faqs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS support_conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        visitor_token TEXT NOT NULL UNIQUE,
        visitor_name TEXT NOT NULL DEFAULT 'Website visitor',
        visitor_email TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS support_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        sender_role TEXT NOT NULL CHECK(sender_role IN ('visitor', 'admin')),
        sender_admin_id INTEGER,
        body TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        is_automated INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(conversation_id) REFERENCES support_conversations(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS support_auto_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT NOT NULL COLLATE NOCASE UNIQUE,
        reply TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS admin_activity_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        target_url TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS feature_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_login_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        admin_name TEXT NOT NULL,
        admin_email TEXT NOT NULL,
        event_type TEXT NOT NULL CHECK(event_type IN ('login', 'logout')),
        ip_address TEXT NOT NULL DEFAULT '',
        user_agent TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS admin_activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        admin_name TEXT NOT NULL,
        action TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS blocks (
        blocker_id INTEGER NOT NULL,
        blocked_id INTEGER NOT NULL,
        reason TEXT DEFAULT '',
        UNIQUE(blocker_id, blocked_id)
    );
    CREATE TABLE IF NOT EXISTS advertisements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        redirect_url TEXT NOT NULL DEFAULT '',
        image_path TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        display_days INTEGER NOT NULL,
        target_audience TEXT NOT NULL CHECK(target_audience IN (
            'ALL', 'FREE', 'PREMIUM', 'MALE', 'FEMALE', 'NEW', 'SELECTED'
        )),
        display_frequency TEXT NOT NULL CHECK(display_frequency IN (
            'EVERY_LOGIN', 'DAILY', 'ONCE'
        )),
        is_enabled INTEGER NOT NULL DEFAULT 0,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER NOT NULL,
        created_by_name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        published_at TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS advertisement_audience_users (
        advertisement_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        PRIMARY KEY(advertisement_id, user_id),
        FOREIGN KEY(advertisement_id) REFERENCES advertisements(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS advertisement_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        advertisement_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        redirect_url TEXT NOT NULL DEFAULT '',
        image_path TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        display_days INTEGER NOT NULL,
        target_audience TEXT NOT NULL,
        selected_users TEXT NOT NULL DEFAULT '[]',
        display_frequency TEXT NOT NULL,
        is_enabled INTEGER NOT NULL,
        is_deleted INTEGER NOT NULL,
        created_by_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        published_at TEXT,
        action TEXT NOT NULL,
        changed_by INTEGER NOT NULL,
        changed_by_name TEXT NOT NULL,
        changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(advertisement_id) REFERENCES advertisements(id)
    );
    CREATE TABLE IF NOT EXISTS advertisement_impressions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        advertisement_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        frequency_key TEXT NOT NULL,
        shown_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_at TEXT,
        UNIQUE(advertisement_id, user_id, frequency_key),
        FOREIGN KEY(advertisement_id) REFERENCES advertisements(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE INDEX IF NOT EXISTS idx_advertisements_schedule
        ON advertisements(is_enabled, is_deleted, start_date, end_date);
    CREATE INDEX IF NOT EXISTS idx_advertisement_impressions_ad
        ON advertisement_impressions(advertisement_id, shown_at);
    CREATE INDEX IF NOT EXISTS idx_advertisement_history_ad
        ON advertisement_history(advertisement_id, changed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_support_messages_conversation
        ON support_messages(conversation_id, id);
    CREATE INDEX IF NOT EXISTS idx_admin_notifications_unread
        ON admin_activity_notifications(is_read, id DESC);
    CREATE INDEX IF NOT EXISTS idx_admin_login_logs_created
        ON admin_login_logs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_admin_activity_logs_created
        ON admin_activity_logs(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_blocks_blocked_id
        ON blocks(blocked_id, blocker_id);
    CREATE INDEX IF NOT EXISTS idx_users_approval_created
        ON users(is_approved, is_admin, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_profiles_city
        ON profiles(city);
    CREATE INDEX IF NOT EXISTS idx_profiles_religion
        ON profiles(religion);
    CREATE INDEX IF NOT EXISTS idx_profiles_mother_tongue
        ON profiles(mother_tongue);
    CREATE INDEX IF NOT EXISTS idx_interests_sender_type_created
        ON interests(sender_id, interest_type, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_interests_receiver_type_created
        ON interests(receiver_id, interest_type, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_views_viewed_at
        ON views(viewed_id, viewed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_receiver_read
        ON messages(receiver_id, is_read, sender_id);
    CREATE INDEX IF NOT EXISTS idx_messages_sender_receiver_id
        ON messages(sender_id, receiver_id, id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_receiver_sender_id
        ON messages(receiver_id, sender_id, id DESC);
    """)
    advertisement_history_columns = {
        row[1] for row in db.execute("PRAGMA table_info(advertisement_history)")
    }
    if "selected_users" not in advertisement_history_columns:
        db.execute(
            "ALTER TABLE advertisement_history "
            "ADD COLUMN selected_users TEXT NOT NULL DEFAULT '[]'"
        )
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "admin_role" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN admin_role TEXT NOT NULL DEFAULT 'ADMIN'")
    if "admin_permissions" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN admin_permissions TEXT NOT NULL DEFAULT 'dashboard'")
    if "admin_active" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN admin_active INTEGER NOT NULL DEFAULT 1")
    admins_seeded = db.execute(
        "SELECT setting_value FROM feature_settings WHERE setting_key='admin_roles_seeded'"
    ).fetchone()
    if not admins_seeded:
        db.execute(
            "UPDATE users SET admin_role='SUPER_ADMIN', admin_permissions=? WHERE is_admin=1",
            (",".join(ADMIN_PERMISSIONS),)
        )
        db.execute(
            "INSERT INTO feature_settings (setting_key, setting_value) VALUES ('admin_roles_seeded', '1')"
        )
    support_message_columns = {
        row[1] for row in db.execute("PRAGMA table_info(support_messages)").fetchall()
    }
    if "is_automated" not in support_message_columns:
        db.execute(
            "ALTER TABLE support_messages ADD COLUMN is_automated INTEGER NOT NULL DEFAULT 0"
        )
    if "sender_admin_id" not in support_message_columns:
        db.execute("ALTER TABLE support_messages ADD COLUMN sender_admin_id INTEGER")
    support_conversation_columns = {
        row[1] for row in db.execute("PRAGMA table_info(support_conversations)").fetchall()
    }
    if "visitor_email" not in support_conversation_columns:
        db.execute(
            "ALTER TABLE support_conversations ADD COLUMN visitor_email TEXT NOT NULL DEFAULT ''"
        )
    seeded = db.execute(
        "SELECT setting_value FROM feature_settings WHERE setting_key='default_faqs_seeded'"
    ).fetchone()
    if not seeded:
        if db.execute("SELECT COUNT(*) FROM faqs").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO faqs (question, answer, sort_order) VALUES (?, ?, ?)",
                [(question, answer, order) for order, (question, answer) in enumerate(DEFAULT_FAQS, 1)]
            )
        db.execute(
            "INSERT INTO feature_settings (setting_key, setting_value) VALUES ('default_faqs_seeded', '1')"
        )


def _ensure_feature_schema():
    global _FEATURE_SCHEMA_READY
    if _FEATURE_SCHEMA_READY:
        return
    connection = sqlite3.connect(DATABASE)
    try:
        _ensure_feature_tables(connection)
        connection.commit()
        _FEATURE_SCHEMA_READY = True
    finally:
        connection.close()


@app.before_request
def ensure_feature_schema():
    _ensure_feature_schema()


def add_admin_notification(db, event_type, title, body, target_url):
    db.execute(
        "INSERT INTO admin_activity_notifications (event_type, title, body, target_url) VALUES (?, ?, ?, ?)",
        (event_type, title[:120], body[:500], target_url)
    )


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    global _FEATURE_SCHEMA_READY
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        matrimony_id TEXT UNIQUE,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL COLLATE NOCASE UNIQUE,
        mobile TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        gender TEXT NOT NULL CHECK(gender IN ('Bride', 'Groom')),
        date_of_birth TEXT NOT NULL,
        is_approved TEXT DEFAULT 'PENDING' CHECK(is_approved IN ('PENDING', 'APPROVED', 'REJECTED')),
        rejection_reason TEXT DEFAULT '',
        is_admin INTEGER DEFAULT 0,
        admin_role TEXT NOT NULL DEFAULT 'ADMIN',
        admin_permissions TEXT NOT NULL DEFAULT 'dashboard',
        admin_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS profiles (
        user_id INTEGER PRIMARY KEY,
        profile_created_by TEXT DEFAULT 'Self',
        religion TEXT DEFAULT '',
        mother_tongue TEXT DEFAULT '',
        marital_status TEXT DEFAULT 'Never Married',
        education TEXT DEFAULT '',
        occupation TEXT DEFAULT '',
        country TEXT DEFAULT 'India',
        state TEXT DEFAULT '',
        city TEXT DEFAULT '',
        about_me TEXT DEFAULT '',
        photo_path TEXT DEFAULT '',
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS interests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        interest_type TEXT NOT NULL CHECK(interest_type IN ('INTEREST', 'SHORTLIST')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sender_id, receiver_id, interest_type),
        FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    # Safe migrations for existing databases
    user_cols = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    if "is_approved" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN is_approved TEXT DEFAULT 'PENDING'")
    if "rejection_reason" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN rejection_reason TEXT DEFAULT ''")
    if "is_admin" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    if "account_active" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN account_active INTEGER NOT NULL DEFAULT 1")

    columns = {row[1] for row in db.execute("PRAGMA table_info(profiles)").fetchall()}
    if "photo_path" not in columns:
        db.execute("ALTER TABLE profiles ADD COLUMN photo_path TEXT DEFAULT ''")
    if "premium_details_visible" not in columns:
        db.execute("ALTER TABLE profiles ADD COLUMN premium_details_visible INTEGER NOT NULL DEFAULT 1")

    icols = {row[1] for row in db.execute("PRAGMA table_info(interests)").fetchall()}
    if "status" not in icols:
        db.execute("ALTER TABLE interests ADD COLUMN status TEXT DEFAULT 'PENDING'")
    if "updated_at" not in icols:
        db.execute("ALTER TABLE interests ADD COLUMN updated_at TEXT")
        db.execute("UPDATE interests SET updated_at = created_at WHERE updated_at IS NULL")

    db.executescript('''
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL, receiver_id INTEGER NOT NULL,
        body TEXT NOT NULL, is_read INTEGER DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS views (viewer_id INTEGER NOT NULL, viewed_id INTEGER NOT NULL, viewed_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(viewer_id, viewed_id));
    CREATE TABLE IF NOT EXISTS blocks (blocker_id INTEGER NOT NULL, blocked_id INTEGER NOT NULL, reason TEXT DEFAULT '', UNIQUE(blocker_id, blocked_id));
    CREATE TABLE IF NOT EXISTS preferences (user_id INTEGER PRIMARY KEY, age_min INTEGER, age_max INTEGER, religion TEXT DEFAULT '',
        caste TEXT DEFAULT '', city TEXT DEFAULT '', marital_status TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS premium_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        plan TEXT NOT NULL CHECK(plan IN ('SILVER','GOLD','PLATINUM','DIAMOND')),
        amount INTEGER NOT NULL,
        transaction_id TEXT NOT NULL,
        screenshot_path TEXT NOT NULL,
        notes TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED')),
        start_date TEXT,
        expiry_date TEXT,
        admin_note TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS user_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        is_read INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS notification_reads (
        user_id INTEGER PRIMARY KEY,
        read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    ''')
    preference_columns = {row[1] for row in db.execute("PRAGMA table_info(preferences)")}
    for column in ("star", "raasi"):
        if column not in preference_columns:
            db.execute(f"ALTER TABLE preferences ADD COLUMN {column} TEXT DEFAULT ''")
    _ensure_feature_tables(db)
    for col, ddl in (("caste","TEXT DEFAULT ''"),("star","TEXT DEFAULT ''"),("raasi","TEXT DEFAULT ''"),("height_cm","INTEGER"),("diet","TEXT DEFAULT ''")):
        if col not in {r[1] for r in db.execute("PRAGMA table_info(profiles)")}:
            db.execute(f"ALTER TABLE profiles ADD COLUMN {col} {ddl}")
    for col, ddl in (("plan","TEXT DEFAULT 'FREE'"),("plan_until","TEXT")):
        if col not in {r[1] for r in db.execute("PRAGMA table_info(users)")}:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

    # Seed Admin Account if not exists
    admin_exists = db.execute("SELECT id FROM users WHERE is_admin = 1").fetchone()
    if not admin_exists:
        db.execute("""
            INSERT OR IGNORE INTO users (matrimony_id, full_name, email, mobile, password_hash, gender, date_of_birth, is_approved, is_admin, admin_role, admin_permissions)
            VALUES ('IRMADMIN', 'System Administrator', 'admin@irumanam.com', '9999999999', ?, 'Groom', '1990-01-01', 'APPROVED', 1, 'SUPER_ADMIN', ?)
        """, (generate_password_hash("AdminSecure!234"), ",".join(ADMIN_PERMISSIONS)))

    # Add 20 fictional Tamil demo profiles once, for development/demo use.
    demo_profiles = [
        ("Priya Subramanian", "Bride", "1999-04-12", "Chennai", "B.E. Computer Science", "Software Engineer", "Hindu", "Tamil", "Vellalar", "She enjoys reading, music, and exploring new places."),
        ("Aravind Kumar", "Groom", "1997-08-21", "Coimbatore", "B.Tech Mechanical", "Design Engineer", "Hindu", "Tamil", "Naidu", "A thoughtful person who enjoys travel and family time."),
        ("Meena Rajesh", "Bride", "2001-01-17", "Madurai", "M.Sc. Biotechnology", "Lab Technician", "Hindu", "Tamil", "Chettiar", "Friendly, caring, and interested in cooking and gardening."),
        ("Karthik Velmurugan", "Groom", "1993-11-05", "Salem", "B.E. Civil", "Project Engineer", "Hindu", "Tamil", "Gounder", "Values honesty, family, and an active lifestyle."),
        ("Divya Murugan", "Bride", "1998-06-23", "Tirunelveli", "B.Sc. Nursing", "Staff Nurse", "Hindu", "Tamil", "Nadar", "Caring by nature and enjoys books and classical music."),
        ("Suresh Prabhu", "Groom", "1996-02-14", "Tiruchirappalli", "B.E. ECE", "Network Engineer", "Hindu", "Tamil", "Thevar", "Enjoys technology, cricket, and spending time with family."),
        ("Kavya Thangavel", "Bride", "2000-09-09", "Erode", "M.A. English", "Teacher", "Hindu", "Tamil", "Iyengar", "Patient, optimistic, and passionate about teaching."),
        ("Raghul Sekar", "Groom", "1998-03-30", "Kumbakonam", "B.Com", "Accountant", "Hindu", "Tamil", "Agamudaiyar", "Likes music, road trips, and simple family gatherings."),
        ("Nandhini Kannan", "Bride", "2002-05-19", "Vellore", "B.E. Information Technology", "Software Developer", "Hindu", "Tamil", "Vanniyar", "Curious learner who likes travel and photography."),
        ("Vijay Rajan", "Groom", "1995-12-11", "Dindigul", "M.E. Production", "Production Manager", "Hindu", "Tamil", "Kallar", "Responsible, friendly, and fond of sports."),
        ("Swetha Lakshmi", "Bride", "1999-07-02", "Chennai", "M.Sc. Physics", "Research Scholar", "Hindu", "Tamil", "Brahmin", "Enjoys research, nature walks, and spending time with family."),
        ("Ganesh Mani", "Groom", "1993-10-26", "Bengaluru", "B.Tech IT", "System Analyst", "Hindu", "Tamil", "Kamma", "A calm person who enjoys music, food, and weekend travel."),
        ("Pooja Srinivasan", "Bride", "2001-02-08", "Ramanathapuram", "B.Com", "Bank Executive", "Hindu", "Tamil", "Pillai", "Values kindness and enjoys cooking and volunteering."),
        ("Hariharan Durai", "Groom", "1997-06-15", "Tiruppur", "B.E. Automobile", "Automobile Engineer", "Hindu", "Tamil", "Mudaliar", "Enjoys automobiles, fitness, and exploring new places."),
        ("Lakshmi Balan", "Bride", "1998-12-04", "Kanchipuram", "MCA", "IT Analyst", "Hindu", "Tamil", "Chettiar", "Positive-minded and enjoys art, movies, and family time."),
        ("Santhosh Pandian", "Groom", "1994-04-28", "Namakkal", "B.E. Mechanical", "Quality Engineer", "Hindu", "Tamil", "Agamudaiyar", "Values trust, respect, and a balanced lifestyle."),
        ("Keerthana Vasanth", "Bride", "2000-08-13", "Thoothukudi", "M.Sc. Chemistry", "Chemist", "Hindu", "Tamil", "Naicker", "Loves learning, music, and spending time outdoors."),
        ("Jeevan Raj", "Groom", "1996-01-25", "Tiruppur", "B.E. Electrical", "Electrical Engineer", "Hindu", "Tamil", "Vanniyar", "Practical, caring, and interested in sports and travel."),
        ("Anitha Krishnan", "Bride", "1998-03-06", "Nagapattinam", "M.Com", "Financial Analyst", "Hindu", "Tamil", "Kudumi", "Enjoys reading, cooking, and meaningful conversations."),
        ("Praveen Selvam", "Groom", "1992-09-18", "Coimbatore", "MBA", "Business Analyst", "Hindu", "Tamil", "Nadar", "Ambitious but family-oriented; enjoys travel and photography."),
    ]
    for index, item in enumerate(demo_profiles, start=1):
        name, gender, dob, city, education, occupation, religion, tongue, community, about = item
        email = f"demo.profile{index:02d}@irumanam.example"
        mobile = f"900000{index:04d}"
        exists = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            continue
        cur = db.execute("""INSERT INTO users
            (matrimony_id, full_name, email, mobile, password_hash, gender, date_of_birth, is_approved)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED')""",
            (f"IRMDEMO{index:02d}", name, email, mobile,
             generate_password_hash("DemoOnly!234"), gender, dob))
        uid = cur.lastrowid
        db.execute("""INSERT INTO profiles
            (user_id, profile_created_by, religion, mother_tongue, marital_status,
             education, occupation, country, state, city, about_me, photo_path)
            VALUES (?, 'Self', ?, ?, 'Never Married', ?, ?, 'India', 'Tamil Nadu', ?, ?, ?)""",
            (uid, religion, tongue, education, occupation, city, about,
             f"images/profiles/demo_{index:02d}.jpg"))
    db.execute("""
        INSERT OR IGNORE INTO notification_reads (user_id, read_at)
        SELECT id, CURRENT_TIMESTAMP FROM users
    """)
    db.commit()
    _FEATURE_SCHEMA_READY = True
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        user = current_user()
        if not user or not user["account_active"]:
            session.clear()
            flash("This account is inactive. Please contact the administrator.", "danger")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        u = current_user()
        if not u or not u["is_admin"]:
            flash("Admin privileges required to access this page.", "danger")
            return redirect(url_for("dashboard"))
        if not u["admin_active"]:
            session.clear()
            flash("This administrator account is inactive.", "danger")
            return redirect(url_for("admin_login"))
        permission = ADMIN_ENDPOINT_PERMISSIONS.get(request.endpoint)
        if permission == "admins" and u["admin_role"] != "SUPER_ADMIN":
            abort(403)
        if permission and not has_admin_permission(u, permission):
            abort(403)
        return view(*args, **kwargs)
    return wrapped_view


def has_admin_permission(user, permission):
    if not user or not user["is_admin"] or not user["admin_active"]:
        return False
    if user["admin_role"] == "SUPER_ADMIN":
        return True
    assigned = set((user["admin_permissions"] or "").split(","))
    return permission == "dashboard" or permission in assigned


def record_admin_login(db, user, event_type):
    db.execute(
        "INSERT INTO admin_login_logs (admin_id, admin_name, admin_email, event_type, ip_address, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            user["id"], user["full_name"], user["email"], event_type,
            (request.remote_addr or "")[:64],
            request.user_agent.string[:300]
        )
    )
    db.commit()


@app.after_request
def record_admin_activity(response):
    endpoint = request.endpoint or ""
    if endpoint not in SEO_INDEXABLE_ENDPOINTS or session.get("user_id"):
        directive = (
            "noindex, follow"
            if endpoint in ("login", "register") and not session.get("user_id")
            else "noindex, nofollow"
        )
        response.headers["X-Robots-Tag"] = directive

    admin_id = session.get("user_id")
    if not admin_id or request.method != "POST" or not endpoint.startswith("admin_"):
        return response
    if endpoint in ("admin_login",):
        return response
    if response.status_code >= 400:
        return response
    db = get_db()
    user = db.execute(
        "SELECT id, full_name, is_admin FROM users WHERE id=?", (admin_id,)
    ).fetchone()
    if not user or not user["is_admin"]:
        return response
    action = "Update"
    if endpoint in ("admin_profile_action", "admin_user_edit", "admin_user_action",
                    "admin_review_premium_payment",
                    "admin_support_conversation", "admin_account_action"):
        action = request.form.get("action", "Update").strip().title()[:40]
    elif "delete" in endpoint or request.form.get("action") == "delete":
        action = "Delete"
    elif endpoint == "admin_support_auto_replies":
        action = "Edit" if request.form.get("reply_id") else "Add"
    elif endpoint == "admin_faqs":
        action = "Edit" if request.form.get("faq_id") else "Add"
    elif endpoint == "admin_accounts":
        action = "Edit" if request.form.get("admin_id") else "Add"
    db.execute(
        "INSERT INTO admin_activity_logs (admin_id, admin_name, action, endpoint, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            user["id"], user["full_name"], action, endpoint,
            (request.path + ("?" + urlencode(request.args) if request.args else ""))[:500]
        )
    )
    db.commit()
    return response


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("""
        SELECT u.*, p.profile_created_by, p.religion, p.mother_tongue,
               p.marital_status, p.education, p.occupation, p.country,
               p.state, p.city, p.about_me, p.photo_path, p.caste, p.star, p.raasi, p.height_cm, p.diet
        FROM users u LEFT JOIN profiles p ON p.user_id = u.id
        WHERE u.id = ?
    """, (user_id,)).fetchone()


@app.context_processor
def inject_user():
    u = current_user()
    unread, notification_count, notifs = 0, 0, []
    login_ad = None
    admin_unread_count, admin_latest_id, admin_notifs, support_unread_count = 0, 0, [], 0
    if u and u["is_admin"]:
        db = get_db()
        admin_unread_count = db.execute(
            "SELECT COUNT(*) FROM admin_activity_notifications WHERE is_read=0"
        ).fetchone()[0]
        latest = db.execute("SELECT COALESCE(MAX(id), 0) FROM admin_activity_notifications").fetchone()[0]
        admin_latest_id = latest
        admin_notifs = db.execute(
            "SELECT id, title, body, created_at FROM admin_activity_notifications ORDER BY id DESC LIMIT 8"
        ).fetchall()
        support_unread_count = db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE sender_role='visitor' AND is_read=0"
        ).fetchone()[0]
    if u and not u["is_admin"]:
        db = get_db()
        unread = db.execute("""
            SELECT COUNT(*) FROM messages m JOIN users x ON x.id=m.sender_id
            WHERE m.receiver_id=:me AND m.is_read=0 AND NOT EXISTS (
                SELECT 1 FROM blocks b
                WHERE (b.blocker_id=:me AND b.blocked_id=x.id)
                   OR (b.blocker_id=x.id AND b.blocked_id=:me)
            )
        """, {"me": u["id"]}).fetchone()[0]
        notification_count = db.execute("""
            SELECT COUNT(*) FROM (
                SELECT v.viewed_at AS event_at
                FROM views v JOIN users x ON x.id = v.viewer_id
                WHERE v.viewed_id = :me AND x.is_approved = 'APPROVED' AND x.is_admin = 0 AND x.account_active = 1
                  AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
                UNION ALL
                SELECT i.created_at AS event_at
                FROM interests i JOIN users x ON x.id = i.sender_id
                WHERE i.receiver_id = :me AND i.interest_type = 'INTEREST'
                  AND x.is_approved = 'APPROVED' AND x.is_admin = 0 AND x.account_active = 1
                  AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
                UNION ALL
                SELECT i.updated_at AS event_at
                FROM interests i JOIN users x ON x.id = i.receiver_id
                WHERE i.sender_id = :me AND i.interest_type = 'INTEREST'
                  AND i.status = 'ACCEPTED' AND x.is_approved = 'APPROVED' AND x.is_admin = 0 AND x.account_active = 1
                  AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
            ) events
            WHERE events.event_at > COALESCE(
                (SELECT read_at FROM notification_reads WHERE user_id = :me),
                '0000-00-00 00:00:00'
            )
        """, {"me": u["id"]}).fetchone()[0]
        notifs = db.execute("""
            SELECT 'view' k, v.viewer_id uid, x.full_name n, v.viewed_at t FROM views v JOIN users x ON x.id=v.viewer_id WHERE v.viewed_id=:me AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
            UNION ALL SELECT 'int', i.sender_id, x.full_name, i.created_at FROM interests i JOIN users x ON x.id=i.sender_id WHERE i.receiver_id=:me AND i.interest_type='INTEREST' AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
            UNION ALL SELECT 'acc', i.receiver_id, x.full_name, i.updated_at FROM interests i JOIN users x ON x.id=i.receiver_id WHERE i.sender_id=:me AND i.interest_type='INTEREST' AND i.status='ACCEPTED' AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
            ORDER BY t DESC LIMIT 8""", {"me": u["id"]}).fetchall()
        login_ad = login_advertisement(db, u)
    return {"logged_in_user": u, "unread_count": unread, "notification_count": notification_count,
            "premium": is_premium(u), "notifs": notifs, "login_ad": login_ad,
            "admin_unread_count": admin_unread_count, "admin_latest_id": admin_latest_id,
            "admin_notifs": admin_notifs, "support_unread_count": support_unread_count,
            "can_admin": lambda permission: has_admin_permission(u, permission)}


def is_premium(u):
    return bool(u and u["plan"] and u["plan"] != "FREE" and (u["plan_until"] or "") >= date.today().isoformat())


def advertisement_expiry(ad):
    start = date.fromisoformat(ad["start_date"])
    scheduled_expiry = start + timedelta(days=ad["display_days"] - 1)
    return min(scheduled_expiry, date.fromisoformat(ad["end_date"]))


def advertisement_status(ad, today=None):
    today = today or date.today()
    if not ad["is_enabled"]:
        return "Disabled"
    if today < date.fromisoformat(ad["start_date"]):
        return "Scheduled"
    if today > advertisement_expiry(ad):
        return "Expired"
    return "Active"


def record_advertisement_history(db, ad, action, actor):
    selected_users = [
        row["user_id"] for row in db.execute(
            "SELECT user_id FROM advertisement_audience_users "
            "WHERE advertisement_id=? ORDER BY user_id",
            (ad["id"],)
        )
    ]
    db.execute("""
        INSERT INTO advertisement_history (
            advertisement_id, title, description, redirect_url, image_path,
            start_date, end_date, display_days, target_audience, selected_users,
            display_frequency, is_enabled, is_deleted, created_by_name,
            created_at, published_at, action, changed_by, changed_by_name
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ad["id"], ad["title"], ad["description"], ad["redirect_url"],
        ad["image_path"], ad["start_date"], ad["end_date"], ad["display_days"],
        ad["target_audience"], json.dumps(selected_users), ad["display_frequency"],
        ad["is_enabled"], ad["is_deleted"], ad["created_by_name"],
        ad["created_at"], ad["published_at"], action, actor["id"],
        actor["full_name"]
    ))


def advertisement_matches_user(db, ad, user):
    audience = ad["target_audience"]
    if audience == "FREE" and is_premium(user):
        return False
    if audience == "PREMIUM" and not is_premium(user):
        return False
    if audience == "MALE" and user["gender"] != "Groom":
        return False
    if audience == "FEMALE" and user["gender"] != "Bride":
        return False
    if audience == "NEW":
        try:
            registered = date.fromisoformat(user["created_at"][:10])
        except (ValueError, TypeError):
            return False
        if registered < date.today() - timedelta(days=30):
            return False
    if audience == "SELECTED" and not db.execute(
        "SELECT 1 FROM advertisement_audience_users "
        "WHERE advertisement_id=? AND user_id=?",
        (ad["id"], user["id"])
    ).fetchone():
        return False
    return True


def advertisement_frequency_key(ad, login_nonce, today=None):
    frequency = ad["display_frequency"]
    if frequency == "EVERY_LOGIN":
        return login_nonce
    if frequency == "DAILY":
        return (today or date.today()).isoformat()
    return "once"


def login_advertisement(db, user):
    if not user or user["is_admin"] or not session.get("login_ad_pending"):
        return None

    session["login_ad_pending"] = False
    login_nonce = session.get("login_ad_nonce")
    if not login_nonce:
        return None

    today = date.today()
    candidates = []
    ads = db.execute("""
        SELECT * FROM advertisements
        WHERE is_enabled=1 AND is_deleted=0
          AND start_date<=? AND end_date>=?
        ORDER BY id DESC
    """, (today.isoformat(), today.isoformat())).fetchall()
    for ad in ads:
        if advertisement_status(ad, today) != "Active":
            continue
        if not advertisement_matches_user(db, ad, user):
            continue
        frequency_key = advertisement_frequency_key(ad, login_nonce, today)
        if db.execute("""
            SELECT 1 FROM advertisement_impressions
            WHERE advertisement_id=? AND user_id=? AND frequency_key=?
        """, (ad["id"], user["id"], frequency_key)).fetchone():
            continue
        last_shown = db.execute("""
            SELECT MAX(shown_at) FROM advertisement_impressions
            WHERE advertisement_id=? AND user_id=?
        """, (ad["id"], user["id"])).fetchone()[0] or ""
        candidates.append((last_shown, -ad["id"], ad, frequency_key))

    if not candidates:
        session.pop("login_ad_id", None)
        db.commit()
        return None

    _, _, ad, frequency_key = min(candidates, key=lambda candidate: (candidate[0], candidate[1]))
    session["login_ad_id"] = ad["id"]
    if not ad["published_at"]:
        published_at = datetime.now().isoformat(sep=" ", timespec="seconds")
        db.execute(
            "UPDATE advertisements SET published_at=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND published_at IS NULL",
            (published_at, ad["id"])
        )
        updated_ad = db.execute(
            "SELECT * FROM advertisements WHERE id=?", (ad["id"],)
        ).fetchone()
        record_advertisement_history(db, updated_ad, "PUBLISHED", user)
    db.commit()
    return {
        "id": ad["id"],
        "title": ad["title"],
        "description": ad["description"],
        "image_url": url_for("advertisement_image", ad_id=ad["id"]),
        "redirect_url": ad["redirect_url"],
        "impression_url": url_for("advertisement_impression", ad_id=ad["id"]),
        "close_url": url_for("advertisement_close", ad_id=ad["id"]),
    }


def is_blocked(db, first_user_id, second_user_id):
    return bool(db.execute(
        "SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)",
        (first_user_id, second_user_id, second_user_id, first_user_id)
    ).fetchone())


BLOCK_SQL = "u.id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id=?) AND u.id NOT IN (SELECT blocker_id FROM blocks WHERE blocked_id=?)"
CARD_SQL = """SELECT u.id, u.full_name, u.gender, u.date_of_birth, p.education, p.occupation, p.city, p.state,
    p.photo_path, p.caste, p.height_cm, p.premium_details_visible, u.created_at,
    EXISTS(SELECT 1 FROM interests i WHERE i.sender_id=:me AND i.receiver_id=u.id AND i.interest_type='SHORTLIST') AS shortlisted,
    EXISTS(SELECT 1 FROM interests i WHERE i.sender_id=:me AND i.receiver_id=u.id AND i.interest_type='INTEREST') AS interested"""


def chat_allowed(db, me, other):
    if me == other or is_blocked(db, me, other):
        return False
    if is_premium(current_user()):
        return True
    return bool(db.execute("""SELECT 1 FROM interests WHERE interest_type='INTEREST' AND status='ACCEPTED'
        AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))""", (me, other, other, me)).fetchone())


def calculate_age(dob):
    born = date.fromisoformat(dob)
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def redirect_back(default_endpoint):
    referrer = request.referrer or ""
    parsed = urlsplit(referrer)
    if parsed.scheme in ("http", "https") and parsed.netloc == request.host:
        return redirect(referrer)
    if not parsed.netloc and referrer.startswith("/") and not referrer.startswith("//"):
        return redirect(referrer)
    return redirect(url_for(default_endpoint))


PROFILE_FIELDS = ["caste", "star", "raasi", "height_cm", "diet", "religion", "mother_tongue", "education", "occupation", "state", "city", "about_me", "photo_path"]
PROFILE_SELECT_OPTIONS = {
    "religion": ["Hindu", "Muslim", "Christian", "Sikh", "Buddhist", "Jain", "Parsi", "Jewish", "Other"],
    "mother_tongue": [
        "Tamil", "Telugu", "Malayalam", "Kannada", "Hindi", "Bengali", "Marathi",
        "Gujarati", "Punjabi", "Urdu", "Odia", "Assamese", "Konkani", "Sindhi",
        "Kashmiri", "Sanskrit", "English", "Other"
    ],
    "star": [
        "Ashwini", "Bharani", "Karthigai", "Rohini", "Mirugasirisham",
        "Thiruvathirai", "Punarpoosam", "Poosam", "Ayilyam", "Magam",
        "Pooram", "Uthiram", "Hastham", "Chithirai", "Swathi", "Visakam",
        "Anusham", "Kettai", "Moolam", "Pooradam", "Uthiradam",
        "Thiruvonam", "Avittam", "Sathayam", "Poorattathi", "Uthirattathi",
        "Revathi", "Other"
    ],
    "raasi": [
        "Mesham", "Rishabam", "Mithunam", "Kadagam", "Simmam", "Kanni",
        "Thulam", "Viruchigam", "Dhanusu", "Makaram", "Kumbam", "Meenam",
        "Other"
    ],
    "caste": ["Other"],
}


def profile_select_options(db):
    options = {}
    for field, defaults in PROFILE_SELECT_OPTIONS.items():
        values = list(defaults)
        existing_values = db.execute(
            f"SELECT DISTINCT {field} FROM profiles "
            f"WHERE {field} IS NOT NULL AND TRIM({field}) != '' "
            f"ORDER BY {field} COLLATE NOCASE"
        ).fetchall()
        for row in existing_values:
            value = row[0]
            if value.strip() and value not in values:
                values.append(value)
        options[field] = values
    return options


app.jinja_env.globals["completeness"] = lambda u: completeness(u)
app.jinja_env.globals["calculate_age"] = calculate_age
app.jinja_env.globals["new_cut"] = lambda: (date.today() - timedelta(days=7)).isoformat()


def completeness(user):
    done = sum(1 for f in PROFILE_FIELDS if user[f])
    return int(round(100 * done / len(PROFILE_FIELDS)))


def save_photo(file):
    if not file or not file.filename:
        return None
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    head = file.stream.read(12)
    file.stream.seek(0)
    kinds = {".jpg": head[:3] == b"\xff\xd8\xff", ".jpeg": head[:3] == b"\xff\xd8\xff",
             ".png": head[:8] == b"\x89PNG\r\n\x1a\n", ".webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP"}
    if not kinds.get(ext):
        return None
    name = f"user_{session['user_id']}_{uuid.uuid4().hex[:8]}{ext}"
    file.save(os.path.join(BASE_DIR, "static", "images", "profiles", name))
    return f"images/profiles/{name}"


def save_album_photo(upload, user_id):
    if not upload or not upload.filename:
        raise ValueError("Choose a photo to upload.")
    if not secure_filename(upload.filename).lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        raise ValueError("Album photos must be JPG, PNG, or WebP images.")
    upload.stream.seek(0, os.SEEK_END)
    if upload.stream.tell() > 2_500_000:
        raise ValueError("Each album photo must be 2.5 MB or smaller.")
    upload.stream.seek(0)

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(upload.stream) as image:
            if image.format not in ("JPEG", "PNG", "WEBP") or image.width > 6000 or image.height > 6000:
                raise ValueError("Please upload a valid JPG, PNG, or WebP photo under 6000 × 6000 pixels.")
            image.verify()
        upload.stream.seek(0)
        with Image.open(upload.stream) as image:
            image = image.convert("RGB")
            image.thumbnail((1600, 2000), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=86, optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("The uploaded album photo is invalid or could not be processed.") from error

    filename = f"album_{user_id}_{uuid.uuid4().hex}.jpg"
    folder = os.path.join(BASE_DIR, "private_media", "profile_albums")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, filename), "wb") as photo_file:
        photo_file.write(output.getvalue())
    return filename


def save_cropped_photo(data_url, user_id):
    if not data_url or len(data_url) > 3 * 1024 * 1024:
        raise ValueError("Please upload and save a valid profile photo.")
    prefix = "data:image/jpeg;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("Please upload and save a valid profile photo.")

    from PIL import Image, UnidentifiedImageError

    try:
        image_data = base64.b64decode(data_url[len(prefix):], validate=True)
        with Image.open(io.BytesIO(image_data)) as image:
            if image.format != "JPEG" or image.width > 4000 or image.height > 4000:
                raise ValueError("Please upload and save a valid profile photo.")
            image = image.convert("RGB")
            image.thumbnail((800, 1000), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=90, optimize=True)
    except (binascii.Error, ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("Please upload and save a valid profile photo.") from error

    filename = f"user_{user_id}_{uuid.uuid4().hex[:8]}.jpg"
    photo_dir = os.path.join(BASE_DIR, "static", "images", "profiles")
    os.makedirs(photo_dir, exist_ok=True)
    with open(os.path.join(photo_dir, filename), "wb") as photo_file:
        photo_file.write(output.getvalue())
    return f"images/profiles/{filename}"


def dob_for_age(age):
    t = date.today()
    try:
        return t.replace(year=t.year - age).isoformat()
    except ValueError:
        return t.replace(year=t.year - age, day=28).isoformat()


@app.route("/")
def index():
    db = get_db()
    if session.get("user_id"):
        user = current_user()
        if user and user["is_admin"]:
            return redirect(url_for("admin_dashboard"))
        preferred_gender = "Bride" if user["gender"] == "Groom" else "Groom"
        gender = request.args.get("gender", preferred_gender)
        query = request.args.get("q", "").strip()[:80]
        conditions = ["u.id != ?", "u.is_approved = 'APPROVED'", "u.is_admin = 0", "u.account_active = 1", BLOCK_SQL]
        params = [session["user_id"]] * 3
        if gender in ("Bride", "Groom"):
            conditions.append("u.gender = ?")
            params.append(gender)
        if query:
            like = f"%{query}%"
            conditions.append("(u.full_name LIKE ? OR p.city LIKE ? OR p.education LIKE ? OR p.occupation LIKE ? OR p.religion LIKE ?)")
            params.extend([like, like, like, like, like])
        profiles = db.execute(f"""
            SELECT u.id, u.full_name, u.gender, u.date_of_birth, u.created_at,
                   p.education, p.occupation, p.city, p.state, p.photo_path,
                   p.caste, p.height_cm, p.premium_details_visible,
                   EXISTS(SELECT 1 FROM interests i WHERE i.sender_id = ? AND i.receiver_id = u.id AND i.interest_type='SHORTLIST') AS shortlisted,
                   EXISTS(SELECT 1 FROM interests i WHERE i.sender_id = ? AND i.receiver_id = u.id AND i.interest_type='INTEREST') AS interested
            FROM users u LEFT JOIN profiles p ON p.user_id = u.id
            WHERE {' AND '.join(conditions)}
            ORDER BY u.created_at DESC LIMIT 60
        """, [session["user_id"], session["user_id"]] + params).fetchall()
        incoming = db.execute("SELECT COUNT(*) FROM interests WHERE receiver_id=? AND interest_type='INTEREST'", (session["user_id"],)).fetchone()[0]
        shortlisted_count = db.execute("SELECT COUNT(*) FROM interests WHERE sender_id=? AND interest_type='SHORTLIST'", (session["user_id"],)).fetchone()[0]
        return render_template("index.html", profiles=profiles, calculate_age=calculate_age,
                               logged_home=True, user=user, gender=gender, query=query,
                               incoming=incoming, shortlisted_count=shortlisted_count,
                               faqs=db.execute("SELECT id, question, answer FROM faqs WHERE is_active=1 ORDER BY sort_order, id").fetchall())

    profiles = db.execute("""
        SELECT u.id, u.matrimony_id, u.full_name, u.gender, u.date_of_birth,
               p.education, p.occupation, p.city, p.religion, p.photo_path, p.premium_details_visible
        FROM users u LEFT JOIN profiles p ON p.user_id = u.id
        WHERE u.is_approved = 'APPROVED' AND u.is_admin = 0 AND u.account_active = 1
        ORDER BY u.created_at DESC LIMIT 6
    """).fetchall()
    faqs = db.execute("SELECT id, question, answer FROM faqs WHERE is_active=1 ORDER BY sort_order, id").fetchall()
    g.seo_faqs = faqs
    return render_template("index.html", profiles=profiles, calculate_age=calculate_age, logged_home=False, faqs=faqs)


TAMIL_FAQS = (
    {
        "question": "இருமணத்தில் சுயவிவரத்தை எப்படித் தொடங்குவது?",
        "answer": "பதிவு படிவத்தை நிரப்பி உங்கள் சுயவிவரத்தைச் சமர்ப்பிக்கவும். நிர்வாகி சரிபார்த்த பிறகு உங்கள் கணக்கு செயல்படுத்தப்படும்.",
    },
    {
        "question": "பொருத்தமான வரன்களை எப்படிக் கண்டுபிடிப்பது?",
        "answer": "உங்கள் சுயவிவரத்தை முடித்து, பொருத்தங்கள் மற்றும் தேடல் வசதிகளைப் பயன்படுத்தி உங்களுக்கு ஏற்ற சுயவிவரங்களைப் பாருங்கள்.",
    },
    {
        "question": "ஒரு உறுப்பினரிடம் ஆர்வத்தை எப்படித் தெரிவிப்பது?",
        "answer": "விருப்பமான சுயவிவரத்தில் உள்ள ஆர்வம் தெரிவிக்கும் வசதியைப் பயன்படுத்துங்கள். உங்கள் கோரிக்கையின் நிலையை உங்கள் கணக்கில் பார்க்கலாம்.",
    },
)


@app.route("/ta")
def tamil_home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    g.seo_faqs = TAMIL_FAQS
    return render_template("tamil_home.html", faqs=TAMIL_FAQS)


@app.route("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /dashboard\n"
        "Disallow: /search\n"
        "Disallow: /profile/\n"
        "Disallow: /messages\n"
        "Disallow: /notifications\n"
        "Disallow: /premium\n"
        "Disallow: /edit-profile\n"
        "Disallow: /preferences\n"
        "Disallow: /matches\n"
        "Disallow: /interests\n"
        "Disallow: /viewers\n"
        "Disallow: /blocked-members\n"
        f"Sitemap: {public_url('/sitemap.xml')}\n"
    )
    return app.response_class(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    pages = (
        ("en-IN", public_url("/")),
        ("ta-IN", public_url("/ta")),
    )
    entries = []
    for language, location in pages:
        alternates = (
            "".join(
                '<xhtml:link rel="alternate" hreflang="{}" href="{}"/>'.format(
                    html.escape(alternate_language, quote=True),
                    html.escape(alternate_url, quote=True),
                )
                for alternate_language, alternate_url in pages
            )
            + '<xhtml:link rel="alternate" hreflang="x-default" href="{}"/>'.format(
                html.escape(public_url("/"), quote=True)
            )
        )
        entries.append(
            "<url><loc>{}</loc>{}<changefreq>weekly</changefreq><priority>{}</priority></url>".format(
                html.escape(location, quote=True),
                alternates,
                "1.0" if language == "en-IN" else "0.8",
            )
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        + "".join(entries)
        + "</urlset>"
    )
    return app.response_class(body, mimetype="application/xml")


def get_support_conversation(db, create=False, visitor_name=None, visitor_email=""):
    token = session.get("support_token")
    if not token:
        token = uuid.uuid4().hex
        session["support_token"] = token
    conversation = db.execute(
        "SELECT * FROM support_conversations WHERE visitor_token=?", (token,)
    ).fetchone()
    if not conversation and create:
        user = current_user()
        visitor_name = visitor_name or (
            user["full_name"] if user and not user["is_admin"] else "Website visitor"
        )
        cursor = db.execute(
            "INSERT INTO support_conversations (visitor_token, visitor_name, visitor_email) VALUES (?, ?, ?)",
            (token, visitor_name, visitor_email)
        )
        conversation = db.execute(
            "SELECT * FROM support_conversations WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    return conversation


def find_support_auto_reply(db, body):
    replies = db.execute(
        "SELECT id, keyword, reply FROM support_auto_replies ORDER BY LENGTH(keyword) DESC, id"
    ).fetchall()
    normalized_body = body.casefold()
    return next(
        (item for item in replies if item["keyword"].casefold() in normalized_body),
        None
    )


@app.route("/support/chat", methods=["GET", "POST"])
def support_chat_api():
    user = current_user()
    if user and user["is_admin"]:
        abort(403)
    db = get_db()
    if request.method == "GET":
        conversation = get_support_conversation(db)
        if not conversation:
            return jsonify(messages=[])
        try:
            after_id = max(0, int(request.args.get("after", "0")))
        except ValueError:
            return jsonify(error="Invalid message cursor."), 400
        rows = db.execute(
            "SELECT id, sender_role, body, is_automated, created_at FROM support_messages WHERE conversation_id=? AND id>? ORDER BY id",
            (conversation["id"], after_id)
        ).fetchall()
        db.execute(
            "UPDATE support_messages SET is_read=1 WHERE conversation_id=? AND sender_role='admin' AND is_read=0",
            (conversation["id"],)
        )
        db.commit()
        return jsonify(messages=[dict(row) for row in rows])

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("body"), str):
        return jsonify(error="Send a valid support message."), 400
    body = payload["body"].strip()
    if not body or len(body) > 1000:
        return jsonify(error="Enter a message between 1 and 1000 characters."), 400
    matched_reply = find_support_auto_reply(db, body)
    conversation = get_support_conversation(db)
    is_new_conversation = conversation is None
    if is_new_conversation:
        conversation = get_support_conversation(db, create=True)
    if not conversation:
        return jsonify(error="Unable to start a support conversation. Please reload and try again."), 500
    cursor = db.execute(
        "INSERT INTO support_messages (conversation_id, sender_role, body, is_read) VALUES (?, 'visitor', ?, ?)",
        (conversation["id"], body, 1 if matched_reply else 0)
    )
    if matched_reply:
        auto_reply_cursor = db.execute(
            "INSERT INTO support_messages (conversation_id, sender_role, body, is_automated) VALUES (?, 'admin', ?, 1)",
            (conversation["id"], matched_reply["reply"])
        )
        db.execute(
            "UPDATE support_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation["id"],)
        )
        if is_new_conversation:
            db.execute(
                "UPDATE support_conversations SET status='CLOSED' WHERE id=?",
                (conversation["id"],)
            )
    else:
        db.execute(
            "UPDATE support_conversations SET status='OPEN', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation["id"],)
        )
        add_admin_notification(
            db, "support_message", "New support chat message",
            f"{conversation['visitor_name']} sent a message to support.",
            url_for("admin_support_conversation", conversation_id=conversation["id"])
        )
    db.commit()
    message = db.execute(
        "SELECT id, sender_role, body, is_automated, created_at FROM support_messages WHERE id=?",
        (cursor.lastrowid,)
    ).fetchone()
    response = {"message": dict(message)}
    if matched_reply:
        reply_message = db.execute(
            "SELECT id, sender_role, body, is_automated, created_at FROM support_messages WHERE id=?",
            (auto_reply_cursor.lastrowid,)
        ).fetchone()
        response["auto_reply"] = dict(reply_message)
    return jsonify(response), 201


@app.route("/support/inquiry", methods=["POST"])
def submit_support_inquiry():
    if request.method != "POST":
        abort(405)
    if current_user() and current_user()["is_admin"]:
        abort(403)

    visitor_name = request.form.get("name", "").strip()
    visitor_email = request.form.get("email", "").strip().lower()
    body = request.form.get("body", "").strip()
    if not visitor_name or len(visitor_name) > 120:
        flash("Enter your name (up to 120 characters).", "warning")
        return redirect(url_for("index", _anchor="support-inquiry"))
    if len(visitor_email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", visitor_email):
        flash("Enter a valid email address.", "warning")
        return redirect(url_for("index", _anchor="support-inquiry"))
    if not body or len(body) > 1000:
        flash("Enter an inquiry between 1 and 1000 characters.", "warning")
        return redirect(url_for("index", _anchor="support-inquiry"))

    db = get_db()
    conversation = get_support_conversation(db)
    is_new_conversation = conversation is None
    if is_new_conversation:
        conversation = get_support_conversation(
            db, create=True, visitor_name=visitor_name, visitor_email=visitor_email
        )
    if not conversation:
        flash("Unable to submit your inquiry. Please try again.", "danger")
        return redirect(url_for("index", _anchor="support-inquiry"))
    db.execute(
        "UPDATE support_conversations SET visitor_name=?, visitor_email=? WHERE id=?",
        (visitor_name, visitor_email, conversation["id"])
    )
    matched_reply = find_support_auto_reply(db, body)
    db.execute(
        "INSERT INTO support_messages (conversation_id, sender_role, body, is_read) VALUES (?, 'visitor', ?, ?)",
        (conversation["id"], body, 1 if matched_reply else 0)
    )
    if matched_reply:
        db.execute(
            "INSERT INTO support_messages (conversation_id, sender_role, body, is_automated) VALUES (?, 'admin', ?, 1)",
            (conversation["id"], matched_reply["reply"])
        )
        db.execute(
            "UPDATE support_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation["id"],)
        )
        if is_new_conversation:
            db.execute(
                "UPDATE support_conversations SET status='CLOSED' WHERE id=?",
                (conversation["id"],)
            )
    else:
        db.execute(
            "UPDATE support_conversations SET status='OPEN', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (conversation["id"],)
        )
        add_admin_notification(
            db, "support_message", "New support inquiry",
            f"{visitor_name} submitted a support inquiry.",
            url_for("admin_support_conversation", conversation_id=conversation["id"])
        )
    db.commit()
    flash(
        "Your inquiry was sent. You can view the support team's reply in the chat widget.",
        "success"
    )
    return redirect(url_for("index", support_inquiry="sent", _anchor="support-inquiry"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        form = {
            "full_name": request.form.get("full_name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "mobile": re.sub(r"\s+", "", request.form.get("mobile", "")),
            "gender": request.form.get("gender", ""),
            "date_of_birth": request.form.get("date_of_birth", ""),
            "profile_created_by": request.form.get("profile_created_by", "Self"),
            "password": request.form.get("password", ""),
            "confirm_password": request.form.get("confirm_password", ""),
        }
        cropped_photo = request.form.get("cropped_photo", "")

        errors = []
        if len(form["full_name"]) < 2:
            errors.append("Please enter your full name.")
        if not cropped_photo:
            errors.append("Please upload and save a profile photo.")
        if len(form["email"]) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["email"]):
            errors.append("Please enter a valid email address.")
        if not re.fullmatch(r"\+?[0-9]{10,15}", form["mobile"]):
            errors.append("Enter a valid mobile number (10–15 digits).")
        if form["gender"] not in ("Bride", "Groom"):
            errors.append("Please choose Bride or Groom.")
        try:
            age = calculate_age(form["date_of_birth"])
            if age < 18 or age > 100:
                errors.append("You must be at least 18 years old to register.")
        except (ValueError, TypeError):
            errors.append("Please enter a valid date of birth.")
        if len(form["password"]) < 8:
            errors.append("Password must contain at least 8 characters.")
        if form["password"] != form["confirm_password"]:
            errors.append("Passwords do not match.")

        db = get_db()
        if not errors:
            existing = db.execute(
                "SELECT email, mobile FROM users WHERE email = ? OR mobile = ?",
                (form["email"], form["mobile"])
            ).fetchone()
            if existing:
                if existing["email"].lower() == form["email"]:
                    errors.append("An account with this email already exists.")
                if existing["mobile"] == form["mobile"]:
                    errors.append("An account with this mobile number already exists.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("register.html", form=form)

        saved_photo_path = None
        try:
            cursor = db.execute("""
                INSERT INTO users (full_name, email, mobile, password_hash, gender, date_of_birth, is_approved)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
            """, (
                form["full_name"], form["email"], form["mobile"],
                generate_password_hash(form["password"]),
                form["gender"], form["date_of_birth"]
            ))
            user_id = cursor.lastrowid
            matrimony_id = f"IRM{100000 + user_id}"
            db.execute("UPDATE users SET matrimony_id = ? WHERE id = ?", (matrimony_id, user_id))
            saved_photo_path = save_cropped_photo(cropped_photo, user_id)
            db.execute(
                "INSERT INTO profiles (user_id, profile_created_by, photo_path) VALUES (?, ?, ?)",
                (user_id, form["profile_created_by"], saved_photo_path)
            )
            add_admin_notification(
                db, "registration", "New member registration",
                f"{form['full_name']} ({matrimony_id}) is waiting for profile review.",
                url_for("admin_view_profile", user_id=user_id)
            )
            mark_notifications_read(db, user_id)
            db.commit()
        except ValueError as error:
            db.rollback()
            if saved_photo_path:
                os.remove(os.path.join(BASE_DIR, "static", saved_photo_path))
            flash(str(error), "danger")
            return render_template("register.html", form=form)
        except sqlite3.IntegrityError:
            db.rollback()
            if saved_photo_path:
                os.remove(os.path.join(BASE_DIR, "static", saved_photo_path))
            flash("An account with those details already exists.", "danger")
            return render_template("register.html", form=form)

        flash(f"Registration successful! Your Matrimony ID is {matrimony_id}. Your profile is pending admin approval.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("""
            SELECT * FROM users
            WHERE email = ? COLLATE NOCASE OR mobile = ?
        """, (identifier.lower(), identifier)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            if not user["account_active"]:
                flash("This account is inactive. Please contact the administrator.", "danger")
                return render_template("login.html")
            if user["is_admin"] and not user["admin_active"]:
                flash("This administrator account is inactive.", "danger")
                return render_template("login.html")
            if not user["is_admin"]:
                if user["is_approved"] == "PENDING":
                    flash("Your profile is currently pending admin verification. Please try again later.", "warning")
                    return render_template("login.html")
                elif user["is_approved"] == "REJECTED":
                    reason = user["rejection_reason"] or "Profile details require corrections."
                    flash(f"Profile verification failed. Reason: {reason}", "danger")
                    return render_template("login.html")

            support_token = session.get("support_token")
            session.clear()
            if support_token:
                session["support_token"] = support_token
            session["user_id"] = user["id"]
            if user["is_admin"]:
                session["login_ad_pending"] = False
                record_admin_login(get_db(), user, "login")
            else:
                session["login_ad_nonce"] = secrets.token_urlsafe(24)
                session["login_ad_pending"] = True
            flash("Welcome back!", "success")
            return redirect(url_for("admin_dashboard" if user["is_admin"] else "index"))

        flash("Invalid credentials.", "danger")

    return render_template("login.html")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("user_id"):
        u = current_user()
        if u and u["is_admin"]:
            return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE (email=? COLLATE NOCASE OR mobile=?) AND is_admin=1", (identifier, identifier)).fetchone()
        if user and user["admin_active"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            record_admin_login(get_db(), user, "login")
            flash("Admin login successful.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.", "danger")
    return render_template("admin_login.html")


@app.route("/admin/accounts", methods=["GET", "POST"])
@login_required
@admin_required
def admin_accounts():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        mobile = re.sub(r"\s+", "", request.form.get("mobile", ""))
        password = request.form.get("password", "")
        role = request.form.get("admin_role", "ADMIN").upper()
        permissions = sorted(set(request.form.getlist("permissions")) & set(ADMIN_PERMISSIONS))
        admin_id = request.form.get("admin_id", "").strip()
        valid = (
            2 <= len(name) <= 120
            and len(email) <= 254
            and bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))
            and bool(re.fullmatch(r"\+?[0-9]{10,15}", mobile))
            and role in ("ADMIN", "SUPER_ADMIN")
        )
        if not valid:
            flash("Enter a valid name, email, mobile number, and administrator role.", "warning")
        elif not admin_id and len(password) < 12:
            flash("New administrator passwords must contain at least 12 characters.", "warning")
        elif admin_id and password and len(password) < 12:
            flash("Administrator passwords must contain at least 12 characters.", "warning")
        elif admin_id and role == "SUPER_ADMIN" and not has_admin_permission(current_user(), "admins"):
            abort(403)
        else:
            target = None
            if admin_id:
                try:
                    admin_id = int(admin_id)
                except ValueError:
                    abort(400)
                target = db.execute(
                    "SELECT id, admin_role, admin_active FROM users WHERE id=? AND is_admin=1",
                    (admin_id,)
                ).fetchone()
                if not target:
                    abort(404)
                if target["id"] == session["user_id"] and (
                    role != "SUPER_ADMIN" or not request.form.get("active", "1") == "1"
                ):
                    flash("You cannot remove your own Super Admin access or deactivate your account.", "warning")
                    return redirect(url_for("admin_accounts"))
            if role == "SUPER_ADMIN" and not has_admin_permission(current_user(), "admins"):
                abort(403)
            active = 1 if request.form.get("active", "1") == "1" else 0
            if target and target["admin_role"] == "SUPER_ADMIN" and target["admin_active"] and (
                role != "SUPER_ADMIN" or not active
            ):
                remaining = db.execute(
                    "SELECT COUNT(*) FROM users WHERE is_admin=1 AND admin_role='SUPER_ADMIN' "
                    "AND admin_active=1 AND id!=?",
                    (admin_id,)
                ).fetchone()[0]
                if not remaining:
                    flash("At least one active Super Admin must remain.", "warning")
                    return redirect(url_for("admin_accounts"))
            try:
                if target:
                    db.execute(
                        "UPDATE users SET full_name=?, email=?, mobile=?, admin_role=?, "
                        "admin_permissions=?, admin_active=? WHERE id=?",
                        (name, email, mobile, role, ",".join(permissions), active, admin_id)
                    )
                    if password:
                        db.execute(
                            "UPDATE users SET password_hash=? WHERE id=?",
                            (generate_password_hash(password), admin_id)
                        )
                    flash("Administrator account updated.", "success")
                else:
                    db.execute(
                        "INSERT INTO users (full_name, email, mobile, password_hash, gender, "
                        "date_of_birth, is_approved, is_admin, admin_role, admin_permissions, admin_active) "
                        "VALUES (?, ?, ?, ?, 'Groom', '1990-01-01', 'APPROVED', 1, ?, ?, 1)",
                        (name, email, mobile, generate_password_hash(password), role, ",".join(permissions))
                    )
                    flash("Administrator account created.", "success")
                db.commit()
                return redirect(url_for("admin_accounts"))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("That email address or mobile number is already in use.", "warning")
    admins = db.execute(
        "SELECT id, full_name, email, mobile, admin_role, admin_permissions, admin_active, created_at "
        "FROM users WHERE is_admin=1 ORDER BY admin_role DESC, full_name COLLATE NOCASE"
    ).fetchall()
    return render_template(
        "admin_accounts.html", admins=admins, permissions=ADMIN_PERMISSIONS
    )


@app.route("/admin/accounts/<int:admin_id>/action", methods=["POST"])
@login_required
@admin_required
def admin_account_action(admin_id):
    db = get_db()
    target = db.execute(
        "SELECT id, admin_role, admin_active FROM users WHERE id=? AND is_admin=1",
        (admin_id,)
    ).fetchone()
    if not target:
        abort(404)
    if admin_id == session["user_id"]:
        flash("You cannot deactivate or delete your own administrator account.", "warning")
        return redirect(url_for("admin_accounts"))
    action = request.form.get("action", "")
    if action not in ("activate", "deactivate", "delete"):
        abort(400)
    if action in ("deactivate", "delete") and target["admin_role"] == "SUPER_ADMIN" and target["admin_active"]:
        remaining = db.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin=1 AND admin_role='SUPER_ADMIN' "
            "AND admin_active=1 AND id!=?",
            (admin_id,)
        ).fetchone()[0]
        if not remaining:
            flash("At least one active Super Admin must remain.", "warning")
            return redirect(url_for("admin_accounts"))
    if action == "delete":
        db.execute(
            "UPDATE users SET admin_active=0, admin_permissions='dashboard' WHERE id=?",
            (admin_id,)
        )
        flash("Administrator access removed. The account record is retained for audit history.", "success")
    else:
        db.execute(
            "UPDATE users SET admin_active=? WHERE id=?",
            (1 if action == "activate" else 0, admin_id)
        )
        flash("Administrator account {}.".format("activated" if action == "activate" else "deactivated"), "success")
    db.commit()
    return redirect(url_for("admin_accounts"))


@app.route("/admin/activity")
@login_required
@admin_required
def admin_activity():
    db = get_db()
    query = request.args.get("q", "").strip()[:100]
    admin_id = request.args.get("admin_id", "").strip()
    activity_type = request.args.get("activity_type", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    valid_admin_ids = {str(row["id"]) for row in db.execute(
        "SELECT id FROM users WHERE is_admin=1"
    ).fetchall()}
    if admin_id not in valid_admin_ids:
        admin_id = ""
    for value_name, value in (("from_date", from_date), ("to_date", to_date)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                if value_name == "from_date":
                    from_date = ""
                else:
                    to_date = ""
    activity_conditions = []
    activity_params = []
    login_conditions = []
    login_params = []
    if admin_id:
        activity_conditions.append("admin_id=?")
        activity_params.append(int(admin_id))
        login_conditions.append("admin_id=?")
        login_params.append(int(admin_id))
    if activity_type:
        activity_conditions.append("action=?")
        activity_params.append(activity_type)
    if query:
        activity_conditions.append("(admin_name LIKE ? OR endpoint LIKE ? OR details LIKE ?)")
        activity_params.extend([f"%{query}%"] * 3)
        login_conditions.append("(admin_name LIKE ? OR admin_email LIKE ? OR ip_address LIKE ?)")
        login_params.extend([f"%{query}%"] * 3)
    for column, value in (("created_at", from_date),):
        if value:
            activity_conditions.append(f"{column}>=?")
            activity_params.append(value + " 00:00:00")
            login_conditions.append(f"{column}>=?")
            login_params.append(value + " 00:00:00")
    if to_date:
        activity_conditions.append("created_at<?")
        activity_params.append((date.fromisoformat(to_date) + timedelta(days=1)).isoformat() + " 00:00:00")
        login_conditions.append("created_at<?")
        login_params.append((date.fromisoformat(to_date) + timedelta(days=1)).isoformat() + " 00:00:00")
    activity_sql = "SELECT * FROM admin_activity_logs"
    login_sql = "SELECT * FROM admin_login_logs"
    if activity_conditions:
        activity_sql += " WHERE " + " AND ".join(activity_conditions)
    if login_conditions:
        login_sql += " WHERE " + " AND ".join(login_conditions)
    activity_rows = db.execute(activity_sql + " ORDER BY id DESC LIMIT 500", activity_params).fetchall()
    login_rows = db.execute(login_sql + " ORDER BY id DESC LIMIT 500", login_params).fetchall()
    activity_types = [row["action"] for row in db.execute(
        "SELECT DISTINCT action FROM admin_activity_logs ORDER BY action"
    ).fetchall()]
    admins = db.execute(
        "SELECT id, full_name FROM users WHERE is_admin=1 ORDER BY full_name COLLATE NOCASE"
    ).fetchall()
    return render_template(
        "admin_activity.html", activity_rows=activity_rows, login_rows=login_rows,
        admins=admins, activity_types=activity_types, filters={
            "q": query, "admin_id": admin_id, "activity_type": activity_type,
            "from_date": from_date, "to_date": to_date
        }
    )


def admin_report_filters():
    db = get_db()
    filters = {
        key: request.args.get(key, "").strip()
        for key in ("from_date", "to_date", "admin_id", "user", "activity_type",
                    "message_type", "status", "role", "q")
    }
    for key in ("from_date", "to_date"):
        if filters[key]:
            try:
                date.fromisoformat(filters[key])
            except ValueError:
                filters[key] = ""
    admin_ids = {str(row["id"]) for row in db.execute(
        "SELECT id FROM users WHERE is_admin=1"
    ).fetchall()}
    if filters["admin_id"] not in admin_ids:
        filters["admin_id"] = ""
    if filters["message_type"] not in ("", "user", "auto", "admin"):
        filters["message_type"] = ""
    if filters["status"] not in ("", "OPEN", "CLOSED", "READ", "UNREAD", "ACTIVE", "INACTIVE"):
        filters["status"] = ""
    if filters["role"] not in ("", "USER", "ADMIN", "SUPER_ADMIN"):
        filters["role"] = ""
    filters["q"] = filters["q"][:100]
    filters["user"] = filters["user"][:100]

    conditions = []
    params = []
    if filters["from_date"]:
        conditions.append("sm.created_at>=?")
        params.append(filters["from_date"] + " 00:00:00")
    if filters["to_date"]:
        conditions.append("sm.created_at<?")
        params.append((date.fromisoformat(filters["to_date"]) + timedelta(days=1)).isoformat() + " 00:00:00")
    if filters["admin_id"]:
        conditions.append("sm.sender_admin_id=?")
        params.append(int(filters["admin_id"]))
    if filters["user"]:
        conditions.append("(sc.visitor_name LIKE ? OR sc.visitor_email LIKE ?)")
        params.extend([f"%{filters['user']}%"] * 2)
    if filters["message_type"] == "user":
        conditions.append("sm.sender_role='visitor'")
    elif filters["message_type"] == "auto":
        conditions.append("sm.is_automated=1")
    elif filters["message_type"] == "admin":
        conditions.append("sm.sender_role='admin' AND sm.is_automated=0")
    if filters["status"] in ("OPEN", "CLOSED"):
        conditions.append("sc.status=?")
        params.append(filters["status"])
    elif filters["status"] == "READ":
        conditions.append("sm.is_read=1")
    elif filters["status"] == "UNREAD":
        conditions.append("sm.is_read=0 AND sm.sender_role='visitor'")
    if filters["role"] == "USER":
        conditions.append("sm.sender_role='visitor'")
    elif filters["role"] == "ADMIN":
        conditions.append("u.admin_role='ADMIN'")
    elif filters["role"] == "SUPER_ADMIN":
        conditions.append("u.admin_role='SUPER_ADMIN'")
    if filters["q"]:
        conditions.append("(sm.body LIKE ? OR sc.visitor_name LIKE ? OR sc.visitor_email LIKE ?)")
        params.extend([f"%{filters['q']}%"] * 3)
    sql = """
        SELECT sm.id, sm.created_at, sc.visitor_name, sc.visitor_email, sc.status,
               sm.sender_role, sm.sender_admin_id, sm.body, sm.is_read, sm.is_automated,
               u.full_name AS admin_name, COALESCE(u.admin_role, 'USER') AS admin_role
        FROM support_messages sm
        JOIN support_conversations sc ON sc.id=sm.conversation_id
        LEFT JOIN users u ON u.id=sm.sender_admin_id
    """
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    message_rows = db.execute(sql + " ORDER BY sm.id DESC", params).fetchall()

    log_conditions = []
    log_params = []
    if filters["from_date"]:
        log_conditions.append("l.created_at>=?")
        log_params.append(filters["from_date"] + " 00:00:00")
    if filters["to_date"]:
        log_conditions.append("l.created_at<?")
        log_params.append((date.fromisoformat(filters["to_date"]) + timedelta(days=1)).isoformat() + " 00:00:00")
    if filters["admin_id"]:
        log_conditions.append("l.admin_id=?")
        log_params.append(int(filters["admin_id"]))
    if filters["activity_type"]:
        log_conditions.append("l.action=?")
        log_params.append(filters["activity_type"])
    if filters["role"] in ("ADMIN", "SUPER_ADMIN"):
        log_conditions.append("u.admin_role=?")
        log_params.append(filters["role"])
    if filters["q"]:
        log_conditions.append("(l.admin_name LIKE ? OR l.endpoint LIKE ? OR l.details LIKE ?)")
        log_params.extend([f"%{filters['q']}%"] * 3)
    log_sql = """
        SELECT l.*, u.admin_role FROM admin_activity_logs l
        LEFT JOIN users u ON u.id=l.admin_id
    """
    if log_conditions:
        log_sql += " WHERE " + " AND ".join(log_conditions)
    activity_rows = db.execute(log_sql + " ORDER BY l.id DESC", log_params).fetchall()

    login_conditions = []
    login_params = []
    if filters["from_date"]:
        login_conditions.append("l.created_at>=?")
        login_params.append(filters["from_date"] + " 00:00:00")
    if filters["to_date"]:
        login_conditions.append("l.created_at<?")
        login_params.append((date.fromisoformat(filters["to_date"]) + timedelta(days=1)).isoformat() + " 00:00:00")
    if filters["admin_id"]:
        login_conditions.append("l.admin_id=?")
        login_params.append(int(filters["admin_id"]))
    if filters["role"] in ("ADMIN", "SUPER_ADMIN"):
        login_conditions.append("u.admin_role=?")
        login_params.append(filters["role"])
    if filters["q"]:
        login_conditions.append("(l.admin_name LIKE ? OR l.admin_email LIKE ? OR l.ip_address LIKE ?)")
        login_params.extend([f"%{filters['q']}%"] * 3)
    login_sql = """
        SELECT l.*, u.admin_role FROM admin_login_logs l
        LEFT JOIN users u ON u.id=l.admin_id
    """
    if login_conditions:
        login_sql += " WHERE " + " AND ".join(login_conditions)
    login_rows = db.execute(login_sql + " ORDER BY l.id DESC", login_params).fetchall()

    key_rows = db.execute(
        "SELECT id, keyword, reply, created_at, updated_at FROM support_auto_replies ORDER BY id DESC"
    ).fetchall()
    if filters["from_date"]:
        key_rows = [row for row in key_rows if row["created_at"] >= filters["from_date"] + " 00:00:00"]
    if filters["to_date"]:
        end_date = (date.fromisoformat(filters["to_date"]) + timedelta(days=1)).isoformat() + " 00:00:00"
        key_rows = [row for row in key_rows if row["created_at"] < end_date]
    if filters["q"]:
        search_like = f"%{filters['q']}%"
        key_rows = [row for row in key_rows if search_like.strip("%").casefold() in
                    (row["keyword"] + " " + row["reply"]).casefold()]
    admins = db.execute(
        "SELECT id, full_name, admin_role FROM users WHERE is_admin=1 ORDER BY full_name COLLATE NOCASE"
    ).fetchall()
    activity_types = [row["action"] for row in db.execute(
        "SELECT DISTINCT action FROM admin_activity_logs ORDER BY action"
    ).fetchall()]
    return {
        "filters": filters, "messages": message_rows, "activity": activity_rows,
        "logins": login_rows, "keys": key_rows, "admins": admins,
        "activity_types": activity_types,
    }


@app.route("/admin/reports")
@login_required
@admin_required
def admin_reports():
    report = admin_report_filters()
    return render_template("admin_reports.html", report=report, filters=report["filters"])


@app.route("/admin/reports/messages/delete", methods=["POST"])
@login_required
@admin_required
def admin_reports_delete():
    raw_ids = request.form.getlist("message_ids")
    try:
        message_ids = list(dict.fromkeys(int(value) for value in raw_ids))
    except ValueError:
        abort(400)
    if not message_ids or any(message_id <= 0 for message_id in message_ids):
        flash("Select at least one valid support message to delete.", "warning")
        return redirect(url_for("admin_reports", **admin_report_filters()["filters"]))
    if len(message_ids) > 500:
        flash("Select no more than 500 messages at a time.", "warning")
        return redirect(url_for("admin_reports", **admin_report_filters()["filters"]))

    report = admin_report_filters()
    visible_ids = {row["id"] for row in report["messages"]}
    if not set(message_ids).issubset(visible_ids):
        abort(400)

    db = get_db()
    placeholders = ",".join("?" for _ in message_ids)
    cursor = db.execute(
        f"DELETE FROM support_messages WHERE id IN ({placeholders})",
        message_ids
    )
    db.commit()
    flash(f"Deleted {cursor.rowcount} selected support message(s). Conversations were retained.", "success")
    return redirect(url_for("admin_reports", **report["filters"]))


@app.route("/admin/reports/export.xlsx")
@login_required
@admin_required
def admin_reports_export():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    report = admin_report_filters()
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheets = (
        ("User messages", ("ID", "Date", "User", "Email", "Message", "Status", "Read"), [
            (row["id"], row["created_at"], row["visitor_name"], row["visitor_email"],
             row["body"], row["status"], "Yes" if row["is_read"] else "No")
            for row in report["messages"] if row["sender_role"] == "visitor"
        ]),
        ("Automatic replies", ("ID", "Date", "User", "Reply type", "Reply"), [
            (row["id"], row["created_at"], row["visitor_name"], "Automatic keyword reply", row["body"])
            for row in report["messages"] if row["is_automated"]
        ]),
        ("Admin replies", ("ID", "Date", "User", "Admin", "Role", "Message"), [
            (row["id"], row["created_at"], row["visitor_name"], row["admin_name"],
             row["admin_role"], row["body"])
            for row in report["messages"] if row["sender_role"] == "admin" and not row["is_automated"]
        ]),
        ("Keys", ("ID", "Key", "Reply", "Created", "Updated"), [
            tuple(row) for row in report["keys"]
        ]),
        ("Admin logins", ("ID", "Admin", "Email", "Role", "Event", "IP", "Date"), [
            (row["id"], row["admin_name"], row["admin_email"], row["admin_role"],
             row["event_type"], row["ip_address"], row["created_at"])
            for row in report["logins"]
        ]),
        ("Admin activities", ("ID", "Admin", "Role", "Action", "Endpoint", "Details", "Date"), [
            (row["id"], row["admin_name"], row["admin_role"], row["action"],
             row["endpoint"], row["details"], row["created_at"])
            for row in report["activity"]
        ]),
    )
    for title, headers, rows in sheets:
        sheet = workbook.create_sheet(title)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="762B4B")
            cell.alignment = Alignment(vertical="center")
        for column in sheet.columns:
            width = min(60, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            sheet.column_dimensions[column[0].column_letter].width = width
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Irumanam_Admin_Reports_{}.xlsx".format(date.today().isoformat())
    )


def contact_validation_status(db, member):
    email = (member["email"] or "").strip()
    mobile = re.sub(r"\s+", "", member["mobile"] or "")
    email_in_use = db.execute(
        "SELECT 1 FROM users WHERE id!=? AND email=? COLLATE NOCASE LIMIT 1",
        (member["id"], email)
    ).fetchone() is not None
    mobile_in_use = db.execute(
        "SELECT 1 FROM users WHERE id!=? AND mobile=? LIMIT 1",
        (member["id"], mobile)
    ).fetchone() is not None
    return {
        "email_format_valid": len(email) <= 254 and bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)),
        "email_in_use": email_in_use,
        "mobile_format_valid": bool(re.fullmatch(r"\+?[0-9]{10,15}", mobile)),
        "mobile_in_use": mobile_in_use,
    }


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    status_filter = request.args.get("status", "PENDING").upper()
    if status_filter not in ("ALL", "PENDING", "APPROVED", "REJECTED"):
        status_filter = "PENDING"
    
    query = request.args.get("q", "").strip()
    cond = ["u.is_admin = 0", "u.account_active = 1"]
    params = []
    if status_filter != "ALL":
        cond.append("u.is_approved = ?")
        params.append(status_filter)
    if query:
        like = f"%{query}%"
        cond.append("(u.full_name LIKE ? OR u.matrimony_id LIKE ? OR u.email LIKE ?)")
        params.extend([like, like, like])
    
    where_clause = "WHERE " + " AND ".join(cond)
    profiles = db.execute(f"""
        SELECT u.id, u.matrimony_id, u.full_name, u.email, u.mobile, u.gender, u.date_of_birth,
               u.is_approved, u.rejection_reason, u.plan, u.plan_until, u.created_at,
               p.education, p.occupation, p.city, p.photo_path
        FROM users u LEFT JOIN profiles p ON p.user_id = u.id
        {where_clause}
        ORDER BY u.created_at DESC LIMIT 100
    """, params).fetchall()
    profiles = [dict(profile) for profile in profiles]
    for profile in profiles:
        profile.update(contact_validation_status(db, profile))
    
    counts = {
        "pending": db.execute("SELECT COUNT(*) FROM users WHERE is_approved='PENDING' AND is_admin=0 AND account_active=1").fetchone()[0],
        "approved": db.execute("SELECT COUNT(*) FROM users WHERE is_approved='APPROVED' AND is_admin=0 AND account_active=1").fetchone()[0],
        "rejected": db.execute("SELECT COUNT(*) FROM users WHERE is_approved='REJECTED' AND is_admin=0 AND account_active=1").fetchone()[0],
        "total": db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0 AND account_active=1").fetchone()[0]
    }
    counts["payments_pending"] = db.execute(
        "SELECT COUNT(*) FROM premium_payments WHERE status='PENDING'"
    ).fetchone()[0]
    counts["support_open"] = db.execute(
        "SELECT COUNT(DISTINCT conversation_id) FROM support_messages sm JOIN support_conversations sc ON sc.id=sm.conversation_id WHERE sc.status='OPEN'"
    ).fetchone()[0]
    overview = {
        "total_users": db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0 AND account_active=1").fetchone()[0],
        "total_keys": db.execute("SELECT COUNT(*) FROM support_auto_replies").fetchone()[0],
        "total_messages": db.execute("SELECT COUNT(*) FROM support_messages").fetchone()[0],
        "pending_messages": db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE sender_role='visitor' AND is_read=0"
        ).fetchone()[0],
        "visitor_messages": db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE sender_role='visitor'"
        ).fetchone()[0],
        "automated_replies": db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE is_automated=1"
        ).fetchone()[0],
        "admin_replies": db.execute(
            "SELECT COUNT(*) FROM support_messages WHERE sender_role='admin' AND is_automated=0"
        ).fetchone()[0],
        "admin_activities": db.execute("SELECT COUNT(*) FROM admin_activity_logs").fetchone()[0],
    }
    recent_activities = db.execute(
        "SELECT admin_name, action, endpoint, created_at FROM admin_activity_logs ORDER BY id DESC LIMIT 6"
    ).fetchall()
    recent_logins = db.execute(
        "SELECT admin_name, admin_email, event_type, ip_address, created_at "
        "FROM admin_login_logs ORDER BY id DESC LIMIT 5"
    ).fetchall()
    return render_template(
        "admin_dashboard.html", profiles=profiles, counts=counts,
        status_filter=status_filter, query=query, overview=overview,
        recent_activities=recent_activities, recent_logins=recent_logins
    )


ADVERTISEMENT_AUDIENCES = {
    "ALL": "All users",
    "FREE": "Free users",
    "PREMIUM": "Premium users",
    "MALE": "Male users",
    "FEMALE": "Female users",
    "NEW": "New users (registered in the last 30 days)",
    "SELECTED": "Selected users",
}
ADVERTISEMENT_FREQUENCIES = {
    "EVERY_LOGIN": "Every login",
    "DAILY": "Once per day",
    "ONCE": "Once per user",
}
ADVERTISEMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def save_advertisement_image(upload):
    if not upload or not upload.filename or "." not in upload.filename:
        raise ValueError("Choose an advertisement image.")
    extension = secure_filename(upload.filename).rsplit(".", 1)[-1].lower()
    if extension not in ADVERTISEMENT_EXTENSIONS:
        raise ValueError("Advertisement images must be PNG, JPG, JPEG, or WEBP.")

    from PIL import Image, UnidentifiedImageError

    try:
        upload.stream.seek(0)
        with Image.open(upload.stream) as image:
            image.verify()
        upload.stream.seek(0)
        with Image.open(upload.stream) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Choose a valid PNG, JPG, JPEG, or WEBP image.")
            if image.width > 6000 or image.height > 6000:
                raise ValueError("Advertisement images must be no larger than 6000 by 6000 pixels.")
            image.load()
            if extension in ("jpg", "jpeg"):
                image = image.convert("RGB")
                output_extension = "jpg"
            else:
                output_extension = "png" if image.format == "PNG" else "webp"
            filename = f"ad_{uuid.uuid4().hex}.{output_extension}"
            directory = os.path.join(BASE_DIR, "private_media", "advertisements")
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, filename)
            save_options = {"optimize": True}
            if output_extension == "jpg":
                save_options["quality"] = 88
            image.save(path, format={"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}[output_extension], **save_options)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("The uploaded advertisement file is not a valid image.") from error
    return filename


def advertisement_form_values(form):
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    redirect_url = form.get("redirect_url", "").strip()
    start_text = form.get("start_date", "").strip()
    end_text = form.get("end_date", "").strip()
    try:
        start = date.fromisoformat(start_text)
        end = date.fromisoformat(end_text)
    except ValueError as error:
        raise ValueError("Choose valid advertisement start and end dates.") from error
    try:
        display_days = int(form.get("display_days", ""))
    except ValueError as error:
        raise ValueError("Enter a valid number of display days.") from error

    audience = form.get("target_audience", "")
    frequency = form.get("display_frequency", "")
    if not 3 <= len(title) <= 120:
        raise ValueError("Advertisement title must be between 3 and 120 characters.")
    if len(description) > 1000:
        raise ValueError("Advertisement description cannot exceed 1000 characters.")
    if len(redirect_url) > 1000:
        raise ValueError("Redirect URLs cannot exceed 1000 characters.")
    if redirect_url:
        parsed_url = urlsplit(redirect_url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError("Enter a complete HTTP or HTTPS redirect URL.")
    if start > end:
        raise ValueError("The end date must be on or after the start date.")
    if not 1 <= display_days <= 365:
        raise ValueError("Display duration must be from 1 to 365 days.")
    if audience not in ADVERTISEMENT_AUDIENCES:
        raise ValueError("Choose a valid target audience.")
    if frequency not in ADVERTISEMENT_FREQUENCIES:
        raise ValueError("Choose a valid display frequency.")
    return {
        "title": title,
        "description": description,
        "redirect_url": redirect_url,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "display_days": display_days,
        "target_audience": audience,
        "display_frequency": frequency,
        "is_enabled": 1 if form.get("is_enabled") == "1" else 0,
    }


def selected_advertisement_users(db, raw_user_ids):
    user_ids = sorted({int(value) for value in raw_user_ids if value.isdigit()})
    if not user_ids:
        return []
    placeholders = ",".join("?" for _ in user_ids)
    rows = db.execute(
        f"SELECT id FROM users WHERE id IN ({placeholders}) AND is_admin=0 "
        "AND is_approved='APPROVED' AND account_active=1",
        user_ids
    ).fetchall()
    if len(rows) != len(user_ids):
        raise ValueError("One or more selected users are no longer active approved members.")
    return user_ids


def advertisement_admin_data(db, actor):
    ads = db.execute("""
        SELECT a.*,
               (SELECT COUNT(*) FROM advertisement_impressions i WHERE i.advertisement_id=a.id) AS impressions,
               (SELECT COUNT(DISTINCT i.user_id) FROM advertisement_impressions i WHERE i.advertisement_id=a.id) AS unique_users,
               (SELECT COUNT(*) FROM advertisement_impressions i WHERE i.advertisement_id=a.id AND i.closed_at IS NOT NULL) AS closes
        FROM advertisements a
        ORDER BY a.created_at DESC, a.id DESC
    """).fetchall()
    today = date.today()
    ad_rows = []
    for ad in ads:
        values = dict(ad)
        values["status"] = advertisement_status(ad, today)
        values["expiry_date"] = advertisement_expiry(ad).isoformat()
        values["selected_users"] = [
            row["user_id"] for row in db.execute(
                "SELECT user_id FROM advertisement_audience_users "
                "WHERE advertisement_id=? ORDER BY user_id",
                (ad["id"],)
            )
        ]
        ad_rows.append(values)
    history_rows = db.execute(
        "SELECT * FROM advertisement_history ORDER BY changed_at DESC, id DESC"
    ).fetchall()
    history = []
    for row in history_rows:
        item = dict(row)
        try:
            item["selected_user_count"] = len(json.loads(item["selected_users"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            item["selected_user_count"] = 0
        history.append(item)
    members = db.execute("""
        SELECT u.id, u.full_name, u.matrimony_id, u.gender, u.plan, u.plan_until
        FROM users u WHERE u.is_admin=0 AND u.is_approved='APPROVED' AND u.account_active=1
        ORDER BY u.full_name COLLATE NOCASE
    """).fetchall()
    return render_template(
        "admin_advertisements.html", advertisements=ad_rows, history=history,
        members=members, audiences=ADVERTISEMENT_AUDIENCES,
        frequencies=ADVERTISEMENT_FREQUENCIES, today=today.isoformat(),
        actor=actor
    )


@app.route("/admin/advertisements")
@login_required
@admin_required
def admin_advertisements():
    return advertisement_admin_data(get_db(), current_user())


@app.route("/admin/advertisements/new", methods=["GET", "POST"])
@app.route("/admin/advertisements/<int:ad_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_advertisement_form(ad_id=None):
    db = get_db()
    actor = current_user()
    ad = None
    selected_users = []
    if ad_id is not None:
        ad = db.execute(
            "SELECT * FROM advertisements WHERE id=? AND is_deleted=0", (ad_id,)
        ).fetchone()
        if not ad:
            abort(404)
        selected_users = [
            row["user_id"] for row in db.execute(
                "SELECT user_id FROM advertisement_audience_users WHERE advertisement_id=?",
                (ad_id,)
            )
        ]

    if request.method == "POST":
        new_image = None
        try:
            values = advertisement_form_values(request.form)
            selected_ids = (
                selected_advertisement_users(db, request.form.getlist("selected_users"))
                if values["target_audience"] == "SELECTED" else []
            )
            if values["target_audience"] == "SELECTED" and not selected_ids:
                raise ValueError("Select at least one approved user for this audience.")
            upload = request.files.get("image")
            if upload and upload.filename:
                new_image = save_advertisement_image(upload)
            elif not ad:
                raise ValueError("Upload an image for this advertisement.")

            if ad:
                image_path = new_image or ad["image_path"]
                if values["is_enabled"] and advertisement_expiry({
                    **values, "start_date": values["start_date"]
                }) < date.today():
                    raise ValueError("An advertisement with an expired display period cannot be enabled.")
                db.execute("""
                    UPDATE advertisements SET title=?, description=?, redirect_url=?, image_path=?,
                        start_date=?, end_date=?, display_days=?, target_audience=?,
                        display_frequency=?, is_enabled=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (
                    values["title"], values["description"], values["redirect_url"], image_path,
                    values["start_date"], values["end_date"], values["display_days"],
                    values["target_audience"], values["display_frequency"],
                    values["is_enabled"], ad_id
                ))
                db.execute(
                    "DELETE FROM advertisement_audience_users WHERE advertisement_id=?",
                    (ad_id,)
                )
                db.executemany(
                    "INSERT INTO advertisement_audience_users (advertisement_id,user_id) VALUES (?,?)",
                    [(ad_id, user_id) for user_id in selected_ids]
                )
                updated_ad = db.execute(
                    "SELECT * FROM advertisements WHERE id=?", (ad_id,)
                ).fetchone()
                record_advertisement_history(db, updated_ad, "UPDATED", actor)
                flash("Advertisement updated.", "success")
            else:
                if values["is_enabled"] and advertisement_expiry(values) < date.today():
                    raise ValueError("An advertisement with an expired display period cannot be enabled.")
                cursor = db.execute("""
                    INSERT INTO advertisements (
                        title, description, redirect_url, image_path, start_date, end_date,
                        display_days, target_audience, display_frequency, is_enabled,
                        created_by, created_by_name
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    values["title"], values["description"], values["redirect_url"], new_image,
                    values["start_date"], values["end_date"], values["display_days"],
                    values["target_audience"], values["display_frequency"],
                    values["is_enabled"], actor["id"], actor["full_name"]
                ))
                ad_id = cursor.lastrowid
                db.executemany(
                    "INSERT INTO advertisement_audience_users (advertisement_id,user_id) VALUES (?,?)",
                    [(ad_id, user_id) for user_id in selected_ids]
                )
                created_ad = db.execute(
                    "SELECT * FROM advertisements WHERE id=?", (ad_id,)
                ).fetchone()
                record_advertisement_history(db, created_ad, "CREATED", actor)
                flash("Advertisement created.", "success")
            db.commit()
            return redirect(url_for("admin_advertisements"))
        except ValueError as error:
            db.rollback()
            if new_image:
                image_path = os.path.join(BASE_DIR, "private_media", "advertisements", new_image)
                if os.path.isfile(image_path):
                    os.remove(image_path)
            flash(str(error), "danger")
        except sqlite3.IntegrityError:
            db.rollback()
            if new_image:
                image_path = os.path.join(BASE_DIR, "private_media", "advertisements", new_image)
                if os.path.isfile(image_path):
                    os.remove(image_path)
            raise

    members = db.execute("""
        SELECT u.id, u.full_name, u.matrimony_id, u.gender, u.plan, u.plan_until
        FROM users u WHERE u.is_admin=0 AND u.is_approved='APPROVED' AND u.account_active=1
        ORDER BY u.full_name COLLATE NOCASE
    """).fetchall()
    return render_template(
        "admin_advertisement_form.html", ad=ad, members=members,
        selected_users=selected_users, audiences=ADVERTISEMENT_AUDIENCES,
        form_data=request.form if request.method == "POST" else {},
        frequencies=ADVERTISEMENT_FREQUENCIES, today=date.today().isoformat(),
        default_end_date=(date.today() + timedelta(days=6)).isoformat()
    )


@app.route("/admin/advertisements/<int:ad_id>/action", methods=["POST"])
@login_required
@admin_required
def admin_advertisement_action(ad_id):
    db = get_db()
    actor = current_user()
    ad = db.execute(
        "SELECT * FROM advertisements WHERE id=?", (ad_id,)
    ).fetchone()
    if not ad:
        abort(404)
    action = request.form.get("action", "").lower()
    if ad["is_deleted"]:
        flash("This advertisement is archived and cannot be changed.", "warning")
        return redirect(url_for("admin_advertisements"))
    if action == "enable":
        if advertisement_expiry(ad) < date.today():
            flash("This advertisement's display period has expired. Edit its dates before enabling it.", "warning")
            return redirect(url_for("admin_advertisements"))
        db.execute(
            "UPDATE advertisements SET is_enabled=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ad_id,)
        )
        event = "ENABLED"
        message = "Advertisement enabled."
    elif action == "disable":
        db.execute(
            "UPDATE advertisements SET is_enabled=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ad_id,)
        )
        event = "DISABLED"
        message = "Advertisement disabled."
    elif action == "delete":
        db.execute(
            "UPDATE advertisements SET is_enabled=0, is_deleted=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ad_id,)
        )
        event = "ARCHIVED"
        message = "Advertisement archived. Its image and history have been retained."
    else:
        flash("Choose a valid advertisement action.", "danger")
        return redirect(url_for("admin_advertisements"))
    changed_ad = db.execute(
        "SELECT * FROM advertisements WHERE id=?", (ad_id,)
    ).fetchone()
    record_advertisement_history(db, changed_ad, event, actor)
    db.commit()
    flash(message, "success")
    return redirect(url_for("admin_advertisements"))


@app.route("/admin/advertisements/<int:ad_id>/image")
@login_required
@admin_required
def admin_advertisement_image(ad_id):
    ad = get_db().execute(
        "SELECT image_path FROM advertisements WHERE id=?", (ad_id,)
    ).fetchone()
    if not ad:
        abort(404)
    return send_from_directory(
        os.path.join(BASE_DIR, "private_media", "advertisements"),
        os.path.basename(ad["image_path"])
    )


@app.route("/admin/advertisements/history/<int:history_id>/image")
@login_required
@admin_required
def admin_advertisement_history_image(history_id):
    entry = get_db().execute(
        "SELECT image_path FROM advertisement_history WHERE id=?", (history_id,)
    ).fetchone()
    if not entry:
        abort(404)
    return send_from_directory(
        os.path.join(BASE_DIR, "private_media", "advertisements"),
        os.path.basename(entry["image_path"])
    )


@app.route("/advertisements/<int:ad_id>/image")
@login_required
def advertisement_image(ad_id):
    db = get_db()
    user = current_user()
    ad = db.execute(
        "SELECT * FROM advertisements WHERE id=? AND is_enabled=1 AND is_deleted=0",
        (ad_id,)
    ).fetchone()
    if (
        not ad or session.get("login_ad_id") != ad_id
        or advertisement_status(ad) != "Active"
        or not advertisement_matches_user(db, ad, user)
    ):
        abort(404)
    return send_from_directory(
        os.path.join(BASE_DIR, "private_media", "advertisements"),
        os.path.basename(ad["image_path"])
    )


@app.route("/advertisements/<int:ad_id>/impression", methods=["POST"])
@login_required
def advertisement_impression(ad_id):
    db = get_db()
    user = current_user()
    ad = db.execute(
        "SELECT * FROM advertisements WHERE id=? AND is_enabled=1 AND is_deleted=0",
        (ad_id,)
    ).fetchone()
    login_nonce = session.get("login_ad_nonce")
    if (
        not ad or session.get("login_ad_id") != ad_id or not login_nonce
        or advertisement_status(ad) != "Active"
        or not advertisement_matches_user(db, ad, user)
    ):
        abort(404)
    frequency_key = advertisement_frequency_key(ad, login_nonce)
    cursor = db.execute("""
        INSERT OR IGNORE INTO advertisement_impressions
            (advertisement_id,user_id,frequency_key)
        VALUES (?,?,?)
    """, (ad_id, user["id"], frequency_key))
    db.commit()
    if not cursor.rowcount:
        return jsonify(show=False), 409
    impression = db.execute(
        "SELECT id FROM advertisement_impressions "
        "WHERE advertisement_id=? AND user_id=? AND frequency_key=?",
        (ad_id, user["id"], frequency_key)
    ).fetchone()
    return jsonify(show=True, impression_id=impression["id"])


@app.route("/advertisements/<int:ad_id>/close", methods=["POST"])
@login_required
def advertisement_close(ad_id):
    db = get_db()
    user = current_user()
    ad = db.execute(
        "SELECT display_frequency FROM advertisements WHERE id=?", (ad_id,)
    ).fetchone()
    login_nonce = session.get("login_ad_nonce")
    if not ad or session.get("login_ad_id") != ad_id or not login_nonce:
        abort(404)
    frequency_key = advertisement_frequency_key(ad, login_nonce)
    db.execute("""
        UPDATE advertisement_impressions SET closed_at=CURRENT_TIMESTAMP
        WHERE advertisement_id=? AND user_id=? AND frequency_key=? AND closed_at IS NULL
    """, (ad_id, user["id"], frequency_key))
    db.commit()
    return jsonify(closed=True)


@app.route("/admin/notifications")
@login_required
@admin_required
def admin_notifications():
    db = get_db()
    db.execute("UPDATE admin_activity_notifications SET is_read=1 WHERE is_read=0")
    db.commit()
    items = db.execute(
        "SELECT * FROM admin_activity_notifications ORDER BY id DESC LIMIT 200"
    ).fetchall()
    return render_template("admin_notifications.html", items=items)


@app.route("/admin/notifications/poll")
@login_required
@admin_required
def admin_notifications_poll():
    db = get_db()
    try:
        after_id = max(0, int(request.args.get("after", "0")))
    except ValueError:
        return jsonify(error="Invalid notification cursor."), 400
    items = db.execute(
        "SELECT id, event_type, title, body, target_url, created_at FROM admin_activity_notifications WHERE id>? ORDER BY id LIMIT 30",
        (after_id,)
    ).fetchall()
    unread_count = db.execute(
        "SELECT COUNT(*) FROM admin_activity_notifications WHERE is_read=0"
    ).fetchone()[0]
    latest_id = db.execute(
        "SELECT COALESCE(MAX(id), 0) FROM admin_activity_notifications"
    ).fetchone()[0]
    support_unread = db.execute(
        "SELECT COUNT(*) FROM support_messages WHERE sender_role='visitor' AND is_read=0"
    ).fetchone()[0]
    return jsonify(
        notifications=[dict(item) for item in items],
        unread_count=unread_count,
        latest_id=latest_id,
        support_unread_count=support_unread
    )


@app.route("/admin/notifications/<int:notification_id>/open")
@login_required
@admin_required
def admin_open_notification(notification_id):
    db = get_db()
    item = db.execute(
        "SELECT target_url FROM admin_activity_notifications WHERE id=?", (notification_id,)
    ).fetchone()
    if not item:
        abort(404)
    db.execute(
        "UPDATE admin_activity_notifications SET is_read=1 WHERE id=?", (notification_id,)
    )
    db.commit()
    target = item["target_url"]
    if not target.startswith("/") or target.startswith("//"):
        abort(400)
    return redirect(target)


@app.route("/admin/faqs", methods=["GET", "POST"])
@login_required
@admin_required
def admin_faqs():
    db = get_db()
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        answer = request.form.get("answer", "").strip()
        faq_id = request.form.get("faq_id", "").strip()
        if not question or len(question) > 250 or not answer or len(answer) > 5000:
            flash("Enter a question (up to 250 characters) and answer (up to 5000 characters).", "warning")
        elif faq_id:
            try:
                faq_id = int(faq_id)
            except ValueError:
                abort(400)
            existing = db.execute("SELECT id FROM faqs WHERE id=?", (faq_id,)).fetchone()
            if not existing:
                abort(404)
            db.execute(
                "UPDATE faqs SET question=?, answer=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (question, answer, faq_id)
            )
            db.commit()
            flash("FAQ updated and published.", "success")
            return redirect(url_for("admin_faqs"))
        else:
            sort_order = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM faqs").fetchone()[0]
            db.execute(
                "INSERT INTO faqs (question, answer, sort_order) VALUES (?, ?, ?)",
                (question, answer, sort_order)
            )
            db.commit()
            flash("FAQ added and published.", "success")
            return redirect(url_for("admin_faqs"))
    items = db.execute("SELECT * FROM faqs ORDER BY sort_order, id").fetchall()
    return render_template("admin_faqs.html", items=items)


@app.route("/admin/faqs/<int:faq_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_faq_delete(faq_id):
    db = get_db()
    if not db.execute("SELECT id FROM faqs WHERE id=?", (faq_id,)).fetchone():
        abort(404)
    db.execute("DELETE FROM faqs WHERE id=?", (faq_id,))
    db.commit()
    flash("FAQ deleted from the website.", "success")
    return redirect(url_for("admin_faqs"))


@app.route("/admin/support")
@login_required
@admin_required
def admin_support():
    db = get_db()
    status = request.args.get("status", "OPEN").upper()
    if status not in ("OPEN", "CLOSED", "ALL"):
        status = "OPEN"
    query = request.args.get("q", "").strip()[:100]
    sql = """
        SELECT c.*,
          (SELECT body FROM support_messages WHERE conversation_id=c.id ORDER BY id DESC LIMIT 1) AS last_body,
          (SELECT COUNT(*) FROM support_messages WHERE conversation_id=c.id AND sender_role='visitor' AND is_read=0) AS unread
        FROM support_conversations c
    """
    params = []
    conditions = []
    if status != "ALL":
        conditions.append("c.status=?")
        params.append(status)
    if query:
        conditions.append(
            "(c.visitor_name LIKE ? OR c.visitor_email LIKE ? OR EXISTS "
            "(SELECT 1 FROM support_messages sm WHERE sm.conversation_id=c.id AND sm.body LIKE ?))"
        )
        params.extend([f"%{query}%"] * 3)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    conversations = db.execute(sql + " ORDER BY c.updated_at DESC, c.id DESC", params).fetchall()
    return render_template(
        "admin_support.html", conversations=conversations, status_filter=status, query=query
    )


@app.route("/admin/support/auto-replies", methods=["GET", "POST"])
@login_required
@admin_required
def admin_support_auto_replies():
    db = get_db()
    if request.method == "POST":
        keyword = request.form.get("keyword", "").strip()
        reply = request.form.get("reply", "").strip()
        reply_id = request.form.get("reply_id", "").strip()
        if not keyword or len(keyword) > 100 or not reply or len(reply) > 1000:
            flash("Enter a key (up to 100 characters) and reply (up to 1000 characters).", "warning")
        else:
            existing = None
            if reply_id:
                try:
                    reply_id = int(reply_id)
                except ValueError:
                    abort(400)
                existing = db.execute(
                    "SELECT id FROM support_auto_replies WHERE id=?", (reply_id,)
                ).fetchone()
                if not existing:
                    abort(404)
            duplicate = db.execute(
                "SELECT id FROM support_auto_replies WHERE keyword=? COLLATE NOCASE AND id != ?",
                (keyword, reply_id or 0)
            ).fetchone()
            if duplicate:
                flash("A reply key with that text already exists.", "warning")
            elif reply_id:
                db.execute(
                    "UPDATE support_auto_replies SET keyword=?, reply=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (keyword, reply, reply_id)
                )
                db.commit()
                flash("Automatic reply updated.", "success")
                return redirect(url_for("admin_support_auto_replies"))
            else:
                db.execute(
                    "INSERT INTO support_auto_replies (keyword, reply) VALUES (?, ?)",
                    (keyword, reply)
                )
                db.commit()
                flash("Automatic reply added.", "success")
                return redirect(url_for("admin_support_auto_replies"))
    items = db.execute(
        "SELECT * FROM support_auto_replies ORDER BY keyword COLLATE NOCASE, id"
    ).fetchall()
    return render_template("admin_support_auto_replies.html", items=items)


@app.route("/admin/support/auto-replies/<int:reply_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_support_auto_reply_delete(reply_id):
    db = get_db()
    if not db.execute("SELECT id FROM support_auto_replies WHERE id=?", (reply_id,)).fetchone():
        abort(404)
    db.execute("DELETE FROM support_auto_replies WHERE id=?", (reply_id,))
    db.commit()
    flash("Automatic reply deleted.", "success")
    return redirect(url_for("admin_support_auto_replies"))


@app.route("/admin/support/<int:conversation_id>", methods=["GET", "POST"])
@login_required
@admin_required
def admin_support_conversation(conversation_id):
    db = get_db()
    conversation = db.execute(
        "SELECT * FROM support_conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if not conversation:
        abort(404)
    if request.method == "POST":
        action = request.form.get("action", "reply")
        if action in ("close", "reopen"):
            db.execute(
                "UPDATE support_conversations SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                ("CLOSED" if action == "close" else "OPEN", conversation_id)
            )
            db.commit()
            flash("Support conversation updated.", "success")
        elif action == "reply":
            body = request.form.get("body", "").strip()
            if not body or len(body) > 1000:
                flash("Enter a reply between 1 and 1000 characters.", "warning")
            else:
                db.execute(
                    "INSERT INTO support_messages (conversation_id, sender_role, sender_admin_id, body) VALUES (?, 'admin', ?, ?)",
                    (conversation_id, session["user_id"], body)
                )
                db.execute(
                    "UPDATE support_conversations SET status='OPEN', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (conversation_id,)
                )
                db.commit()
                flash("Reply sent to the visitor.", "success")
        else:
            abort(400)
        return redirect(url_for("admin_support_conversation", conversation_id=conversation_id))
    db.execute(
        "UPDATE support_messages SET is_read=1 WHERE conversation_id=? AND sender_role='visitor' AND is_read=0",
        (conversation_id,)
    )
    db.commit()
    messages = db.execute(
        "SELECT sm.*, u.full_name AS admin_name FROM support_messages sm "
        "LEFT JOIN users u ON u.id=sm.sender_admin_id "
        "WHERE sm.conversation_id=? ORDER BY sm.id",
        (conversation_id,)
    ).fetchall()
    return render_template("admin_support_conversation.html", conversation=conversation, messages=messages)


@app.route("/admin/support/<int:conversation_id>/messages")
@login_required
@admin_required
def admin_support_messages(conversation_id):
    db = get_db()
    if not db.execute(
        "SELECT id FROM support_conversations WHERE id=?", (conversation_id,)
    ).fetchone():
        abort(404)
    try:
        after_id = max(0, int(request.args.get("after", "0")))
    except ValueError:
        return jsonify(error="Invalid message cursor."), 400
    rows = db.execute(
        "SELECT sm.id, sm.sender_role, sm.body, sm.is_automated, sm.created_at, "
        "u.full_name AS admin_name FROM support_messages sm "
        "LEFT JOIN users u ON u.id=sm.sender_admin_id "
        "WHERE sm.conversation_id=? AND sm.id>? ORDER BY sm.id",
        (conversation_id, after_id)
    ).fetchall()
    db.execute(
        "UPDATE support_messages SET is_read=1 WHERE conversation_id=? AND sender_role='visitor' AND is_read=0",
        (conversation_id,)
    )
    db.commit()
    return jsonify(messages=[dict(row) for row in rows])


@app.route("/admin/reports.xlsx")
@login_required
@admin_required
def admin_reports_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    db = get_db()
    workbook = Workbook()
    workbook.remove(workbook.active)
    reports = [
        ("Members", ("User ID", "Matrimony ID", "Full name", "Email", "Mobile", "Gender", "Date of birth",
                     "Approval status", "Rejection reason", "Plan", "Plan expiry", "Registered at",
                     "Profile created by", "Religion", "Mother tongue", "Marital status", "Education",
                     "Occupation", "Country", "State", "City", "About", "Photo path", "Caste", "Star",
                     "Raasi", "Height cm", "Diet"), """
            SELECT u.id, u.matrimony_id, u.full_name, u.email, u.mobile, u.gender, u.date_of_birth,
                   u.is_approved, u.rejection_reason, u.plan, u.plan_until, u.created_at,
                   p.profile_created_by, p.religion, p.mother_tongue, p.marital_status, p.education,
                   p.occupation, p.country, p.state, p.city, p.about_me, p.photo_path, p.caste, p.star,
                   p.raasi, p.height_cm, p.diet
            FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.is_admin=0 ORDER BY u.id
        """),
        ("Premium payments", ("Payment ID", "User ID", "Matrimony ID", "Member", "Plan", "Amount", "Transaction ID",
                              "Screenshot file", "Payment note", "Status", "Start date", "Expiry date", "Admin note",
                              "Submitted at", "Reviewed at"), """
            SELECT pp.id, pp.user_id, u.matrimony_id, u.full_name, pp.plan, pp.amount, pp.transaction_id,
                   pp.screenshot_path, pp.notes, pp.status, pp.start_date, pp.expiry_date, pp.admin_note,
                   pp.created_at, pp.reviewed_at
            FROM premium_payments pp JOIN users u ON u.id=pp.user_id ORDER BY pp.id
        """),
        ("Interests", ("Interest ID", "Sender ID", "Sender", "Receiver ID", "Receiver", "Type", "Status", "Created", "Updated"), """
            SELECT i.id, i.sender_id, s.full_name, i.receiver_id, r.full_name, i.interest_type,
                   i.status, i.created_at, i.updated_at
            FROM interests i JOIN users s ON s.id=i.sender_id JOIN users r ON r.id=i.receiver_id ORDER BY i.id
        """),
        ("Member messages", ("Message ID", "Sender ID", "Sender", "Receiver ID", "Receiver", "Message", "Read", "Created"), """
            SELECT m.id, m.sender_id, s.full_name, m.receiver_id, r.full_name, m.body, m.is_read, m.created_at
            FROM messages m JOIN users s ON s.id=m.sender_id JOIN users r ON r.id=m.receiver_id ORDER BY m.id
        """),
        ("Profile views", ("Viewer ID", "Viewer", "Profile ID", "Profile", "Viewed at"), """
            SELECT v.viewer_id, a.full_name, v.viewed_id, b.full_name, v.viewed_at
            FROM views v JOIN users a ON a.id=v.viewer_id JOIN users b ON b.id=v.viewed_id ORDER BY v.viewed_at
        """),
        ("Preferences", ("User ID", "Member", "Age min", "Age max", "Religion", "Caste", "City", "Marital status"), """
            SELECT p.user_id, u.full_name, p.age_min, p.age_max, p.religion, p.caste, p.city, p.marital_status
            FROM preferences p JOIN users u ON u.id=p.user_id ORDER BY p.user_id
        """),
        ("Blocks", ("Blocker ID", "Blocker", "Blocked ID", "Blocked member", "Reason"), """
            SELECT b.blocker_id, a.full_name, b.blocked_id, c.full_name, b.reason
            FROM blocks b JOIN users a ON a.id=b.blocker_id JOIN users c ON c.id=b.blocked_id ORDER BY b.blocker_id
        """),
        ("Member notifications", ("Notification ID", "User ID", "Member", "Message", "Read", "Created"), """
            SELECT n.id, n.user_id, u.full_name, n.message, n.is_read, n.created_at
            FROM user_notifications n JOIN users u ON u.id=n.user_id ORDER BY n.id
        """),
        ("Support conversations", ("Conversation ID", "Visitor", "Status", "Started", "Last activity", "Message count"), """
            SELECT c.id, c.visitor_name, c.status, c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM support_messages sm WHERE sm.conversation_id=c.id)
            FROM support_conversations c ORDER BY c.id
        """),
        ("Support messages", ("Message ID", "Conversation ID", "Visitor", "Sender", "Message", "Read", "Created"), """
            SELECT m.id, m.conversation_id, c.visitor_name,
                   CASE WHEN m.is_automated=1 THEN 'Auto-reply' ELSE m.sender_role END,
                   m.body, m.is_read, m.created_at
            FROM support_messages m JOIN support_conversations c ON c.id=m.conversation_id ORDER BY m.id
        """),
        ("Admin notifications", ("Notification ID", "Event type", "Title", "Details", "Target", "Read", "Created"), """
            SELECT id, event_type, title, body, target_url, is_read, created_at
            FROM admin_activity_notifications ORDER BY id
        """)
    ]
    for sheet_name, headers, sql in reports:
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(headers)
        for row in db.execute(sql):
            values = []
            for value in row:
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                    value = "'" + value
                values.append(value)
            sheet.append(values)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, sheet.max_row)}"
        for cell in sheet[1]:
            cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="54233D")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.row_dimensions[1].height = 30
        for column_index, header in enumerate(headers, 1):
            maximum = len(str(header))
            for cells in sheet.iter_rows(min_row=2, min_col=column_index, max_col=column_index):
                cell = cells[0]
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                maximum = max(maximum, min(len(str(cell.value or "")), 60))
            sheet.column_dimensions[get_column_letter(column_index)].width = min(max(maximum + 2, 12), 42)
        if sheet.max_row > 1:
            table_ref = f"A1:{get_column_letter(len(headers))}{sheet.max_row}"
            table = Table(displayName="ReportTable{}".format(len(workbook.sheetnames)), ref=table_ref)
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2", showFirstColumn=False, showLastColumn=False,
                showRowStripes=True, showColumnStripes=False
            )
            sheet.add_table(table)
    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="Irumanam_Admin_Reports_{}.xlsx".format(date.today().isoformat())
    )


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    inactive = request.args.get("scope") == "inactive"
    query = request.args.get("q", "").strip()[:120]
    account_filter = 0 if inactive else 1
    status_filter = "" if inactive else " AND u.is_approved='APPROVED'"
    sql = """
        SELECT u.id, u.matrimony_id, u.full_name, u.email, u.mobile, u.gender,
               u.is_approved, u.plan, u.plan_until, u.created_at, u.account_active,
               p.city
        FROM users u LEFT JOIN profiles p ON p.user_id=u.id
        WHERE u.is_admin=0 AND u.account_active=?""" + status_filter
    params = [account_filter]
    if query:
        like = f"%{query}%"
        sql += " AND (u.full_name LIKE ? OR u.matrimony_id LIKE ? OR u.email LIKE ? OR u.mobile LIKE ? OR p.city LIKE ?)"
        params.extend([like] * 5)
    users = get_db().execute(sql + " ORDER BY u.created_at DESC", params).fetchall()
    return render_template("admin_users.html", users=users, inactive=inactive, query=query)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def admin_user_edit(user_id):
    db = get_db()
    member = db.execute("""
        SELECT u.*, p.profile_created_by, p.religion, p.mother_tongue,
               p.marital_status, p.education, p.occupation, p.country, p.state,
               p.city, p.about_me, p.caste, p.star, p.raasi, p.height_cm, p.diet
        FROM users u LEFT JOIN profiles p ON p.user_id=u.id
        WHERE u.id=? AND u.is_admin=0 AND u.account_active=1
    """, (user_id,)).fetchone()
    if not member:
        flash("Active member not found.", "warning")
        return redirect(url_for("admin_users"))

    if request.method == "POST":
        form = {
            "full_name": request.form.get("full_name", "").strip()[:100],
            "email": request.form.get("email", "").strip().lower(),
            "mobile": re.sub(r"\s+", "", request.form.get("mobile", "")),
            "gender": request.form.get("gender", ""),
            "date_of_birth": request.form.get("date_of_birth", ""),
            "is_approved": request.form.get("is_approved", ""),
            "rejection_reason": request.form.get("rejection_reason", "").strip()[:300],
            "plan": request.form.get("plan", "").upper(),
            "plan_until": request.form.get("plan_until", ""),
            "profile_created_by": request.form.get("profile_created_by", "Self"),
            "religion": request.form.get("religion", "").strip()[:80],
            "mother_tongue": request.form.get("mother_tongue", "").strip()[:80],
            "marital_status": request.form.get("marital_status", "Never Married"),
            "education": request.form.get("education", "").strip()[:120],
            "occupation": request.form.get("occupation", "").strip()[:120],
            "country": request.form.get("country", "India").strip()[:80],
            "state": request.form.get("state", "").strip()[:80],
            "city": request.form.get("city", "").strip()[:80],
            "about_me": request.form.get("about_me", "").strip()[:1000],
            "caste": request.form.get("caste", "").strip()[:80],
            "star": request.form.get("star", "").strip()[:40],
            "raasi": request.form.get("raasi", "").strip()[:40],
            "diet": request.form.get("diet", ""),
            "height_cm": request.form.get("height_cm", "")
        }
        errors = []
        if len(form["full_name"]) < 2:
            errors.append("Enter a full name with at least 2 characters.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", form["email"]):
            errors.append("Enter a valid email address.")
        if not re.fullmatch(r"\+?[0-9]{10,15}", form["mobile"]):
            errors.append("Enter a valid mobile number (10–15 digits).")
        if form["gender"] not in ("Bride", "Groom"):
            errors.append("Choose Bride or Groom.")
        try:
            age = calculate_age(form["date_of_birth"])
            if age < 18 or age > 100:
                errors.append("Member age must be between 18 and 100.")
        except (ValueError, TypeError):
            errors.append("Enter a valid date of birth.")
        if form["is_approved"] not in ("PENDING", "APPROVED", "REJECTED"):
            errors.append("Choose a valid account approval status.")
        if form["is_approved"] == "REJECTED" and not form["rejection_reason"]:
            errors.append("Provide a reason for a rejected account.")
        if form["plan"] not in ("FREE", *PLANS.keys()):
            errors.append("Choose a valid membership plan.")
        if form["plan"] != "FREE":
            try:
                date.fromisoformat(form["plan_until"])
            except ValueError:
                errors.append("Enter a valid Premium expiry date.")
        if form["diet"] not in ("", "Vegetarian", "Non-Vegetarian", "Eggetarian", "Vegan"):
            errors.append("Choose a valid diet.")
        if form["height_cm"] and (
            not form["height_cm"].isdigit()
            or not 120 <= int(form["height_cm"]) <= 230
        ):
            errors.append("Height must be between 120 and 230 cm.")
        if form["profile_created_by"] not in ("Self", "Parent", "Sibling", "Relative", "Friend"):
            errors.append("Choose a valid profile creator.")
        if form["marital_status"] not in ("Never Married", "Divorced", "Widowed", "Awaiting Divorce"):
            errors.append("Choose a valid marital status.")

        duplicate = db.execute(
            "SELECT email, mobile FROM users WHERE id!=? AND (email=? COLLATE NOCASE OR mobile=?)",
            (user_id, form["email"], form["mobile"])
        ).fetchone()
        if duplicate:
            if duplicate["email"].lower() == form["email"]:
                errors.append("That email address is already in use.")
            if duplicate["mobile"] == form["mobile"]:
                errors.append("That mobile number is already in use.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("admin_user_edit.html", member={**dict(member), **form})

        db.execute("""
            UPDATE users SET full_name=?, email=?, mobile=?, gender=?, date_of_birth=?,
                is_approved=?, rejection_reason=?, plan=?, plan_until=?
            WHERE id=?
        """, (
            form["full_name"], form["email"], form["mobile"], form["gender"],
            form["date_of_birth"], form["is_approved"], form["rejection_reason"],
            form["plan"], form["plan_until"] if form["plan"] != "FREE" else None,
            user_id
        ))
        db.execute("""
            UPDATE profiles SET profile_created_by=?, religion=?, mother_tongue=?,
                marital_status=?, education=?, occupation=?, country=?, state=?, city=?,
                about_me=?, caste=?, star=?, raasi=?, height_cm=?, diet=?
            WHERE user_id=?
        """, (
            form["profile_created_by"], form["religion"], form["mother_tongue"],
            form["marital_status"], form["education"], form["occupation"],
            form["country"], form["state"], form["city"], form["about_me"],
            form["caste"], form["star"], form["raasi"],
            int(form["height_cm"]) if form["height_cm"] else None,
            form["diet"], user_id
        ))
        db.commit()
        flash("Member details updated.", "success")
        return redirect(url_for("admin_users"))

    return render_template("admin_user_edit.html", member=member)


@app.route("/admin/users/<int:user_id>/action", methods=["POST"])
@login_required
@admin_required
def admin_user_action(user_id):
    action = request.form.get("action", "")
    if action not in ("deactivate", "restore"):
        flash("Invalid member action.", "danger")
        return redirect(url_for("admin_users"))
    active = 0 if action == "deactivate" else 1
    db = get_db()
    changed = db.execute(
        "UPDATE users SET account_active=? WHERE id=? AND is_admin=0",
        (active, user_id)
    ).rowcount
    if not changed:
        flash("Member account not found.", "warning")
    else:
        db.commit()
        flash(
            "Member account deactivated. The account can be restored from the inactive list."
            if action == "deactivate" else "Member account restored.",
            "success"
        )
    return redirect(url_for("admin_users", scope="inactive" if action == "deactivate" else None))


@app.route("/admin/profile/<int:user_id>")
@login_required
@admin_required
def admin_view_profile(user_id):
    db = get_db()
    p = db.execute("""
        SELECT u.id, u.matrimony_id, u.full_name, u.email, u.mobile, u.gender, u.date_of_birth,
               u.is_approved, u.rejection_reason, u.plan, u.plan_until, u.created_at,
               p.profile_created_by, p.religion, p.mother_tongue, p.marital_status, p.education,
               p.occupation, p.country, p.state, p.city, p.about_me, p.photo_path, p.caste, p.star, p.raasi, p.height_cm, p.diet
        FROM users u LEFT JOIN profiles p ON p.user_id = u.id
        WHERE u.id = ? AND u.is_admin = 0
    """, (user_id,)).fetchone()
    if not p:
        flash("Profile not found.", "danger")
        return redirect(url_for("admin_dashboard"))
    return render_template(
        "admin_profile_view.html",
        p=p,
        age=calculate_age(p["date_of_birth"]),
        contact_checks=contact_validation_status(db, p)
    )


@app.route("/admin/profile/<int:user_id>/action", methods=["POST"])
@login_required
@admin_required
def admin_profile_action(user_id):
    db = get_db()
    action = request.form.get("action")
    target_user = db.execute("SELECT id, is_admin FROM users WHERE id=?", (user_id,)).fetchone()
    if not target_user or target_user["is_admin"]:
        flash("Invalid target user.", "danger")
        return redirect(url_for("admin_dashboard"))

    if action == "approve":
        member = db.execute(
            "SELECT id, email, mobile FROM users WHERE id=?", (user_id,)
        ).fetchone()
        checks = contact_validation_status(db, member)
        if not checks["email_format_valid"] or checks["email_in_use"]:
            flash("Cannot approve: the email address is invalid or already used by another account.", "danger")
            return redirect(url_for("admin_view_profile", user_id=user_id))
        if not checks["mobile_format_valid"] or checks["mobile_in_use"]:
            flash("Cannot approve: the mobile number is invalid or already used by another account.", "danger")
            return redirect(url_for("admin_view_profile", user_id=user_id))
        db.execute("UPDATE users SET is_approved='APPROVED', rejection_reason='' WHERE id=?", (user_id,))
        db.commit()
        flash("Profile approved successfully.", "success")
    elif action == "reject":
        reason = request.form.get("reason", "").strip()[:300]
        if not reason:
            flash("Please provide a reason for rejection.", "warning")
            return redirect(url_for("admin_dashboard"))
        db.execute("UPDATE users SET is_approved='REJECTED', rejection_reason=? WHERE id=?", (reason, user_id))
        db.commit()
        flash("Profile rejected with feedback saved.", "info")
    elif action == "subscription":
        plan = request.form.get("plan", "FREE")
        months = int(request.form.get("months", 1))
        if plan == "FREE":
            db.execute("UPDATE users SET plan='FREE', plan_until=NULL WHERE id=?", (user_id,))
        else:
            until = (date.today() + timedelta(days=30 * months)).isoformat()
            db.execute("UPDATE users SET plan=?, plan_until=? WHERE id=?", (plan, until, user_id))
        db.commit()
        flash("Member subscription updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    if user["is_admin"]:
        return redirect(url_for("admin_dashboard"))
    g = "Bride" if user["gender"] == "Groom" else "Groom"
    recs = get_db().execute(CARD_SQL + " FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id!=:me AND u.gender=:g AND u.is_approved='APPROVED' AND u.is_admin=0 AND u.account_active=1 AND "
                            + BLOCK_SQL.replace("?", ":me") + " ORDER BY u.created_at DESC LIMIT 12", {"me": user["id"], "g": g}).fetchall()
    db, me = get_db(), user["id"]
    one = lambda q: db.execute(q, (me,)).fetchone()[0]
    stats = {"pending": one("SELECT COUNT(*) FROM interests WHERE receiver_id=? AND interest_type='INTEREST' AND status='PENDING'"),
             "views": one("SELECT COUNT(*) FROM views WHERE viewed_id=?"),
             "shortlisted": one("SELECT COUNT(*) FROM interests WHERE receiver_id=? AND interest_type='SHORTLIST'")}
    return render_template("dashboard.html", stats=stats, user=user, age=calculate_age(user["date_of_birth"]),
                           percent=completeness(user), recs=recs)


def build_biodata_pdf(u):
    """Render the member's own biodata as a one-page A4 PDF (reportlab)."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image as RLImage
    from xml.sax.saxutils import escape

    ORANGE = colors.HexColor("#f26b0b")
    INK, MUTED, LINE = colors.HexColor("#1d1d1f"), colors.HexColor("#6b7280"), colors.HexColor("#e5e7eb")
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=INK)
    idst = ParagraphStyle("id", fontName="Helvetica-Bold", fontSize=9, textColor=ORANGE, spaceBefore=2)
    sec = ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=10.5, textColor=ORANGE, spaceBefore=12, spaceAfter=4)
    lab = ParagraphStyle("lab", fontName="Helvetica", fontSize=8.5, textColor=MUTED, leading=11)
    val = ParagraphStyle("val", fontName="Helvetica-Bold", fontSize=9.5, textColor=INK, leading=12)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, textColor=INK, leading=14)

    def esc(v):
        return escape(str(v)) if v not in (None, "") else "-"

    h = u["height_cm"]
    height = f"{int(h / 30.48)}'{int(round(h / 2.54)) % 12}\" ({h} cm)" if h else None
    age = calculate_age(u["date_of_birth"]) if u["date_of_birth"] else None
    dob = u["date_of_birth"]
    try:
        dob = date.fromisoformat(dob).strftime("%d %b %Y")
    except Exception:
        pass
    place = ", ".join(x for x in [u["city"], u["state"], u["country"]] if x)

    def block(title, rows):
        data = [[Paragraph(esc(l), lab), Paragraph(esc(v), val)] for l, v in rows]
        t = Table(data, colWidths=[42 * mm, 134 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE)]))
        return [Paragraph(title.upper(), sec), t]

    # header: name/ID on the left, photo on the right
    left = [Paragraph(esc(u["full_name"]), h1), Paragraph(f"MATRIMONY ID: {esc(u['matrimony_id'])}", idst)]
    photo = None
    if u["photo_path"]:
        fp = os.path.join(BASE_DIR, "static", u["photo_path"])
        if os.path.isfile(fp):
            try:
                from PIL import Image as PILImage
                im = PILImage.open(fp).convert("RGB")
                w, hh = im.size
                target = 4 / 5  # crop to portrait 4:5 so it matches the on-site card
                if w / hh > target:
                    nw = int(hh * target); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, hh))
                else:
                    nh = int(w / target); im = im.crop((0, 0, w, nh))
                buf = io.BytesIO(); im.save(buf, "JPEG", quality=90); buf.seek(0)
                photo = RLImage(buf, width=42 * mm, height=52.5 * mm)
            except Exception:
                photo = None
    head = Table([[left, photo or ""]], colWidths=[134 * mm, 42 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    story = [head]
    story += block("Personal details", [("Gender", u["gender"]), ("Date of birth", dob), ("Age", f"{age} years" if age else None),
                                        ("Height", height), ("Marital status", u["marital_status"]), ("Diet", u["diet"]),
                                        ("Profile created by", u["profile_created_by"])])
    story += block("Religion & horoscope", [("Religion", u["religion"]), ("Caste / community", u["caste"]),
                                            ("Mother tongue", u["mother_tongue"]), ("Star (Nakshatra)", u["star"]), ("Raasi", u["raasi"])])
    story += block("Education & career", [("Education", u["education"]), ("Occupation", u["occupation"])])
    story += block("Location & contact", [("Location", place), ("Mobile", u["mobile"]), ("Email", u["email"])])
    if u["about_me"]:
        story += [Paragraph("ABOUT ME", sec), Paragraph(escape(u["about_me"]).replace("\n", "<br/>"), body)]

    def frame(c, d):
        c.saveState()
        c.setFillColor(ORANGE); c.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 12); c.drawString(17 * mm, A4[1] - 8 * mm, "Irumanam  |  Biodata")
        c.setFillColor(MUTED); c.setFont("Helvetica", 7.5)
        c.drawString(17 * mm, 9 * mm, f"Generated on {date.today().strftime('%d %b %Y')} from Irumanam")
        c.restoreState()

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=20 * mm, bottomMargin=16 * mm,
                            title=f"Biodata - {u['full_name']}", author="Irumanam")
    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    out.seek(0)
    return out


@app.route("/biodata.pdf")
@login_required
def biodata_pdf():
    from flask import send_file
    u = current_user()
    if not u or u["is_admin"]:
        return redirect(url_for("index"))
    try:
        import reportlab  # noqa: F401
    except ImportError:
        flash("PDF feature needs a one-time setup: run  pip install reportlab Pillow  and restart the app.", "warning")
        return redirect(url_for("edit_profile"))
    safe = re.sub(r"[^A-Za-z0-9]+", "_", u["full_name"]).strip("_") or "member"
    return send_file(build_biodata_pdf(u), mimetype="application/pdf", as_attachment=True,
                     download_name=f"Biodata_{safe}_{u['matrimony_id']}.pdf")


@app.route("/edit-profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    db = get_db()
    user = current_user()
    if request.method == "POST":
        fields = {
            "profile_created_by": request.form.get("profile_created_by", "Self"),
            "religion": request.form.get("religion", "").strip()[:80],
            "mother_tongue": request.form.get("mother_tongue", "").strip()[:80],
            "marital_status": request.form.get("marital_status", "Never Married"),
            "education": request.form.get("education", "").strip()[:120],
            "occupation": request.form.get("occupation", "").strip()[:120],
            "country": request.form.get("country", "India").strip()[:80],
            "state": request.form.get("state", "").strip()[:80],
            "city": request.form.get("city", "").strip()[:80],
            "about_me": request.form.get("about_me", "").strip()[:1000],
            "caste": request.form.get("caste", "").strip()[:80],
            "star": request.form.get("star", "").strip()[:40],
            "raasi": request.form.get("raasi", "").strip()[:40],
            "diet": request.form.get("diet", "") if request.form.get("diet", "") in ("Vegetarian", "Non-Vegetarian", "Eggetarian", "Vegan") else "",
            "height_cm": int(request.form["height_cm"]) if request.form.get("height_cm", "").isdigit() and 120 <= int(request.form["height_cm"]) <= 230 else None,
        }
        db.execute("""
            UPDATE profiles SET profile_created_by = :profile_created_by,
                religion = :religion, mother_tongue = :mother_tongue,
                marital_status = :marital_status, education = :education,
                occupation = :occupation, country = :country, state = :state,
                city = :city, about_me = :about_me, caste = :caste, star = :star,
                raasi = :raasi, diet = :diet, height_cm = :height_cm
            WHERE user_id = :user_id
        """, {**fields, "user_id": session["user_id"]})
        
        cropped_data = request.form.get("cropped_photo")
        if cropped_data and "," in cropped_data:
            try:
                header, encoded = cropped_data.split(",", 1)
                file_data = base64.b64decode(encoded)
                filename = f"user_{session['user_id']}_{uuid.uuid4().hex[:8]}.jpg"
                filepath = os.path.join(BASE_DIR, "static", "images", "profiles", filename)
                with open(filepath, "wb") as f:
                    f.write(file_data)
                db.execute("UPDATE profiles SET photo_path=? WHERE user_id=?", (f"images/profiles/{filename}", session["user_id"]))
            except Exception:
                pass
        else:
            photo = request.files.get("photo")
            if photo and photo.filename:
                path = save_photo(photo)
                if path:
                    db.execute("UPDATE profiles SET photo_path=? WHERE user_id=?", (path, session["user_id"]))
        add_admin_notification(
            db, "profile_updated", "Member profile updated",
            f"{user['full_name']} updated their profile details.",
            url_for("admin_view_profile", user_id=session["user_id"])
        )
        db.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("dashboard"))
    album_photos = db.execute(
        "SELECT id, created_at FROM profile_album_photos WHERE user_id=? ORDER BY id DESC",
        (session["user_id"],),
    ).fetchall()
    return render_template(
        "edit_profile.html", user=user, dropdowns=profile_select_options(db),
        album_photos=album_photos,
    )


@app.route("/search")
@login_required
def search():
    db = get_db()
    a = request.args
    query = a.get("q", "").strip()[:80]
    matrimony_id = a.get("matrimony_id", "").strip().upper()[:30]
    gender = a.get("gender", "")
    f = {k: a.get(k, "").strip()[:80] for k in ("religion", "caste", "city", "marital_status", "mother_tongue", "star", "raasi")}
    f["age_min"] = a.get("age_min", "").strip()
    f["age_max"] = a.get("age_max", "").strip()
    f["photo_only"] = a.get("photo_only", "")
    conditions = ["u.id != ?", "u.is_approved = 'APPROVED'", "u.is_admin = 0", "u.account_active = 1", BLOCK_SQL]
    params = [session["user_id"]] * 3

    if matrimony_id:
        conditions.append("UPPER(u.matrimony_id) = ?")
        params.append(matrimony_id)
    else:
        if gender in ("Bride", "Groom"):
            conditions.append("u.gender = ?"); params.append(gender)
        if query:
            like = f"%{query}%"
            conditions.append("(u.full_name LIKE ? OR p.city LIKE ? OR p.education LIKE ? OR p.occupation LIKE ?)")
            params += [like] * 4
        for col in ("religion", "caste", "city", "mother_tongue"):
            if f[col]:
                conditions.append(f"p.{col} LIKE ?"); params.append(f"%{f[col]}%")
        for col in ("star", "raasi"):
            if f[col]:
                conditions.append(f"p.{col} LIKE ?"); params.append(f"%{f[col]}%")
        if f["marital_status"]:
            conditions.append("p.marital_status = ?"); params.append(f["marital_status"])
        if f["age_min"].isdigit():
            conditions.append("u.date_of_birth <= ?"); params.append(dob_for_age(int(f["age_min"])))
        if f["age_max"].isdigit():
            conditions.append("u.date_of_birth > ?"); params.append(dob_for_age(int(f["age_max"]) + 1))
        if f["photo_only"]:
            conditions.append("p.photo_path != ''")

    rows = db.execute(f"""
        SELECT u.id, u.full_name, u.gender, u.date_of_birth, u.created_at,
               p.education, p.occupation, p.city, p.state, p.photo_path,
               p.caste, p.height_cm, p.premium_details_visible,
               EXISTS(SELECT 1 FROM interests i WHERE i.sender_id = ? AND i.receiver_id = u.id AND i.interest_type='SHORTLIST') AS shortlisted,
               EXISTS(SELECT 1 FROM interests i WHERE i.sender_id = ? AND i.receiver_id = u.id AND i.interest_type='INTEREST') AS interested
        FROM users u LEFT JOIN profiles p ON p.user_id = u.id
        WHERE {' AND '.join(conditions)}
        ORDER BY u.created_at DESC LIMIT 100
    """, [session["user_id"], session["user_id"]] + params).fetchall()
    return render_template("search.html", profiles=rows, query=query, gender=gender, f=f,
                           matrimony_id=matrimony_id, calculate_age=calculate_age,
                           dropdowns=profile_select_options(db))


@app.route("/profile/<int:profile_id>")
@login_required
def view_profile(profile_id):
    db = get_db()
    p = db.execute("""
        SELECT u.id, u.full_name, u.gender, u.date_of_birth,
               p.education, p.occupation, p.country, p.state, p.city, p.photo_path,
               p.caste, p.height_cm, p.diet,
               EXISTS(SELECT 1 FROM interests i WHERE i.sender_id=? AND i.receiver_id=u.id AND i.interest_type='SHORTLIST') AS shortlisted,
               EXISTS(SELECT 1 FROM interests i WHERE i.sender_id=? AND i.receiver_id=u.id AND i.interest_type='INTEREST') AS interested
        FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=? AND u.is_approved='APPROVED' AND u.is_admin=0 AND u.account_active=1
    """, (session["user_id"], session["user_id"], profile_id)).fetchone()
    if not p:
        flash("Profile not found.", "warning")
        return redirect(url_for("index"))
    if profile_id != session["user_id"] and is_blocked(db, session["user_id"], profile_id):
        flash("This profile is unavailable.", "warning")
        return redirect(url_for("index"))
    if profile_id != session["user_id"]:
        db.execute("""
            INSERT INTO views (viewer_id, viewed_id, viewed_at) VALUES (?, ?, ?)
            ON CONFLICT(viewer_id, viewed_id) DO UPDATE SET viewed_at=excluded.viewed_at
        """, (session["user_id"], profile_id, datetime.now().isoformat(sep=" ", timespec="microseconds")))
        db.commit()
    sent = db.execute("SELECT status FROM interests WHERE sender_id=? AND receiver_id=? AND interest_type='INTEREST'",
                      (session["user_id"], profile_id)).fetchone()
    is_owner = profile_id == session["user_id"]
    can_view_album = is_owner or is_premium(current_user())
    album_photos = (
        db.execute(
            "SELECT id FROM profile_album_photos WHERE user_id=? ORDER BY id",
            (profile_id,),
        ).fetchall()
        if can_view_album else []
    )
    profile_completion = completeness(current_user()) if is_owner else None
    return render_template("profile.html", percent=profile_completion, p=p, age=calculate_age(p["date_of_birth"]),
                           can_view_album=can_view_album, album_photos=album_photos,
                           sent_status=sent["status"] if sent else None,
                           can_chat=chat_allowed(db, session["user_id"], profile_id))


@app.route("/profile/<int:profile_id>/album/<int:photo_id>")
@login_required
def profile_album_photo(profile_id, photo_id):
    viewer_id = session["user_id"]
    if profile_id != viewer_id and (
        not is_premium(current_user()) or is_blocked(get_db(), viewer_id, profile_id)
    ):
        abort(404)
    row = get_db().execute("""
        SELECT a.filename
        FROM profile_album_photos a
        JOIN users u ON u.id=a.user_id
        WHERE a.id=? AND a.user_id=? AND u.is_approved='APPROVED'
          AND u.is_admin=0 AND u.account_active=1
    """, (photo_id, profile_id)).fetchone()
    if not row:
        abort(404)
    response = send_from_directory(
        os.path.join(BASE_DIR, "private_media", "profile_albums"),
        row["filename"],
        mimetype="image/jpeg",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.route("/profile/album/upload", methods=["POST"])
@login_required
def profile_album_upload():
    user = current_user()
    if not user or user["is_admin"]:
        abort(403)
    uploads = [photo for photo in request.files.getlist("album_photos") if photo and photo.filename]
    if not uploads:
        flash("Choose at least one photo to upload.", "warning")
        return redirect(url_for("edit_profile") + "#album")
    if len(uploads) > 5:
        flash("Upload no more than 5 photos at a time.", "warning")
        return redirect(url_for("edit_profile") + "#album")

    saved_filenames = []
    try:
        for upload in uploads:
            saved_filenames.append(save_album_photo(upload, session["user_id"]))
    except ValueError as error:
        for filename in saved_filenames:
            os.remove(os.path.join(BASE_DIR, "private_media", "profile_albums", filename))
        flash(str(error), "danger")
        return redirect(url_for("edit_profile") + "#album")

    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        photo_count = db.execute(
            "SELECT COUNT(*) FROM profile_album_photos WHERE user_id=?",
            (session["user_id"],),
        ).fetchone()[0]
        if photo_count + len(saved_filenames) > 12:
            db.rollback()
            for filename in saved_filenames:
                os.remove(os.path.join(BASE_DIR, "private_media", "profile_albums", filename))
            flash("Your album can contain up to 12 photos. Remove a photo before uploading more.", "warning")
            return redirect(url_for("edit_profile") + "#album")
        db.executemany(
            "INSERT INTO profile_album_photos (user_id, filename) VALUES (?, ?)",
            [(session["user_id"], filename) for filename in saved_filenames],
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        for filename in saved_filenames:
            os.remove(os.path.join(BASE_DIR, "private_media", "profile_albums", filename))
        raise
    flash(f"{len(saved_filenames)} photo(s) added to your album.", "success")
    return redirect(url_for("edit_profile") + "#album")


@app.route("/profile/album/<int:photo_id>/delete", methods=["POST"])
@login_required
def profile_album_delete(photo_id):
    db = get_db()
    photo = db.execute(
        "SELECT filename FROM profile_album_photos WHERE id=? AND user_id=?",
        (photo_id, session["user_id"]),
    ).fetchone()
    if not photo:
        abort(404)
    db.execute("BEGIN IMMEDIATE")
    try:
        os.remove(os.path.join(BASE_DIR, "private_media", "profile_albums", photo["filename"]))
    except FileNotFoundError:
        pass
    except PermissionError:
        db.rollback()
        flash("That photo is still being accessed. Please try removing it again shortly.", "warning")
        return redirect(url_for("edit_profile") + "#album")
    db.execute(
        "DELETE FROM profile_album_photos WHERE id=? AND user_id=?",
        (photo_id, session["user_id"]),
    )
    db.commit()
    flash("Photo removed from your album.", "success")
    return redirect(url_for("edit_profile") + "#album")


@app.route("/interest/<int:sender_id>/respond", methods=["POST"])
@login_required
def respond_interest(sender_id):
    action = request.form.get("action")
    if action not in ("accept", "decline"):
        return redirect(url_for("interests"))
    db = get_db()
    if is_blocked(db, session["user_id"], sender_id):
        flash("This interaction is unavailable.", "warning")
        return redirect(url_for("interests"))
    changed = db.execute("UPDATE interests SET status=?, updated_at=? WHERE sender_id=? AND receiver_id=? AND interest_type='INTEREST'",
                         ("ACCEPTED" if action == "accept" else "DECLINED",
                          datetime.now().isoformat(sep=" ", timespec="microseconds"), sender_id, session["user_id"])).rowcount
    if changed and action == "accept":
        member = db.execute("SELECT full_name FROM users WHERE id=?", (session["user_id"],)).fetchone()
        add_admin_notification(
            db, "interest_accepted", "Member interest accepted",
            f"{member['full_name']} accepted a match interest.",
            url_for("admin_view_profile", user_id=session["user_id"])
        )
    db.commit()
    flash("Interest accepted." if action == "accept" else "Interest declined.", "success" if action == "accept" else "info")
    return redirect(url_for("interests"))


@app.route("/interest/<int:profile_id>", methods=["POST"])
@login_required
def send_interest(profile_id):
    if profile_id == session["user_id"]:
        return redirect_back("index")
    db = get_db()
    target = db.execute(
        "SELECT id FROM users WHERE id=? AND is_approved='APPROVED' AND is_admin=0 AND account_active=1",
        (profile_id,)
    ).fetchone()
    if not target or is_blocked(db, session["user_id"], profile_id):
        flash("This profile is unavailable.", "warning")
        return redirect_back("index")
    created_at = datetime.now().isoformat(sep=" ", timespec="microseconds")
    cursor = db.execute("""
        INSERT OR IGNORE INTO interests (sender_id, receiver_id, interest_type, created_at, updated_at)
        VALUES (?, ?, 'INTEREST', ?, ?)
    """, (session["user_id"], profile_id, created_at, created_at))
    if cursor.rowcount:
        member = db.execute("SELECT full_name FROM users WHERE id=?", (session["user_id"],)).fetchone()
        add_admin_notification(
            db, "interest_sent", "New match interest",
            f"{member['full_name']} sent a match interest.",
            url_for("admin_view_profile", user_id=session["user_id"])
        )
    db.commit()
    flash("Interest sent!", "success")
    return redirect_back("index")


@app.route("/shortlist/<int:profile_id>", methods=["POST"])
@login_required
def toggle_shortlist(profile_id):
    if profile_id == session["user_id"]:
        return redirect_back("index")
    db = get_db()
    target = db.execute(
        "SELECT id FROM users WHERE id=? AND is_approved='APPROVED' AND is_admin=0 AND account_active=1",
        (profile_id,)
    ).fetchone()
    if not target or is_blocked(db, session["user_id"], profile_id):
        flash("This profile is unavailable.", "warning")
        return redirect_back("index")
    row = db.execute("SELECT id FROM interests WHERE sender_id=? AND receiver_id=? AND interest_type='SHORTLIST'", (session["user_id"], profile_id)).fetchone()
    if row:
        db.execute("DELETE FROM interests WHERE id=?", (row["id"],))
        flash("Profile removed from shortlist.", "info")
    else:
        db.execute("INSERT OR IGNORE INTO interests (sender_id, receiver_id, interest_type) VALUES (?, ?, 'SHORTLIST')", (session["user_id"], profile_id))
        flash("Profile added to shortlist.", "success")
    db.commit()
    return redirect_back("index")


@app.route("/shortlist")
@login_required
def shortlist():
    rows = get_db().execute(CARD_SQL + " FROM interests i JOIN users u ON u.id=i.receiver_id LEFT JOIN profiles p ON p.user_id=u.id "
                            "                            WHERE i.sender_id=:me AND i.interest_type='SHORTLIST' AND u.is_approved='APPROVED' AND u.is_admin=0 AND u.account_active=1 AND "
                            + BLOCK_SQL.replace("?", ":me") + " ORDER BY i.created_at DESC", {"me": session["user_id"]}).fetchall()
    return render_template("search.html", profiles=rows, calculate_age=calculate_age, f={}, page_heading="My Shortlist")


@app.route("/interests")
@login_required
def interests():
    db, me = get_db(), session["user_id"]
    box = "sent" if request.args.get("box") == "sent" else "received"
    status = request.args.get("status", "all").upper()
    if status not in ("PENDING", "ACCEPTED", "DECLINED"):
        status = "ALL"
    me_col, other_col = ("sender_id", "receiver_id") if box == "sent" else ("receiver_id", "sender_id")
    sql = (CARD_SQL + f", i.status AS interest_status, i.created_at AS sent_at FROM interests i JOIN users u ON u.id=i.{other_col} "
           f"LEFT JOIN profiles p ON p.user_id=u.id WHERE i.{'receiver_id' if box == 'received' else 'sender_id'}=:me AND i.interest_type='INTEREST' AND u.is_approved='APPROVED' AND u.is_admin=0 AND u.account_active=1 AND "
           + BLOCK_SQL.replace("?", ":me"))
    par = {"me": me}
    if status != "ALL":
        sql += " AND i.status=:st"; par["st"] = status
    rows = db.execute(sql + " ORDER BY i.created_at DESC", par).fetchall()
    ic = {}
    for b, st, n in db.execute("""SELECT 'received', status, COUNT(*) FROM interests WHERE receiver_id=? AND interest_type='INTEREST' GROUP BY status
                                  UNION ALL SELECT 'sent', status, COUNT(*) FROM interests WHERE sender_id=? AND interest_type='INTEREST' GROUP BY status""", (me, me)):
        ic[f"{b}_{st}"] = n; ic[f"{b}_ALL"] = ic.get(f"{b}_ALL", 0) + n
    title = f"{status.title() if status != 'ALL' else 'All'} interests {'sent' if box == 'sent' else 'received'} ({len(rows)})"
    return render_template("search.html", profiles=rows, calculate_age=calculate_age, f={}, page_heading="Interests",
                           ititle=title, box=box, status=status, ic=ic, mode="sent" if box == "sent" else "recv")


PLATINUM_PRICE = int(os.environ.get("IRUMANAM_PLATINUM_PRICE", "0") or 0)
PLANS = {
    "SILVER": ("Silver", 3, 333),
    "GOLD": ("Gold", 6, 666),
    "PLATINUM": ("Platinum", 9, 999),
    "DIAMOND": ("Diamond", 12, 1332),
}
UPI_NUMBER = "7867877418"
ALLOWED_PAYMENT_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def _payment_qr(amount, note):
    # UPI ID is intentionally not guessed from the mobile number. This QR opens a
    # UPI payment intent addressed to the supplied number; verify the receiver in-app.
    from urllib.parse import quote
    upi_uri = f"upi://pay?pa={quote(UPI_NUMBER)}&pn={quote('Irumanam Matrimony')}&am={amount}&cu=INR&tn={quote(note)}"
    qr = qrcode.QRCode(box_size=8, border=3)
    qr.add_data(upi_uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#172554", back_color="white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


@app.route("/premium")
@login_required
def premium_page():
    db = get_db()
    payments = db.execute("SELECT * FROM premium_payments WHERE user_id=? ORDER BY id DESC LIMIT 10", (session["user_id"],)).fetchall()
    return render_template("premium.html", plans=PLANS, payments=payments)


@app.route("/premium/activate", methods=["POST"])
@login_required
def premium_activate():
    plan = request.form.get("plan", "").upper()
    if plan not in PLANS:
        flash("Please select a valid Premium plan.", "danger")
        return redirect(url_for("premium_page"))
    name, months, amount = PLANS[plan]
    if amount <= 0:
        flash("The Platinum price has not been configured yet. Please contact the administrator.", "warning")
        return redirect(url_for("premium_page"))
    user = get_db().execute("SELECT id, matrimony_id FROM users WHERE id=? AND is_admin=0", (session["user_id"],)).fetchone()
    if not user:
        flash("A member account is required to request Premium.", "danger")
        return redirect(url_for("admin_dashboard" if current_user() and current_user()["is_admin"] else "premium_page"))
    return render_template("premium_payment.html", plan=plan, plan_name=name, months=months,
                           amount=amount, note=f"{user['matrimony_id']}-{name}-{date.today().isoformat()}",
                           qr_data=_payment_qr(amount, f"{user['matrimony_id']}-{name}-{date.today().isoformat()}"), upi_number=UPI_NUMBER)


@app.route("/premium/payment/submit", methods=["POST"])
@login_required
def premium_payment_submit():
    plan = request.form.get("plan", "").upper()
    txn = re.sub(r"\s+", "", request.form.get("transaction_id", "")).strip()
    upload = request.files.get("payment_screenshot")
    if plan not in PLANS or PLANS[plan][2] <= 0:
        flash("Invalid plan or plan price is not configured.", "danger")
        return redirect(url_for("premium_page"))
    if not txn or len(txn) > 120 or not re.fullmatch(r"[A-Za-z0-9_-]+", txn):
        flash("Enter a valid transaction ID (letters, numbers, hyphen or underscore).", "warning")
        return redirect(url_for("premium_page"))
    if not upload or not upload.filename or "." not in upload.filename:
        flash("Please upload your payment screenshot.", "warning")
        return redirect(url_for("premium_page"))
    ext = upload.filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_PAYMENT_EXTENSIONS:
        flash("Screenshot must be PNG, JPG, JPEG or WEBP.", "danger")
        return redirect(url_for("premium_page"))
    # Verify image content, not just the filename extension.
    try:
        from PIL import Image
        image = Image.open(upload.stream)
        image.verify()
        upload.stream.seek(0)
    except Exception:
        flash("The uploaded file is not a valid image.", "danger")
        return redirect(url_for("premium_page"))
    db = get_db()
    if db.execute("SELECT id FROM premium_payments WHERE transaction_id=?", (txn,)).fetchone():
        flash("This transaction ID has already been submitted.", "danger")
        return redirect(url_for("premium_page"))
    user = db.execute("SELECT matrimony_id FROM users WHERE id=?", (session["user_id"],)).fetchone()
    name, months, amount = PLANS[plan]
    note = f"{user['matrimony_id']}-{name}-{date.today().isoformat()}"
    folder = os.path.join(BASE_DIR, "private_media", "payments")
    os.makedirs(folder, exist_ok=True)
    filename = f"payment_{session['user_id']}_{uuid.uuid4().hex}.{ext}"
    upload.save(os.path.join(folder, filename))
    cursor = db.execute("INSERT INTO premium_payments (user_id,plan,amount,transaction_id,screenshot_path,notes) VALUES (?,?,?,?,?,?)",
                        (session["user_id"], plan, amount, txn, filename, note))
    db.execute("INSERT INTO user_notifications (user_id,message) VALUES (?,?)",
               (session["user_id"], f"Your {name} payment request was submitted and is Pending Approval."))
    add_admin_notification(
        db, "payment_submitted", "Premium payment submitted",
        f"A member submitted a {name} plan payment for review.",
        url_for("admin_premium_payments", status="PENDING") + "#payment-{}".format(cursor.lastrowid)
    )
    db.commit()
    flash("Payment details submitted. Your plan will activate only after admin approval.", "success")
    return redirect(url_for("premium_page"))


@app.route("/admin/premium-payments")
@login_required
@admin_required
def admin_premium_payments():
    status = request.args.get("status", "PENDING").upper()
    if status not in ("PENDING", "APPROVED", "REJECTED", "ALL"):
        status = "PENDING"
    query = request.args.get("q", "").strip()[:120]
    sql = "SELECT pp.*, u.full_name, u.matrimony_id, u.email, u.mobile FROM premium_payments pp JOIN users u ON u.id=pp.user_id"
    conditions = []
    params = []
    if status != "ALL":
        conditions.append("pp.status=?")
        params.append(status)
    if query:
        like = f"%{query}%"
        conditions.append(
            "(u.full_name LIKE ? OR u.matrimony_id LIKE ? OR u.email LIKE ? "
            "OR u.mobile LIKE ? OR pp.transaction_id LIKE ?)"
        )
        params.extend([like] * 5)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    rows = get_db().execute(sql + " ORDER BY pp.created_at DESC", params).fetchall()
    return render_template(
        "admin_premium_payments.html",
        payments=rows,
        status_filter=status,
        query=query,
        today=date.today().isoformat(),
        plan_months={key: details[1] for key, details in PLANS.items()}
    )


@app.route("/admin/premium-payments/<int:payment_id>/screenshot")
@login_required
@admin_required
def admin_payment_screenshot(payment_id):
    from flask import send_from_directory, abort
    row = get_db().execute("SELECT screenshot_path FROM premium_payments WHERE id=?", (payment_id,)).fetchone()
    if not row:
        abort(404)
    return send_from_directory(os.path.join(BASE_DIR, "private_media", "payments"), row["screenshot_path"], as_attachment=False)


@app.route("/admin/premium-payments/<int:payment_id>/review", methods=["POST"])
@login_required
@admin_required
def admin_review_premium_payment(payment_id):
    db = get_db()
    payment = db.execute("SELECT * FROM premium_payments WHERE id=?", (payment_id,)).fetchone()
    if not payment or payment["status"] != "PENDING":
        flash("This payment request is not pending review.", "warning")
        return redirect(url_for("admin_premium_payments"))
    action = request.form.get("action", "").lower()
    user_id = payment["user_id"]
    plan_name = PLANS[payment["plan"]][0]
    if action == "approve":
        try:
            start = date.fromisoformat(request.form.get("start_date", ""))
            expiry = date.fromisoformat(request.form.get("expiry_date", ""))
        except ValueError:
            flash("Choose valid subscription start and expiry dates.", "danger")
            return redirect(url_for("admin_premium_payments"))
        if expiry <= start:
            flash("Expiry date must be after the start date.", "danger")
            return redirect(url_for("admin_premium_payments"))
        db.execute("UPDATE premium_payments SET status='APPROVED',start_date=?,expiry_date=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (start.isoformat(), expiry.isoformat(), payment_id))
        db.execute("UPDATE users SET plan=?,plan_until=? WHERE id=?", (payment["plan"], expiry.isoformat(), user_id))
        db.execute("INSERT INTO user_notifications (user_id,message) VALUES (?,?)", (user_id, f"Your {plan_name} Premium plan has been approved and is valid from {start.isoformat()} to {expiry.isoformat()}."))
        member = db.execute("SELECT full_name FROM users WHERE id=?", (user_id,)).fetchone()
        add_admin_notification(
            db, "payment_approved", "Payment approved",
            f"{member['full_name']}’s {plan_name} subscription is active.",
            url_for("admin_premium_payments", status="APPROVED") + "#payment-{}".format(payment_id)
        )
        db.commit()
        flash(f"{plan_name} payment approved and subscription activated.", "success")
    elif action == "reject":
        reason = request.form.get("reason", "").strip()[:300]
        if not reason:
            flash("Please provide a rejection reason.", "warning")
            return redirect(url_for("admin_premium_payments"))
        db.execute("UPDATE premium_payments SET status='REJECTED',admin_note=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (reason, payment_id))
        db.execute("INSERT INTO user_notifications (user_id,message) VALUES (?,?)", (user_id, f"Your {plan_name} payment request was rejected. Reason: {reason}"))
        db.commit()
        flash("Payment request rejected and user notified.", "info")
    else:
        flash("Invalid review action.", "danger")
    return redirect(url_for("admin_premium_payments"))


@app.route("/my-notifications")
@login_required
def my_notifications():
    rows = get_db().execute("SELECT * FROM user_notifications WHERE user_id=? ORDER BY id DESC LIMIT 50", (session["user_id"],)).fetchall()
    return render_template("my_notifications.html", items=rows)


def _threads(db, me):
    return db.execute("""
        SELECT o.id, o.full_name, pr.photo_path,
          (SELECT body FROM messages WHERE (sender_id=o.id AND receiver_id=:me) OR (sender_id=:me AND receiver_id=o.id) ORDER BY id DESC LIMIT 1) AS last_body,
          (SELECT COUNT(*) FROM messages WHERE sender_id=o.id AND receiver_id=:me AND is_read=0) AS unread
        FROM users o LEFT JOIN profiles pr ON pr.user_id=o.id
        WHERE o.id IN (SELECT receiver_id FROM messages WHERE sender_id=:me UNION SELECT sender_id FROM messages WHERE receiver_id=:me)
          AND o.is_approved='APPROVED' AND o.is_admin=0 AND o.account_active=1
          AND NOT EXISTS (
              SELECT 1 FROM blocks b
              WHERE (b.blocker_id=:me AND b.blocked_id=o.id)
                 OR (b.blocker_id=o.id AND b.blocked_id=:me)
          )
        ORDER BY (SELECT MAX(id) FROM messages WHERE sender_id IN (o.id,:me) AND receiver_id IN (o.id,:me)) DESC""", {"me": me}).fetchall()


@app.route("/messages")
@login_required
def messages_inbox():
    ts = _threads(get_db(), session["user_id"])
    if ts:
        return redirect(url_for("chat", other_id=ts[0]["id"]))
    return render_template("messages.html", threads=ts, active=None, msgs=[])


@app.route("/messages/<int:other_id>", methods=["GET", "POST"])
@login_required
def chat(other_id):
    db, me = get_db(), session["user_id"]
    other = db.execute("SELECT u.id, u.full_name, p.photo_path FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE u.id=? AND u.is_approved='APPROVED' AND u.is_admin=0 AND u.account_active=1", (other_id,)).fetchone()
    if not other or other_id == me:
        return redirect(url_for("messages_inbox"))
    if is_blocked(db, me, other_id):
        flash("This conversation is unavailable.", "warning")
        return redirect(url_for("messages_inbox"))
    if not chat_allowed(db, me, other_id):
        flash("Chat opens once interest is accepted, or with Premium.", "warning")
        return redirect(url_for("premium_page"))
    if request.method == "POST":
        body = request.form.get("body", "").strip()[:1000]
        if body:
            db.execute("INSERT INTO messages (sender_id, receiver_id, body) VALUES (?, ?, ?)", (me, other_id, body))
            db.commit()
        return redirect(url_for("chat", other_id=other_id))
    db.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?", (other_id, me))
    db.commit()
    msgs = db.execute("SELECT * FROM messages WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?) ORDER BY id", (me, other_id, other_id, me)).fetchall()
    return render_template("messages.html", threads=_threads(db, me), active=other, msgs=msgs)


@app.route("/viewers")
@login_required
def viewers():
    db = get_db()
    rows = db.execute(CARD_SQL + """ FROM views v JOIN users u ON u.id=v.viewer_id LEFT JOIN profiles p ON p.user_id=u.id
        WHERE v.viewed_id=:me AND u.is_approved='APPROVED' AND u.is_admin=0 AND u.account_active=1 AND """ + BLOCK_SQL.replace("?", ":me") + " ORDER BY v.viewed_at DESC LIMIT 50", {"me": session["user_id"]}).fetchall()
    if not is_premium(current_user()):
        return render_template("viewers_locked.html", count=len(rows))
    return render_template("search.html", profiles=rows, query="", gender="", f={}, calculate_age=calculate_age, page_heading="Who Viewed My Profile")


@app.route("/preferences", methods=["GET", "POST"])
@login_required
def preferences():
    db, me = get_db(), session["user_id"]
    if request.method == "POST":
        r = request.form
        num = lambda k: int(r[k]) if r.get(k, "").isdigit() else None
        db.execute("""INSERT INTO preferences (user_id, age_min, age_max, religion, caste, city, marital_status, star, raasi) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET age_min=excluded.age_min, age_max=excluded.age_max, religion=excluded.religion,
            caste=excluded.caste, city=excluded.city, marital_status=excluded.marital_status,
            star=excluded.star, raasi=excluded.raasi""",
            (me, num("age_min"), num("age_max"), r.get("religion", "").strip()[:80], r.get("caste", "").strip()[:80],
             r.get("city", "").strip()[:80], r.get("marital_status", "")[:30],
             r.get("star", "").strip()[:40], r.get("raasi", "").strip()[:40]))
        db.execute(
            "UPDATE profiles SET premium_details_visible=? WHERE user_id=?",
            (1 if r.get("premium_details_visible") == "1" else 0, me)
        )
        db.commit()
        flash("Partner preferences saved.", "success")
        return redirect(url_for("matches"))
    pref = db.execute("SELECT * FROM preferences WHERE user_id=?", (me,)).fetchone()
    profile_privacy = db.execute(
        "SELECT premium_details_visible FROM profiles WHERE user_id=?", (me,)
    ).fetchone()
    return render_template(
        "preferences.html",
        pref=pref,
        dropdowns=profile_select_options(db),
        premium_details_visible=bool(profile_privacy and profile_privacy["premium_details_visible"])
    )


@app.route("/matches")
@login_required
def matches():
    db, me = get_db(), session["user_id"]
    user = current_user()
    pref = db.execute("SELECT * FROM preferences WHERE user_id=?", (me,)).fetchone()
    if not pref:
        flash("Set your partner preferences.", "info")
        return redirect(url_for("preferences"))
    cond, par = ["u.id != :me", "u.gender = :g", "u.is_approved = 'APPROVED'", "u.is_admin = 0", "u.account_active = 1", BLOCK_SQL.replace("?", ":me")], {"me": me, "g": "Bride" if user["gender"] == "Groom" else "Groom"}
    if pref["age_min"]: cond.append("u.date_of_birth <= :dmax"); par["dmax"] = dob_for_age(pref["age_min"])
    if pref["age_max"]: cond.append("u.date_of_birth > :dmin"); par["dmin"] = dob_for_age(pref["age_max"] + 1)
    for col in ("religion", "caste", "city"):
        if pref[col]: cond.append(f"p.{col} LIKE :{col}"); par[col] = f"%{pref[col]}%"
    for col in ("star", "raasi"):
        if pref[col]: cond.append(f"p.{col} LIKE :{col}"); par[col] = f"%{pref[col]}%"
    if pref["marital_status"]: cond.append("p.marital_status = :ms"); par["ms"] = pref["marital_status"]
    rows = db.execute(CARD_SQL + " FROM users u LEFT JOIN profiles p ON p.user_id=u.id WHERE " + " AND ".join(cond) + " ORDER BY u.created_at DESC LIMIT 60", par).fetchall()
    return render_template("search.html", profiles=rows, query="", gender="", f={}, calculate_age=calculate_age, page_heading="My Matches")


@app.route("/block/<int:profile_id>", methods=["POST"])
@login_required
def block(profile_id):
    db = get_db()
    target = db.execute(
        "SELECT id FROM users WHERE id=? AND is_approved='APPROVED' AND is_admin=0 AND account_active=1",
        (profile_id,)
    ).fetchone()
    if profile_id == session["user_id"] or not target:
        flash("This member cannot be blocked.", "warning")
        return redirect_back("index")
    db.execute(
        "INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, reason) VALUES (?,?,?)",
        (session["user_id"], profile_id, request.form.get("reason", "").strip()[:200])
    )
    db.commit()
    flash("Member blocked. Their profile and conversation are now unavailable to you.", "info")
    return redirect(url_for("index"))


@app.route("/blocked-members")
@login_required
def blocked_members():
    rows = get_db().execute("""
        SELECT u.id, u.full_name, u.matrimony_id, b.reason
        FROM blocks b JOIN users u ON u.id=b.blocked_id
        WHERE b.blocker_id=?
        ORDER BY b.rowid DESC
    """, (session["user_id"],)).fetchall()
    return render_template("blocked_members.html", members=rows)


@app.route("/block/<int:profile_id>/remove", methods=["POST"])
@login_required
def unblock_member(profile_id):
    db = get_db()
    changed = db.execute(
        "DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?",
        (session["user_id"], profile_id)
    ).rowcount
    db.commit()
    flash(
        "Member unblocked." if changed else "That member was not in your blocked list.",
        "success" if changed else "info"
    )
    return redirect(url_for("blocked_members"))


@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    mark_notifications_read(db, session["user_id"])
    tab = request.args.get("tab", "all")
    if tab not in ("all", "interactions", "urgent"):
        tab = "all"
    rows = db.execute("""
        SELECT 'view' k, x.id, x.full_name, pr.photo_path, v.viewed_at t, '' st FROM views v JOIN users x ON x.id=v.viewer_id LEFT JOIN profiles pr ON pr.user_id=x.id WHERE v.viewed_id=:me AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
        UNION ALL SELECT 'int', x.id, x.full_name, pr.photo_path, i.created_at, i.status FROM interests i JOIN users x ON x.id=i.sender_id LEFT JOIN profiles pr ON pr.user_id=x.id WHERE i.receiver_id=:me AND i.interest_type='INTEREST' AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
        UNION ALL SELECT 'acc', x.id, x.full_name, pr.photo_path, i.updated_at, i.status FROM interests i JOIN users x ON x.id=i.receiver_id LEFT JOIN profiles pr ON pr.user_id=x.id WHERE i.sender_id=:me AND i.interest_type='INTEREST' AND i.status='ACCEPTED' AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me))
        UNION ALL SELECT 'msg', x.id, x.full_name, pr.photo_path, MAX(m.created_at), '' FROM messages m JOIN users x ON x.id=m.sender_id LEFT JOIN profiles pr ON pr.user_id=x.id WHERE m.receiver_id=:me AND m.is_read=0 AND x.is_approved='APPROVED' AND x.is_admin=0 AND x.account_active=1 AND NOT EXISTS (SELECT 1 FROM blocks b WHERE (b.blocker_id=:me AND b.blocked_id=x.id) OR (b.blocker_id=x.id AND b.blocked_id=:me)) GROUP BY x.id
        ORDER BY t DESC LIMIT 60""", {"me": session["user_id"]}).fetchall()
    if tab == "interactions":
        rows = [r for r in rows if r["k"] in ("int", "acc")]
    elif tab == "urgent":
        rows = [r for r in rows if r["k"] == "msg" or (r["k"] == "int" and r["st"] == "PENDING")]
    return render_template("notifications.html", items=rows, tab=tab)


def mark_notifications_read(db, user_id):
    read_at = datetime.now().isoformat(sep=" ", timespec="microseconds")
    db.execute("""
        INSERT INTO notification_reads (user_id, read_at) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET read_at = excluded.read_at
    """, (user_id, read_at))
    db.commit()


@app.route("/notifications/read", methods=["POST"])
@login_required
def mark_notifications_read_route():
    mark_notifications_read(get_db(), session["user_id"])
    return "", 204


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    user = current_user()
    if user and user["is_admin"]:
        db = get_db()
        record_admin_login(db, user, "logout")
        db.execute(
            "INSERT INTO admin_activity_logs (admin_id, admin_name, action, endpoint, details) "
            "VALUES (?, ?, 'Logout', 'logout', ?)",
            (user["id"], user["full_name"], request.path)
        )
        db.commit()
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


if __name__ == "__main__":
    init_db()
    app.run(
        debug=os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"},
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
    )