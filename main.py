from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import uvicorn
import logging
import sqlite3
from typing import List
from datetime import datetime
import os

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CORS KONFIGURATION ====================

# 1️⃣ Umgebungsabhängige Frontend-URLs
ENV = os.getenv("ENV", "production")

# Erlaubte Origins
origins = [
    # 🔧 Lokale Entwicklung
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    
    # 🌐 Deployment Frontends
    "https://spendesoundsystem-production.up.railway.app",
    "https://muntaziran-e-zahoor.github.io",
    "https://fanciful-piroshki-0985d4.netlify.app",
    "https://web-production-6008.up.railway.app",
    
    # 🌐 GitHub Pages mit verschiedenen Pfaden - WICHTIG!
    "https://muntaziran-e-zahoor.github.io/SpendeSoundAnlage",
    "https://muntaziran-e-zahoor.github.io/SpendeSoundAnlage/",
    "https://muntaziran-e-zahoor.github.io/spendeSoundAnlage-Frontend",
    "https://muntaziran-e-zahoor.github.io/spendeSoundAnlage-Frontend/"
]

# Development Mode: Alle Origins erlauben (NUR FÜR TESTS!)
if ENV == "dev":
    logger.warning("⚠️ DEV MODE: Alle CORS-Origins erlaubt!")
    origins = ["*"]

logger.info(f"✅ CORS aktiviert für: {origins}")

# FastAPI Setup
app = FastAPI(title="Spenden-API", version="1.0.0")

# 2️⃣ CORS-Middleware (MUSS vor anderen Middleware kommen!)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

# Telegram
BOT_TOKEN = "8375806921:AAGjpcEOjYmqE8DpNQXL9iD5Y68Kub_0Pgo"
CHAT_ID = "7768533941"

# Datenbank
DB_FILE = "donations.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            nachname TEXT,
            telefon TEXT,
            kontaktArt TEXT,
            betrag REAL,
            aktionName TEXT,
            status TEXT DEFAULT 'pending',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("✅ Datenbank initialisiert")

init_db()

# Pydantic Models
class Donation(BaseModel):
    name: str
    nachname: str = ""
    telefon: str = ""
    kontaktArt: str
    betrag: float
    aktionName: str

# ==================== ENDPOINTS ====================

@app.get("/")
def read_root():
    return {
        "status": "API läuft",
        "environment": ENV,
        "bot_configured": bool(BOT_TOKEN and CHAT_ID),
        "message": "Spenden-Backend für Muntazira-E-Zahoor",
        "endpoints": {
            "docs": "/docs",
            "donation_erstellen": "POST /donation",
            "pending_liste": "GET /donations/pending",
            "statistiken": "GET /donations/statistics",
            "bestaetigen": "POST /donation/confirm/{id}",
            "loeschen": "DELETE /donation/{id}"
        }
    }

@app.options("/{full_path:path}")
async def preflight(full_path: str):
    """CORS Preflight Handler"""
    return {"message": "OK"}

@app.get("/test-telegram")
def test_telegram():
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return {"status": "success", "bot_info": response.json()}
        return {"status": "error", "code": response.status_code}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.post("/donation")
def create_donation(donation: Donation):
    """Neue Spende erstellen"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO donations (name, nachname, telefon, kontaktArt, betrag, aktionName, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """, (
            donation.name,
            donation.nachname,
            donation.telefon,
            donation.kontaktArt,
            donation.betrag,
            donation.aktionName
        ))
        
        donation_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"✅ Spende #{donation_id}: {donation.name} - {donation.betrag}€ für {donation.aktionName}")

        # Telegram Benachrichtigung
        full_name = f"{donation.name} {donation.nachname}".strip()
        message = f"""
📢 Neue Spende eingegangen!

👤 Name: {full_name}
💰 Betrag: {donation.betrag} €
📱 Kontaktart: {donation.kontaktArt}
📞 Telefon: {donation.telefon}
🎯 Aktion: {donation.aktionName}

⏳ Wartet auf Bestätigung
        """
        
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
            logger.info(f"📱 Telegram gesendet für #{donation_id}")
        except Exception as e:
            logger.warning(f"⚠️ Telegram Fehler: {e}")

        return {
            "status": "success",
            "message": "Spende erfolgreich eingetragen!",
            "donation_id": donation_id
        }

    except Exception as e:
        logger.error(f"❌ Fehler: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/donations/pending")
def get_pending_donations():
    """Alle ausstehenden Spenden abrufen"""
    try:
        conn = get_db_connection()
        rows = conn.execute("""
            SELECT id, name, nachname, telefon, kontaktArt, betrag, aktionName, timestamp 
            FROM donations 
            WHERE status='pending' 
            ORDER BY timestamp DESC
        """).fetchall()
        conn.close()
        
        result = [{
            "id": r["id"],
            "name": f"{r['name']} {r['nachname']}".strip(),
            "telefon": r["telefon"],
            "kontaktArt": r["kontaktArt"],
            "betrag": float(r["betrag"]),
            "aktionName": r["aktionName"],
            "timestamp": r["timestamp"]
        } for r in rows]
        
        logger.info(f"📋 {len(result)} pending Spenden")
        return result
    except Exception as e:
        logger.error(f"❌ {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/donation/confirm/{donation_id}")
