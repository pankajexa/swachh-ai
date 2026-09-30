const $ = s => document.querySelector(s);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let locations = [], currentLocation = null, newFiles = [], apiKey = '', busy = false, currentResult = null;
let previewURLs = [];
const labels = {clean:'Meets the clean standard', mostly_clean:'Mostly clean', needs_cleaning:'More cleaning needed', needs_review:'Needs a closer look'};
const formatDate = d => new Date(d).toLocaleString(undefined, {dateStyle:'medium', timeStyle:'short'});
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path, options); } catch { throw new Error('Cannot reach the backend. Check that the server is running.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the input fields and image limits.');
  return data;
}
function showError(message) { $('#alert').textContent = message; $('#alert').hidden = !message; }
function updateAnalyze() { $('#analyze-btn').disabled = busy || !currentLocation || !newFiles.length; }
function imageHTML(src, caption) { return `<figure><img src="${escapeHTML(src)}" alt="${escapeHTML(caption)}" data-expand="${escapeHTML(src)}"><figcaption>${escapeHTML(caption)}</figcaption></figure>`; }
function renderLocations() {
  $('#location-list').innerHTML = locations.length ? locations.map(l => `<button data-location="${l.id}" class="${l.id === currentLocation?.id ? 'selected' : ''}">⌖ &nbsp; ${escapeHTML(l.name)}</button>`).join('') : '<p class="sidebar-empty">Your locations will appear here.</p>';
}
async function selectLocation(id) {
  if (busy) return;
  currentLocation = locations.find(l => l.id === id);
  renderLocations(); showError(''); clearFiles();
  $('#location-title').textContent = currentLocation.name;
  $('#location-subtitle').textContent = `${currentLocation.references.length} fixed reference ${currentLocation.references.length === 1 ? 'view' : 'views'} · Ready for recurring inspections`;
  $('#reference-gallery').classList.remove('empty-gallery');
  $('#reference-gallery').innerHTML = currentLocation.references.map((p, i) => imageHTML(`/media/${p}`, `Reference ${i+1}`)).join('');
  $('#results').hidden = true;
  currentResult = null;
  $('#history-list').innerHTML = '<p>Loading inspections…</p>';
  try { await loadHistory(id); } catch(e) { showError(e.message); }
  updateAnalyze();
}
async function loadHistory(id) {
  const history = await api(`/api/locations/${id}/inspections`);
  if (currentLocation?.id !== id) return;
  $('#history-count').textContent = `${history.length} INSPECTION${history.length === 1 ? '' : 'S'}`;
  $('#history-list').className = history.length ? '' : 'history-empty';
  $('#history-list').innerHTML = history.length ? history.map(r => `<button class="history-row" data-inspection="${r.id}"><div>${escapeHTML(formatDate(r.created_at))}<small>${escapeHTML(labels[r.report.status])} · ${r.images.length} photos</small></div><span class="history-score">${r.report.cleanliness_percent === null ? 'Review ↗' : r.report.cleanliness_percent + '%'}</span></button>`).join('') : '<span>◷</span><div><strong>No inspections yet</strong><p>Your completed inspections will appear here.</p></div>';
}
function clearFiles() {
  newFiles = []; $('#new-images').value = '';
  previewURLs.forEach(URL.revokeObjectURL); previewURLs = [];
  $('#new-gallery').innerHTML = ''; $('#new-gallery').hidden = true;
  $('#drop-zone').hidden = false; $('#upload-controls').hidden = true; updateAnalyze();
}
function validateFiles(files) {
  if (!files.length || files.length > 6) throw new Error('Choose between 1 and 6 photos.');
  if (files.some(f => f.size > 8 * 1024 * 1024)) throw new Error('Each photo must be 8 MB or smaller.');
  if (files.some(f => !['image/jpeg','image/png','image/webp'].includes(f.type))) throw new Error('Choose JPG, PNG or WebP photos.');
}
function setFiles(files) {
  if (busy) return;
  try { validateFiles(files); } catch(e) { showError(e.message); return; }
  clearFiles(); newFiles = files; showError('');
  $('#new-gallery').innerHTML = files.map((f,i) => { const url = URL.createObjectURL(f); previewURLs.push(url); return imageHTML(url, `New ${i+1} · ${f.name}`); }).join('');
  $('#new-gallery').hidden = false; $('#drop-zone').hidden = true; $('#upload-controls').hidden = false;
  $('#photo-count').textContent = `${files.length} photos ready`; updateAnalyze();
}
function metric(name, value) { return `<div class="metric"><strong>${value === null ? '—' : Math.round(value) + '%'}</strong><span>${name}</span><div class="meter"><i style="width:${value ?? 0}%"></i></div></div>`; }
function renderReport(result) {
  currentResult = result;
  const r = result.report;
  $('#results').hidden = false;
  $('#results').innerHTML = `<div class="report-header"><h2>Inspection results</h2><button id="download-report" class="button secondary">↓ Download JSON</button></div>
  <div class="report-top"><div class="score-block"><div class="score-number">${r.cleanliness_percent === null ? '—' : r.cleanliness_percent + '<small>%</small>'}</div><div class="score-label">${r.cleanliness_percent === null ? 'Overall score withheld' : 'Estimated cleanliness'}</div></div><div><div class="eyebrow">${escapeHTML(formatDate(result.created_at))}</div><h3>${escapeHTML(labels[r.status])}</h3><p>${escapeHTML(r.summary)}</p><div class="report-meta"><span>${r.reference_coverage_percent}% of reference views assessable</span><span>${r.views.length} photos inspected</span></div></div></div>
  ${r.cleanliness_percent === null ? `<div class="report-notice">A whole-location score needs a usable match for every reference and every submitted photo. ${r.missing_reference_indices.length ? 'Retake reference views: ' + r.missing_reference_indices.join(', ') + '.' : 'Retake the photos marked for review below.'}</div>` : ''}
  ${r.views.map(v => `<article class="view-card"><div class="view-title"><h3>Photo ${v.image_index} <span style="color:#93a08a;font-weight:400">/ ${v.reference_index ? 'Reference ' + v.reference_index : 'No reliable match'}</span></h3><span class="badge neutral">${v.cleanliness_percent === null ? 'REVIEW REQUIRED' : v.cleanliness_percent + '% CLEAN'}</span></div>
  <div class="view-images"><div>${v.reference_index ? `<img src="/media/${result.references[v.reference_index-1]}" data-expand="/media/${result.references[v.reference_index-1]}" alt="Matched clean reference"><small>REFERENCE · CLEAN STANDARD</small>` : '<p>No matching reference</p>'}</div><div><img src="/media/${result.images[v.image_index-1]}" data-expand="/media/${result.images[v.image_index-1]}" alt="New inspection photo"><small>NEW · INSPECTION PHOTO</small></div></div>
  <p>${escapeHTML(v.summary)}</p><p><strong>Comparison evidence:</strong> ${escapeHTML(v.comparison_evidence)}</p>
  <div class="metrics">${metric('Litter-free · 50% weight', v.status === 'scored' ? v.litter_free_score : null)}${metric('Surface cleanliness · 35%', v.status === 'scored' ? v.surface_cleanliness_score : null)}${metric('Orderly surroundings · 15%', v.status === 'scored' ? v.orderly_surroundings_score : null)}</div>
  <div class="report-meta"><span>Model confidence: ${Math.round(v.confidence*100)}% (self-reported)</span><span>Reference area visible: ${Math.round(v.visible_reference_area_percent)}%</span><span>Visibly clean ground: ${v.status !== 'scored' || v.clean_visible_area_percent === null ? 'Not assessed' : Math.round(v.clean_visible_area_percent) + '% (estimate)'}</span></div>
  ${v.findings.length ? `<div class="table-wrap"><table><thead><tr><th>OBJECT / ISSUE</th><th>WHERE & EVIDENCE</th><th>NEXT ACTION</th></tr></thead><tbody>${v.findings.map(f => `<tr><td><strong>${escapeHTML(f.object)}</strong><small>${escapeHTML(f.category.replaceAll('_',' '))}${f.approximate_count === null ? '' : ' · Approx. ' + f.approximate_count}</small><span class="severity">${escapeHTML(f.severity)} severity</span></td><td>${escapeHTML(f.location)}<small>${escapeHTML(f.evidence)}</small></td><td>${escapeHTML(f.action)}</td></tr>`).join('')}</tbody></table></div>` : `<p>${v.status === 'scored' ? 'No visible cleaning issues identified in this photo.' : 'No reliable findings reported for this photo.'}</p>`}
  ${v.limitations.length ? `<div class="report-notice"><strong>Limitations:</strong> ${v.limitations.map(escapeHTML).join(' · ')}</div>` : ''}</article>`).join('')}
  ${r.recommendations.length ? `<div class="recommendations"><h3>Recommended next steps</h3><ul>${r.recommendations.map(x => `<li>${escapeHTML(x)}</li>`).join('')}</ul></div>` : ''}
  <details class="technical-details"><summary>How this score is calculated</summary><p>Each photo: 50% litter-free + 35% surface cleanliness + 15% orderly surroundings. We take the lowest score for each reference view, then average the reference views equally. All reference views must be covered; every photo must be comparable with at least 60% confidence and 50% reference visibility. This is a visual index, not a measured percentage of dirt removed, proof of cleaning, or a sanitation assessment.</p><p>Model: ${escapeHTML(result.model)} · Prompt ${escapeHTML(result.prompt_version)} · Scoring ${escapeHTML(r.scoring_version)}. Scores and confidence are estimates; review the photos alongside findings.</p></details>`;
  $('#results').scrollIntoView({behavior:'smooth',block:'start'});
}
function openSetup() { if (!busy) $('#location-dialog').showModal(); }
$('#add-location').onclick = $('#new-location-btn').onclick = $('#setup-btn').onclick = openSetup;
$('#settings-btn').onclick = () => $('#settings-dialog').showModal();
document.querySelectorAll('.close-dialog').forEach(b => b.onclick = () => b.closest('dialog').close());
$('#settings-form').onsubmit = e => { e.preventDefault(); apiKey = $('#api-key').value.trim(); $('#key-dot').classList.toggle('ready', Boolean(apiKey || window.serverKey)); $('#settings-dialog').close(); showError(''); };
$('#reference-images').onchange = e => {
  const files = [...e.target.files];
  $('#reference-preview').innerHTML = '';
  try { validateFiles(files); $('#location-error').textContent = ''; } catch(error) { $('#location-error').textContent = error.message; return; }
  files.forEach((f,i) => { const image = document.createElement('img'); const url = URL.createObjectURL(f); image.src = url; image.alt = `Reference ${i+1} preview`; image.onload = image.onerror = () => URL.revokeObjectURL(url); $('#reference-preview').append(image); });
};
$('#location-form').onsubmit = async e => {
  e.preventDefault(); const btn = e.target.querySelector('[type=submit]'); btn.disabled = true; $('#location-error').textContent = '';
  try {
    const files = [...$('#reference-images').files]; validateFiles(files);
    const form = new FormData(); form.append('name', $('#location-name').value.trim()); files.forEach(f => form.append('images', f));
    const result = await api('/api/locations', {method:'POST',body:form}); locations.unshift(result);
    $('#location-dialog').close(); e.target.reset(); $('#reference-preview').innerHTML = ''; await selectLocation(result.id);
  } catch(error) { $('#location-error').textContent = error.message; } finally { btn.disabled = false; }
};
$('#new-images').onchange = e => setFiles([...e.target.files]);
$('#clear-photos').onclick = () => { if(!busy) clearFiles(); };
const drop = $('#drop-zone');
['dragenter','dragover'].forEach(event => drop.addEventListener(event,e => {e.preventDefault(); drop.classList.add('dragging');}));
['dragleave','drop'].forEach(event => drop.addEventListener(event,e => {e.preventDefault(); drop.classList.remove('dragging');}));
drop.addEventListener('drop', e => setFiles([...e.dataTransfer.files]));
$('#analyze-btn').onclick = async () => {
  if (!currentLocation || !newFiles.length || busy) return;
  if (!apiKey && !window.serverKey) { $('#settings-dialog').showModal(); return; }
  const id = currentLocation.id;
  busy = true; updateAnalyze(); showError(''); $('#progress').hidden = false; $('#results').hidden = true; $('#analyze-btn').textContent = 'Analyzing…';
  try {
    const form = new FormData(); newFiles.forEach(f => form.append('images', f)); if(apiKey) form.append('api_key',apiKey);
    const result = await api(`/api/locations/${id}/inspections`, {method:'POST', body:form});
    renderReport(result); await loadHistory(id);
  } catch(error) { showError(error.message); } finally { busy = false; updateAnalyze(); $('#progress').hidden = true; $('#analyze-btn').innerHTML = 'Analyze cleanliness <span>↗</span>'; }
};
document.addEventListener('click', async e => {
  const loc = e.target.closest('[data-location]'); if (loc) await selectLocation(loc.dataset.location);
  const inspection = e.target.closest('[data-inspection]');
  if(inspection && !busy) { const id = currentLocation.id; try { const result = await api(`/api/inspections/${inspection.dataset.inspection}`); if(currentLocation.id === id) renderReport(result); } catch(error) { showError(error.message); } }
  const photo = e.target.closest('[data-expand]'); if(photo) { $('#large-photo').src = photo.dataset.expand; $('#photo-dialog').showModal(); }
  if(e.target.closest('#download-report') && currentResult) { const url = URL.createObjectURL(new Blob([JSON.stringify(currentResult,null,2)],{type:'application/json'})); const a = document.createElement('a'); a.href = url; a.download = `swachh-inspection-${currentResult.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); }
});
(async () => {
  try {
    const [config, saved] = await Promise.all([api('/api/config'), api('/api/locations')]);
    window.serverKey = config.api_key_configured;
    $('#key-dot').classList.toggle('ready', config.api_key_configured);
    $('#server-key-note').textContent = config.api_key_configured ? 'A server API key is configured. Add a key below only to override it for this session.' : 'Connect your Gemini key to start analyzing photos.';
    $('#model-name').textContent = config.model;
    locations = saved; renderLocations(); if(locations.length) await selectLocation(locations[0].id);
  } catch(error) { showError(error.message); }
})();
