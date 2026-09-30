import base64
import json
import re
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from .prompt import SYSTEM_PROMPT
from .schemas import ModelAssessment

async def compare_images(references: list[bytes], images: list[bytes], api_key: str, model: str) -> ModelAssessment:
    if not re.fullmatch(r'gemini-[a-zA-Z0-9.\-]+', model):
        raise HTTPException(400, 'Invalid Gemini model name.')
    parts = [{'text': f'Compare {len(images)} NEW images against {len(references)} REFERENCE images. Reference views are fixed clean targets.'}]
    for label, files in [('REFERENCE', references), ('NEW', images)]:
        for i, data in enumerate(files, 1):
            parts.extend([{'text': f'{label} IMAGE {i}'}, {'inlineData': {
                'mimeType': 'image/jpeg', 'data': base64.b64encode(data).decode()}}])
    payload = {'systemInstruction': {'parts': [{'text': SYSTEM_PROMPT}]},
               'contents': [{'role': 'user', 'parts': parts}],
               'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 12000,
                                    'responseMimeType': 'application/json',
                                    'responseJsonSchema': ModelAssessment.model_json_schema()}}
    if len(json.dumps(payload).encode()) > 19 * 1024 * 1024:
        raise HTTPException(413, 'Combined photos are too large for Gemini. Use fewer or lower-resolution photos.')
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            response = await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                                         headers={'x-goog-api-key': api_key}, json=payload)
    except httpx.TimeoutException:
        raise HTTPException(504, 'Gemini timed out. Please try again with fewer images.') from None
    except httpx.RequestError:
        raise HTTPException(502, 'Could not connect to Gemini. Check the server network and retry.') from None
    if response.status_code in (401, 403):
        raise HTTPException(400, 'Gemini rejected the API key or its permissions. Check your key.')
    if response.status_code == 429:
        raise HTTPException(429, 'Gemini quota exceeded. Wait and retry, or check your API quota.')
    if response.status_code == 404:
        raise HTTPException(400, 'This Gemini model is unavailable. Update GEMINI_MODEL in .env and restart.')
    if response.status_code >= 400:
        raise HTTPException(502, f'Gemini could not process this inspection (HTTP {response.status_code}). Check model access and retry.')
    try:
        candidate = response.json()['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Incomplete or blocked response')
        output = ''.join(p.get('text', '') for p in candidate['content']['parts'] if not p.get('thought'))
        return ModelAssessment.model_validate_json(output)
    except (KeyError, IndexError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
        raise HTTPException(502, 'Gemini returned an incomplete or invalid assessment. No score was saved; please retry.') from None
