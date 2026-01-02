import json
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
            
            If waste is present, identify the primary waste type and return ONLY a valid JSON object in the following format:
            
            {
              "waste_type": "<specific waste type>",
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