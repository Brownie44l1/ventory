import os
import httpx

WA_TOKEN  = os.environ["WHATSAPP_TOKEN"]
PHONE_ID  = os.environ["WHATSAPP_PHONE_ID"]
BASE_URL  = f"https://graph.facebook.com/v19.0/{PHONE_ID}"
MEDIA_URL = f"https://graph.facebook.com/v19.0/{PHONE_ID}/media"
HEADERS   = {"Authorization": f"Bearer {WA_TOKEN}"}


async def send_message(to: str, text: str):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text, "preview_url": False},
            },
        )
        r.raise_for_status()


async def send_document(to: str, media_id: str, filename: str):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE_URL}/messages",
            headers=HEADERS,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "document",
                "document": {"id": media_id, "filename": filename},
            },
        )
        r.raise_for_status()


async def upload_media(file_path: str, mime_type: str) -> str:
    async with httpx.AsyncClient() as client:
        with open(file_path, "rb") as f:
            r = await client.post(
                MEDIA_URL,
                headers=HEADERS,
                data={"messaging_product": "whatsapp"},
                files={"file": (os.path.basename(file_path), f, mime_type)},
            )
        r.raise_for_status()
        return r.json()["id"]


async def download_media(media_id: str) -> bytes:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://graph.facebook.com/v19.0/{media_id}",
            headers=HEADERS,
        )
        media_url = r.json()["url"]
        r = await client.get(media_url, headers=HEADERS)
        return r.content