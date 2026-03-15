import json
import base64
import io
from PIL import Image
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, messaging
import cloudinary
import cloudinary.uploader
import requests

load_dotenv()

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Firebase Initialization ---
# Ensure you have your serviceAccountKey.json in the same directory or provide the correct path.
# You can download this from Firebase Console -> Project Settings -> Service Accounts.
try:
    if not firebase_admin._apps:
        if os.path.exists('/etc/secrets/serviceAccountKey.json'):
            cred = credentials.Certificate('/etc/secrets/serviceAccountKey.json')
        elif os.path.exists('serviceAccountKey.json'):
            cred = credentials.Certificate('serviceAccountKey.json')
        else:
            raise FileNotFoundError("serviceAccountKey.json not found")
        firebase_admin.initialize_app(cred)
        print("Firebase initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase: {e}")


# IMPORTANT: Keep your API key safe
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# 1. New Client initialization
client = genai.Client(api_key=GOOGLE_API_KEY)

@app.get('/')
def status():
    return {"status": "Waste Detection API is running."}

@app.post('/detect')
async def detect_waste(file: UploadFile = File(...)):
    try:
        # 2. Read bytes and reset cursor if necessary
        image_bytes = await file.read()

        # 3. Define the prompt clearly
        prompt = """
            Analyze the given image strictly for waste management.
            
            Identify the primary waste type from these categories: "PLASTIC", "PAPER", "METAL", or "OTHERS".
            
            Rules for classification:
            1. If the waste fits perfectly into PLASTIC, PAPER, or METAL, choose that category.
            2. If the waste is not a perfect match but is primarily made of or closely aligned to one of these three, choose the most appropriate one.
            3. If it absolutely does not fit into PLASTIC, PAPER, or METAL, categorize it as "OTHERS".
            
            Return ONLY a valid JSON object in the following format:
            
            {
              "waste_type": "<One of: PLASTIC, PAPER, METAL, OTHERS>",
              "quantity": <estimated item count as an integer>,
              "disposal_methods": [
                "<clear and practical disposal method 1>",
                "<clear and practical disposal method 2>",
                "<clear and practical disposal method 3>"
              ],
              "mistakes_to_avoid": [
                "<common mistake 1>",
                "<common mistake 2>",
                "<common mistake 3>"
              ]
            }
            
            If NO waste is detected, return ONLY this JSON:
            
            {
              "waste_type": "No waste detected",
              "quantity": 0,
              "disposal_methods": [],
              "mistakes_to_avoid": []
            }
            
            Rules:
            - Respond with JSON only.
            - Do NOT include markdown, explanations, or extra text.
            - Lists must contain 3 concise, practical items when waste is detected.
            """


        # 4. Use the new generation method
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type="image/jpeg",  # change to image/png if needed
                ),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )

        # 5. Parse the text response into a dictionary
        return json.loads(response.text)

    except Exception as e:
        print(f"Detailed Error: {e}")
        return {"waste_type": "Error", "quantity": 0, "message": str(e)}
@app.post("/upload")
async def upload_data(
    file: UploadFile = File(...),
    waste_type: str = Form(...),
    quantity: str = Form(...),
    location: str = Form(...),
    date: str = Form(...)
):
    try:
        if firebase_admin._apps:
            # 1. Read file
            file_content = await file.read()
            
            # --- Cloudinary Upload Logic ---
            try:
                print(f"Uploading image to Cloudinary...")
                print(f"Uploading image to Cloudinary...")
                cloudinary_url = f"https://api.cloudinary.com/v1_1/dcimzj1yx/image/upload"
                files = {'file': file_content}
                data = {'upload_preset': 'Unsigned'}
                response = requests.post(cloudinary_url, files=files, data=data)
                
                if response.status_code == 200:
                    res_json = response.json()
                    image_url = res_json.get('secure_url')
                    print(f"Cloudinary upload success: {image_url}")
                else:
                    print(f"Cloudinary upload FAILED ({response.status_code}): {response.text}")
                    image_url = ""
            except Exception as cloudinary_err:
                print(f"Cloudinary error: {cloudinary_err}")
                image_url = ""

            # 2. Save Metadata to Firestore
            db = firestore.client()
            
            doc_ref = db.collection('waste_items').add({
                'type': waste_type, # Keep both 'type' and 'waste_type' for compatibility
                'waste_type': waste_type,
                'quantity': quantity,
                'qty': quantity, # Compatibility
                'location': location,
                'date': date,
                'imageUrl': image_url,
                'image_url': image_url, # Redundancy
                'timestamp': firestore.SERVER_TIMESTAMP,
                'time': firestore.SERVER_TIMESTAMP # Compatibility
            })

            # Extract the document id (keep the existing indexing behavior)
            try:
                doc_id = doc_ref[1].id
            except Exception:
                # Fallback if the return shape is different
                try:
                    doc_id = doc_ref[0].id
                except Exception:
                    doc_id = None

            # 3. Send an FCM topic notification so Flutter clients receive the update.
            # Clients should subscribe to the `waste_updates` topic to receive these notifications.
            
            try:
                notif_title = "New waste item reported"
                notif_body = f"{waste_type} ({quantity}) at {location}"

                message = messaging.Message(
                    notification=messaging.Notification(
                        title=notif_title,
                        body=notif_body
                    ),
                    data={
                        'id': doc_id or '',
                        'waste_type': waste_type,
                        'quantity': str(quantity),
                        'location': location,
                        'date': date
                    },
                    topic='waste_updates'
                )

                send_result = messaging.send(message)
            except Exception as e:
                # Log but don't fail the whole request if notification fails
                print(f"FCM send error: {e}")
                send_result = None

            return {
                "status": "success",
                "message": "Data and image uploaded to Firestore successfully",
                "id": doc_id,
                "fcm_result": send_result
            }
        else:
             return {"status": "error", "message": "Firebase not initialized. Check server logs."}

    except Exception as e:
        print(f"Error in /upload: {e}")
        return {"status": "error", "message": str(e)}

        