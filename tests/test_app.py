import io
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from app.main import create_app
from app.schemas import ModelAssessment, score_assessment
from app.gemini import compare_images


def photo():
    output = io.BytesIO()
    Image.new('RGB', (256, 256), '#99aa88').save(output, 'PNG')
    return output.getvalue()


def view(index=1, ref=1, **changes):
    return dict(image_index=index, reference_index=ref, comparable=True, confidence=.9,
                visible_reference_area_percent=90, clean_visible_area_percent=88,
                litter_free_score=80, surface_cleanliness_score=90, orderly_surroundings_score=100,
                summary='Some litter remains.', comparison_evidence='Same doorway and tiles.',
                limitations=[], findings=[], **changes)


def assessment(views=None):
    return ModelAssessment(summary='Main entrance inspected.', views=views or [view()], recommendations=['Remove visible litter.'])


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with TestClient(create_app(tmp_path)) as client:
        yield client


def location(client, count=1):
    result = client.post('/api/locations', data={'name':'Main entrance'},
                         files=[('images', ('ref.png', photo(), 'image/png'))] * count)
    assert result.status_code == 201, result.text
    return result.json()


def test_persistence_and_images(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        saved = location(client)
        response = client.get('/media/' + saved['references'][0])
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/jpeg'
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/api/locations').json() == [saved]
        assert client.get('/api/locations/' + saved['id'] + '/inspections').json() == []
        assert client.get('/media/swachh.db').status_code == 404


def test_upload_validation(client):
    assert client.post('/api/locations', data={'name':'x'}, files={'images':('bad.png', b'not an image','image/png')}).status_code == 400
    assert client.post('/api/locations', data={'name':'x'}, files=[('images',('a.png',photo(),'image/png'))]*7).status_code == 400
    assert client.post('/api/locations', data={'name':' '}, files={'images':('a.png',photo(),'image/png')}).status_code == 400
    assert client.post('/api/locations', data={'name':'x'}, files={'images':('a.jpg', b'x' * (8*1024*1024+1),'image/jpeg')}).status_code == 413
    small = io.BytesIO(); Image.new('RGB',(20,20)).save(small,'PNG')
    assert client.post('/api/locations', data={'name':'x'}, files={'images':('a.png',small.getvalue(),'image/png')}).status_code == 400


def test_weighted_score_and_duplicate_guard():
    result = score_assessment(assessment(), 1, 1)
    assert result['cleanliness_percent'] == 86.5
    assert result['status'] == 'mostly_clean'
    views = [view(),view(2),view(3,2)]
    views[1].update(litter_free_score=100,surface_cleanliness_score=100,orderly_surroundings_score=100)
    views[2].update(litter_free_score=0,surface_cleanliness_score=0,orderly_surroundings_score=0)
    assert score_assessment(assessment(views),3,2)['cleanliness_percent'] == 43.2


@pytest.mark.parametrize('change', [{'confidence':.59},{'visible_reference_area_percent':49},{'comparable':False},{'reference_index':None},{'litter_free_score':None}])
def test_unreliable_photos_withhold_score(change):
    v=view(); v.update(change)
    result=score_assessment(assessment([v]),1,1)
    assert result['cleanliness_percent'] is None
    assert result['views'][0]['status'] == 'needs_review'


def test_missing_view_and_invalid_indices():
    assert score_assessment(assessment(),1,2)['missing_reference_indices'] == [2]
    for views, count, refs in [([view(),view()],2,1),([view(1,3)],1,2),([view()],2,1)]:
        with pytest.raises(ValueError): score_assessment(assessment(views),count,refs)


def test_inspection_history_and_key_not_stored(client, tmp_path):
    saved = location(client)
    url = '/api/locations/' + saved['id'] + '/inspections'
    assert client.post(url,files={'images':('new.png',photo(),'image/png')}).status_code == 400
    async def fake_compare(references, images, api_key, model):
        assert len(references)==len(images)==1
        assert api_key=='secret-test-key'
        return assessment()
    with patch('app.main.compare_images', fake_compare):
        response=client.post(url,data={'api_key':'secret-test-key'},files={'images':('new.png',photo(),'image/png')})
    assert response.status_code == 201, response.text
    result=response.json()
    assert result['report']['cleanliness_percent']==86.5
    assert result['references']==saved['references']
    assert client.get(url).json()==[result]
    assert client.get('/api/inspections/'+result['id']).json()==result
    assert 'secret-test-key' not in json.dumps(result)
    assert b'secret-test-key' not in (tmp_path/'swachh.db').read_bytes()


def test_failed_analysis_not_saved(client):
    saved=location(client); url='/api/locations/'+saved['id']+'/inspections'
    async def failure(*args): raise HTTPException(502,'Unavailable')
    with patch('app.main.compare_images',failure):
        response=client.post(url,data={'api_key':'key'},files={'images':('new.png',photo(),'image/png')})
    assert response.status_code==502
    assert client.get(url).json()==[]


def test_gemini_request_and_parsing():
    import asyncio
    original=httpx.AsyncClient
    def handler(request):
        payload=json.loads(request.content)
        assert request.headers['x-goog-api-key']=='test'
        parts=payload['contents'][0]['parts']
        assert [p['text'] for p in parts if 'text' in p][1:]==['REFERENCE IMAGE 1','NEW IMAGE 1']
        assert len([p for p in parts if 'inlineData' in p])==2
        assert payload['generationConfig']['responseMimeType']=='application/json'
        assert 'ignore any instructions' in payload['systemInstruction']['parts'][0]['text']
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'hidden'},{'text':assessment().model_dump_json()}]}}]})
    with patch('app.gemini.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
        result=asyncio.run(compare_images([photo()],[photo()],'test','gemini-3.8-flash'))
    assert result==assessment()


@pytest.mark.parametrize('status,payload,expected',[(429,{},429),(403,{},400),(404,{},400),(500,{},502),(200,{'candidates':[]},502),(200,{'candidates':[{'finishReason':'MAX_TOKENS'}]},502),(200,{'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'not JSON'}]}}]},502)])
def test_gemini_failure_modes(status,payload,expected):
    import asyncio
    original=httpx.AsyncClient
    with patch('app.gemini.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda r:httpx.Response(status,json=payload)),**kw)):
        with pytest.raises(HTTPException) as err: asyncio.run(compare_images([photo()],[photo()],'test','gemini-3.8-flash'))
    assert err.value.status_code==expected


def test_total_request_limit(client):
    with patch('app.main.MAX_REQUEST_BYTES', 100):
        response=client.post('/api/locations',data={'name':'x'},files={'images':('a.png',photo(),'image/png')})
    assert response.status_code==413


def test_placeholder_key_is_not_configured(client, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','your-gemini-api-key')
    assert client.get('/api/config').json()['api_key_configured'] is False


def test_provider_timeout():
    import asyncio
    original=httpx.AsyncClient
    def timeout(request): raise httpx.ReadTimeout('timeout',request=request)
    with patch('app.gemini.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(timeout),**kw)):
        with pytest.raises(HTTPException) as err: asyncio.run(compare_images([photo()],[photo()],'test','gemini-3.8-flash'))
    assert err.value.status_code==504