def confirm_donation(donation_id: int):
    """Spende bestätigen"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        donation = conn.execute("SELECT * FROM donations WHERE id=?", (donation_id,)).fetchone()
        if not donation:
            conn.close()
            raise HTTPException(status_code=404, detail="Spende nicht gefunden")
        
        cursor.execute("UPDATE donations SET status='confirmed' WHERE id=?", (donation_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Bestätigt: #{donation_id}")
        
        # Telegram Bestätigung
        try:
            full_name = f"{donation['name']} {donation['nachname']}".strip()
            message = f"✅ Spende bestätigt!\n\n👤 {full_name}\n💰 {donation['betrag']} €\n🎯 {donation['aktionName']}"
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
            logger.info(f"📱 Bestätigung an Telegram gesendet")
        except Exception as e:
            logger.warning(f"⚠️ Telegram Fehler: {e}")
        
        return {
            "status": "success",
            "message": "Spende erfolgreich bestätigt!",
            "donation_id": donation_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/donation/{donation_id}")
def delete_donation(donation_id: int):
    """Spende löschen"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Erst die Spende abrufen für Telegram-Nachricht
        donation = conn.execute("SELECT * FROM donations WHERE id=?", (donation_id,)).fetchone()
        if not donation:
            conn.close()
            raise HTTPException(status_code=404, detail="Spende nicht gefunden")
        
        # Jetzt löschen
        cursor.execute("DELETE FROM donations WHERE id=?", (donation_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"🗑️ Gelöscht: #{donation_id}")
        
        # Telegram Benachrichtigung
        try:
            full_name = f"{donation['name']} {donation['nachname']}".strip()
            message = f"""
🗑️ Spende gelöscht!

👤 Name: {full_name}
💰 Betrag: {donation['betrag']} €
🎯 Aktion: {donation['aktionName']}
            """
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": CHAT_ID, "text": message}, timeout=10)
            logger.info(f"📱 Löschung an Telegram gesendet")
        except Exception as e:
            logger.warning(f"⚠️ Telegram Fehler: {e}")
        
        return {
            "status": "success",
            "message": "Spende erfolgreich gelöscht!",
            "donation_id": donation_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/donations/statistics")
def get_statistics():
    """Statistiken für alle Aktionen abrufen"""
    try:
        conn = get_db_connection()
        
        rows = conn.execute("""
            SELECT name, nachname, betrag, aktionName
            FROM donations 
            WHERE status='confirmed'
            ORDER BY aktionName, timestamp DESC
        """).fetchall()
        conn.close()
        
        # Gruppiere nach Aktion
        aktionen_dict = {}
        for r in rows:
            aktion_name = r["aktionName"]
            if aktion_name not in aktionen_dict:
                aktionen_dict[aktion_name] = {
                    "name": aktion_name,
                    "gesammelt": 0.0,
                    "donations": []
                }
            
            aktionen_dict[aktion_name]["gesammelt"] += r["betrag"]
            aktionen_dict[aktion_name]["donations"].append({
                "name": f"{r['name']} {r['nachname']}".strip(),
                "betrag": r["betrag"]
            })
        
        result = list(aktionen_dict.values())
        logger.info(f"📊 {len(result)} Aktionen mit Statistiken")
        
        return {"aktionen": result}
        
    except Exception as e:
        logger.error(f"❌ {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/donations/all")
def get_all_donations():
    """Alle Spenden abrufen (für Debugging)"""
    try:
        conn = get_db_connection()
        rows = conn.execute("""
            SELECT id, name, nachname, telefon, kontaktArt, betrag, aktionName, status, timestamp 
            FROM donations 
            ORDER BY timestamp DESC
        """).fetchall()
        conn.close()
        
        result = [{
            "id": r["id"],
            "name": f"{r['name']} {r['nachname']}".strip(),
            "telefon": r["telefon"],
            "kontaktArt": r["kontaktArt"],
            "betrag": float(r["betrag"]),
            "aktionName": r["aktionName"],
            "status": r["status"],
            "timestamp": r["timestamp"]
        } for r in rows]
        
        return {"total": len(result), "donations": result}
    except Exception as e:
        logger.error(f"❌ {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== SERVER STARTEN ====================
if __name__ == "__main__":
    print("="*60)
    print("🚀 Spenden-API startet...")
    print("="*60)
    print(f"📋 Environment: {ENV}")
    print(f"🌐 Lokal:      http://localhost:8000")
    print(f"📄 API Docs:   http://localhost:8000/docs")
    print(f"🎨 Swagger UI: http://localhost:8000/docs")
    print(f"📚 ReDoc:      http://localhost:8000/redoc")
    print("="*60)
    print(f"🤖 Telegram Bot: {'✅ Konfiguriert' if BOT_TOKEN and CHAT_ID else '❌ Nicht konfiguriert'}")
    print("="*60)
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)