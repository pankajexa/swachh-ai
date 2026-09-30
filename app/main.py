import asyncio
import io
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .gemini import compare_images
from .prompt import PROMPT_VERSION
from .schemas import score_assessment
from .storage import Store

BASE = Path(__file__).resolve().parent
load_dotenv(BASE.parent / '.env')
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 6
MAX_REQUEST_BYTES = 50 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 25_000_000

class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        total = 0
        async def limited_receive():
            nonlocal total
            message = await receive()
            if message['type'] == 'http.request':
                total += len(message.get('body', b''))
                if total > MAX_REQUEST_BYTES:
                    raise HTTPException(413, 'Upload exceeds the 50 MB request limit.')
            return message
        await self.app(scope, limited_receive, send)

def normalize_image(raw: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('Unsupported format')
                if getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('Animated image')
                source.load()
                img = ImageOps.exif_transpose(source).convert('RGB')
                if min(img.size) < 128:
                    raise ValueError('Too small')
                img.thumbnail((1600, 1600))
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=85)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(400, 'Use valid, non-animated JPG, PNG or WebP images, at least 128px on each side and no more than 25 megapixels.') from None

async def read_images(files: list[UploadFile]) -> list[bytes]:
    try:
        if not 1 <= len(files) <= MAX_IMAGES:
            raise HTTPException(400, 'Upload between 1 and 6 images.')
        results = []
        for file in files:
            raw = await file.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise HTTPException(413, 'Each image must be 8 MB or smaller.')
            results.append(await run_in_threadpool(normalize_image, raw))
        return results
    finally:
        for file in files:
            await file.close()

def save_images(store, images):
    paths = []
    try:
        for raw in images:
            filename = f'{uuid4().hex}.jpg'
            (store.media / filename).write_bytes(raw)
            paths.append(filename)
    except Exception:
        for name in paths:
            (store.media / name).unlink(missing_ok=True)
        raise
    return paths

def now():
    return datetime.now(timezone.utc).isoformat()

def create_app(data_dir: Path | None = None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(data_dir or Path(os.getenv('DATA_DIR', str(BASE.parent / 'data'))))
        app.state.comparison_slots = asyncio.Semaphore(2)
        yield

    app = FastAPI(title='Swachh AI', version='1.0.0', lifespan=lifespan)
    app.add_middleware(RequestSizeLimit)
    app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')

    @app.get('/')
    def index():
        return FileResponse(BASE / 'static' / 'index.html')

    @app.get('/api/config')
    def config():
        key = os.getenv('GEMINI_API_KEY', '').strip()
        return {'api_key_configured': bool(key and key != 'your-gemini-api-key'),
                'model': os.getenv('GEMINI_MODEL', 'gemini-3.8-flash'), 'max_images': MAX_IMAGES}

    @app.get('/api/locations')
    def locations(request: Request):
        return request.app.state.store.locations()

    @app.post('/api/locations', status_code=201)
    async def add_location(request: Request, name: str = Form(..., max_length=120), images: list[UploadFile] = File(...)):
        if not name.strip():
            raise HTTPException(400, 'Give this location a name.')
        raw = await read_images(images)
        store = request.app.state.store
        paths = await run_in_threadpool(save_images, store, raw)
        payload = {'id': uuid4().hex, 'name': name.strip(), 'created_at': now(), 'references': paths}
        try:
            await run_in_threadpool(store.save_location, payload)
        except Exception:
            for path in paths:
                (store.media / path).unlink(missing_ok=True)
            raise
        return payload

    @app.get('/api/locations/{location_id}/inspections')
    def history(location_id: str, request: Request):
        store = request.app.state.store
        if not store.location(location_id):
            raise HTTPException(404, 'Location not found.')
        return store.inspections(location_id)

    @app.get('/api/inspections/{inspection_id}')
    def get_inspection(inspection_id: str, request: Request):
        result = request.app.state.store.inspection(inspection_id)
        if not result:
            raise HTTPException(404, 'Inspection not found.')
        return result

    @app.post('/api/locations/{location_id}/inspections', status_code=201)
    async def inspect(location_id: str, request: Request, images: list[UploadFile] = File(...),
                      api_key: str = Form('', max_length=256)):
        store = request.app.state.store
        location = await run_in_threadpool(store.location, location_id)
        if not location:
            raise HTTPException(404, 'Location not found.')
        key = api_key.strip() or os.getenv('GEMINI_API_KEY', '').strip()
        if not key or key == 'your-gemini-api-key':
            raise HTTPException(400, 'Add your Gemini API key in Settings or the server .env file.')
        raw = await read_images(images)
        references = [(store.media / path).read_bytes() for path in location['references']]
        model = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
        async with request.app.state.comparison_slots:
            assessment = await compare_images(references, raw, key, model)
        try:
            report = score_assessment(assessment, len(raw), len(references))
        except ValueError:
            raise HTTPException(502, 'Gemini returned inconsistent image matches. No score was saved; retry the inspection.') from None
        paths = await run_in_threadpool(save_images, store, raw)
        result = {'id': uuid4().hex, 'location_id': location_id, 'location_name': location['name'],
                  'created_at': now(), 'images': paths, 'references': location['references'],
                  'model': model, 'prompt_version': PROMPT_VERSION, 'report': report}
        try:
            await run_in_threadpool(store.save_inspection, result)
        except Exception:
            for path in paths:
                (store.media / path).unlink(missing_ok=True)
            raise
        return result

    @app.get('/media/{filename}')
    def media(filename: str, request: Request):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}\.jpg', filename):
            raise HTTPException(404, 'Image not found.')
        path = request.app.state.store.media / filename
        if not path.is_file():
            raise HTTPException(404, 'Image not found.')
        return FileResponse(path, media_type='image/jpeg', headers={'X-Content-Type-Options': 'nosniff'})

    return app

app = create_app()
