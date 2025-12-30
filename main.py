from fastapi import FastAPI, File, UploadFile
# 1. Fix the import (it is .cors, not .cores)
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all connections (good for dev)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post('/detect')
async def detect_waste(file: UploadFile = File(...)):
    return {
        'waste_type' : 'Paperuuu',
        'quantity' : '10',
    }

