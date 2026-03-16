import json
import base64
import io
from PIL import Image
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
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

# --- Cloudinary Configuration ---
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
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
    date: str = Form(...),
    latitude: float = Form(None),
    longitude: float = Form(None),
    userId: str = Form(None),
    userEmail: str = Form(None),
    userName: str = Form(None),
    userPhone: str = Form(None),
    userAddress: str = Form(None),
    dispose_ways: str = Form("[]"), # JSON string
    donts: str = Form("[]") # JSON string
):
    try:
        if firebase_admin._apps:
            # 1. Read file
            file_content = await file.read()
            
            # --- Cloudinary Upload Logic ---
            try:
                print(f"Uploading image to Cloudinary...")
                upload_result = cloudinary.uploader.upload(file_content)
                image_url = upload_result.get('secure_url')
                print(f"Cloudinary upload success: {image_url}")
            except Exception as cloudinary_err:
                print(f"Cloudinary error: {cloudinary_err}")
                image_url = ""

            # 2. Save Metadata to Firestore
            db = firestore.client()
            
            try:
                dispose_ways_list = json.loads(dispose_ways)
                donts_list = json.loads(donts)
            except:
                dispose_ways_list = []
                donts_list = []

            doc_ref = db.collection('waste_items').add({
                'type': waste_type,
                'waste_type': waste_type,
                'quantity': quantity,
                'qty': quantity,
                'location': location,
                'geo_location': {
                    'latitude': latitude,
                    'longitude': longitude,
                },
                'date': date,
                'imageUrl': image_url,
                'image_url': image_url,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'time': firestore.SERVER_TIMESTAMP,
                'dispose_ways': dispose_ways_list,
                'donts': donts_list,
                'userId': userId,
                'userEmail': userEmail,
                'userName': userName,
                'userPhone': userPhone,
                'userAddress': userAddress,
                'status': 'reported' # Base status
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
                        'date': date,
                        'status': 'reported'
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

@app.post("/update_status/{doc_id}")
async def update_status(doc_id: str, status: str = Form(...)):
    try:
        db = firestore.client()
        doc_ref = db.collection('waste_items').document(doc_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Document not found")
            
        doc_ref.update({'status': status})
        
        return {"status": "success", "message": f"Status updated to {status}"}
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error updating status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_proof/{doc_id}")
async def upload_proof(
    doc_id: str,
    file: UploadFile = File(...),
    remarks: str = Form("")
):
    try:
        db = firestore.client()
        doc_ref = db.collection('waste_items').document(doc_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Document not found")
            
        # 1. Read file
        file_content = await file.read()
        
        # 2. Upload to Cloudinary
        try:
            print(f"Uploading proof image to Cloudinary...")
            upload_result = cloudinary.uploader.upload(file_content)
            proof_image_url = upload_result.get('secure_url')
            print(f"Cloudinary upload success: {proof_image_url}")
        except Exception as cloudinary_err:
            print(f"Cloudinary error: {cloudinary_err}")
            raise HTTPException(status_code=500, detail="Failed to upload proof image")

        # 3. Update Firestore
        doc_ref.update({
            'status': 'cleared_pending_approval',
            'proofImageUrl': proof_image_url,
            'cleared_remarks': remarks,
            'cleared_at': firestore.SERVER_TIMESTAMP
        })
        
        # Send notification to the specific user who reported the waste
        data = doc.to_dict()
        user_id = data.get('userId')
        if user_id:
            try:
                notif_title = "Waste Clearance Pending Approval"
                notif_body = f"The waste at {data.get('location')} has been cleared. Please approve."
                
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=notif_title,
                        body=notif_body
                    ),
                    data={
                        'id': doc_id,
                        'status': 'cleared_pending_approval'
                    },
                    topic=f'user_{user_id}'
                )
                messaging.send(message)
            except:
                pass

        return {
            "status": "success", 
            "message": "Proof uploaded and status updated",
            "proofUrl": proof_image_url
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in /upload_proof: {e}")
        raise HTTPException(status_code=500, detail=str(e))

        