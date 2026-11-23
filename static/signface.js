const q = (selector, root = document) => root.querySelector(selector);
const state = {parts: [], part: null, config: null, tab: 'Captures', mode: 'outline', capture: null, listing: [], result: null, marks: false, survey: []};
const base = '/survey';
const dialog = q('#dialog');
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch]));
const fmt = value => value == null ? '—' : Array.isArray(value) ? value.join(', ') : String(value);
const title = value => value.replaceAll('_', ' ');
const partPath = () => '/parts/' + state.part.id;
const capturePath = id => partPath() + '/captures/' + id;
const markRows = purpose => state.part.marks.filter(mark => mark.purpose === purpose);
const tool = key => state.config.tools[key];
let toastTimer;
let navigation = 0;

function notice(msg, error = false) {
  const el = q('#toast');
  el.textContent = msg;
  el.hidden = false;
  el.classList.toggle('error', error);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, error ? 7000 : 3900);
}

async function api(path, method = 'GET', body = null) {
  const init = {method};
  if (body instanceof FormData) init.body = body;
  else if (body !== null) {
    init.headers = {'Content-Type': 'application/json'};
    init.body = JSON.stringify(body);
  }
  const res = await fetch(base + path, init);
  const out = await res.json();
  if (!res.ok) throw new Error(out.error || 'The request could not be completed.');
  return out;
}

function option(value, label, selected) {
  return '<option value="' + escapeHTML(value) + '"' + (selected === value ? ' selected' : '') + '>' + escapeHTML(label) + '</option>';
}
function field(label, key, type = 'text', params = '') {
  return '<label class="field">' + label + '<input name="' + key + '" type="' + type + '" ' + params + '></label>';
}
function select(label, key, options) {
  return '<label class="field">' + label + '<select name="' + key + '">' + options.join('') + '</select></label>';
}
function btn(label, action, rest = '', kind = '') {
  return '<button type="button" class="' + kind + '" data-action="' + action + '" ' + rest + '>' + escapeHTML(label) + '</button>';
}
function dataID(id) { return 'data-id="' + escapeHTML(id) + '"'; }
function download(label, path) {
  return '<a class="download" href="' + base + path + '">' + label + '</a>';
}
function updatePart(part) {
  state.part = part;
  state.parts = [part, ...state.parts.filter(entry => entry.id !== part.id)];
  render();
}

function stage(html, placeholder = false) {
  return '<div class="stage' + (placeholder ? ' placeholder' : '') + '">' + html + '</div>';
}
function captureImage(id, mode) {
  return base + capturePath(id) + '/image?view=' + mode + '&revision=' + state.part.revision;
}

function stageCapture() {
  if (!state.capture) return stage('Add a photograph to begin.', true);
  const mode = state.marks ? 'marks' : 'plane';
  return stage('<img src="' + captureImage(state.capture, mode) + '" alt="Registered inspection photograph">');
}

function renderParts() {
  q('#part-count').textContent = state.parts.length;
  q('#parts').innerHTML = state.parts.map(item => '<button class="part' + (state.part?.id === item.id ? ' active' : '') +
    '" data-action="choose" ' + dataID(item.id) + '>' + escapeHTML(item.name) + '<small>' +
    escapeHTML(item.lot || 'No site reference') + '</small></button>').join('');
}

function capturePanel() {
  const selected = state.part.captures.find(item => item.id === state.capture);
  const label = selected ? 'Registration ' + (selected.corners ? 'saved' : 'needed') : '';
  return '<div class="grid-main"><section class="card"><div class="action-row">' +
    (selected ? btn('Register corners', 'register', dataID(selected.id), 'primary') +
      btn(state.marks ? 'Hide marks' : 'Show marks', 'toggle-marks') +
      download('Original file', capturePath(selected.id) + '/source') : btn('Add photo', 'add-photo', '', 'primary')) +
    (label ? '<small>' + label + '</small>' : '') + '</div>' + stageCapture() +
    '</section><section class="card"><div class="action-row"><h2>Photographs</h2>' + btn('Add photo', 'add-photo') + '</div>' +
    state.part.captures.map(item => '<div class="list-item"><div><strong>' + escapeHTML(item.name) + '</strong><small>' +
      escapeHTML(state.config.roles[item.role]) + ' · ' + (item.corners ? 'Registered' : 'Unregistered') +
      '</small></div>' + btn('View', 'pick-photo', dataID(item.id)) + '</div>').join('') + '</section></div>';
}

function marksPanel() {
  return '<div class="grid-main"><section class="card"><div class="action-row"><h2>Marked inspection plane</h2>' +
    btn(state.marks ? 'Hide marks' : 'Show marks', 'toggle-marks') + '</div>' + stageCapture() +
    '</section><section class="card"><div class="action-row"><h2>Sampling marks</h2>' + btn('Draw mark', 'add-mark', '', 'primary') +
    '</div>' + state.part.marks.map(item => '<div class="list-item"><div><strong>' + escapeHTML(item.name) + '</strong><small>' +
      escapeHTML(state.config.marks[item.purpose]) + ' · ' + item.points.length + ' points</small></div>' +
      btn('Remove', 'remove-mark', dataID(item.id), 'ghost') + '</div>').join('') + '</section></div>';
}

function chooseMarks(label, fieldName, purpose, fallback = '') {
  return select(label, fieldName, [option('', fallback || 'Choose a mark', ''),
    ...markRows(purpose).map(item => option(item.id, item.name, ''))]);
}

function toolFields() {
  const threshold = (label, start) => field(label, 'threshold', 'number', 'required min=".02" max="1.5" step=".01" value="' + start + '"');
  const area = field('Minimum area (mm²)', 'minimum_mm2', 'number', 'required min="1" max="100000" step="1" value="30"');
  const toolMode = state.mode;
  if (toolMode === 'outline') return threshold('Panel light threshold', '.32');
  if (toolMode === 'holes') return field('Chroma limit', 'threshold', 'number', 'required min="1" max="100" step="1" value="14"') + area;
  if (toolMode === 'scuffs') return threshold('Local contrast', '.14') +
    field('Background radius (mm)', 'radius_mm', 'number', 'required min="1" max="100" step="1" value="14"') + area;
  if (toolMode === 'return') {
    const tolerance = (label, key) => field(label, key, 'number', 'required min=".001" max="1" step=".01" value=".15"');
    const schemes = [['auto', 'Auto: check both, adopt one scale'], ['common', 'Common reference across the whole photo'],
      ['split', 'Side-specific references; middle band left unresolved']];
    return '<div class="field-group"><h3>Left controls</h3>' +
      chooseMarks('Left sound return', 'reference', 'reference') + chooseMarks('Left dark reference', 'dark', 'dark') +
      chooseMarks('Left known-good check film', 'check_left', 'check') + tolerance('Left check max deviation', 'tolerance_left') +
      '</div><div class="field-group"><h3>Right controls</h3>' +
      chooseMarks('Right sound return', 'reference_right', 'reference') + chooseMarks('Right dark reference', 'dark_right', 'dark') +
      chooseMarks('Right known-good check film', 'check_right', 'check') + tolerance('Right check max deviation', 'tolerance_right') +
      '</div>' + select('Scale scheme', 'scale_scheme', schemes.map(([value, label]) => option(value, label, 'auto'))) +
      threshold('Relative return threshold', '.62');
  }
  if (toolMode === 'weak') {
    const scales = state.listing.filter(item => item.mode === 'return' && item.scale);
    const scaleOptions = [option('', 'Mark controls directly (no frozen scale)', ''),
      ...scales.map(item => option(item.id, item.title + ' · rev ' + item.revision, ''))];
    return '<div id="scale-fields">' + select('Frozen return scale', 'scale_reading', scaleOptions) + '</div>' +
      '<div id="control-fields" hidden>' + chooseMarks('Sound return', 'reference', 'reference') +
      chooseMarks('Dark reference', 'dark', 'dark') + '</div>' +
      threshold('Relative return threshold', '.62') + area;
  }
  if (toolMode === 'contrast') return chooseMarks('Letter face', 'letter', 'letter') +
    chooseMarks('Letter background', 'background', 'background');
  if (toolMode === 'profile') return btn('Mark transect', 'mark-survey') +
    '<small id="survey-count">' + state.survey.length + ' points marked</small>';
  return '';
}

function readingForm() {
  const shots = state.part.captures;
  const opts = Object.entries(state.config.tools).map(([key, value]) => option(key, value[0], state.mode));
  const captions = list => list.map(item => option(item.id, item.name, state.capture));
  const pair = state.mode === 'coverage';
  return '<section class="card"><h2>Measure inspection</h2><p>' + escapeHTML(tool(state.mode)[1]) + '</p><form class="form" id="reading-form">' +
    select('Measurement', 'mode', opts) + select('Photograph', 'capture', captions(shots)) +
    (pair ? select('Comparison photograph', 'other', [option('', 'Choose comparison', ''), ...captions(shots.filter(item => item.id !== state.capture))]) : '') +
    chooseMarks('Inspection region', 'region', 'inspect', 'Whole inspected plane') + toolFields() +
    '<button class="primary" type="submit"' + (shots.length ? '' : ' disabled') + '>Save measurement</button></form></section>';
}
function scalePanel(scale) {
  if (!scale) return '';
  const checks = scale.checks?.length ? '<table><thead><tr><th>Check film</th><th>Observed</th><th>Max deviation</th><th>Actual deviation</th><th>Result</th></tr></thead><tbody>' +
    scale.checks.map(row => '<tr><td>' + escapeHTML(row.name) + '</td><td>' + fmt(row.observed_return) + '</td><td>' +
      fmt(row.tolerance) + '</td><td>' + fmt(row.deviation) + '</td><td>' + (row.passes ? 'Within tolerance' : 'Outside tolerance') + '</td></tr>').join('') +
    '</tbody></table>' : '<p>No check film marked; the scale was not independently validated.</p>';
  const candidates = scale.candidates?.length > 1 ? '<div class="table"><table><thead><tr><th>Scheme</th><th>Worst check deviation</th><th>Decision</th></tr></thead><tbody>' +
    scale.candidates.map(candidate => '<tr><td>' + escapeHTML(title(candidate.scheme)) + '</td><td>' +
      fmt(candidate.worst_deviation) + '</td><td>' + (candidate.accepted ? (candidate.scheme === scale.scheme ? 'Adopted' : 'Passed') : 'Failed check') +
      '</td></tr>').join('') + '</tbody></table></div>' : '';
  const gap = scale.gap ? '<p>Side-specific scale: the middle band at x ' + scale.gap.join(' to ') +
    ' cannot be assigned to either side and stays unresolved.</p>' : '';
  const range = scale.observed_range ? '<p>Observed scale range on this capture: ' +
    Object.entries(scale.observed_range).map(([key, value]) => escapeHTML(key) + ' ' + fmt(value)).join(' · ') + '</p>' : '';
  return '<div class="scale-panel"><h3>Frozen return scale · ' + escapeHTML(title(scale.scheme)) + '</h3>' +
    gap + range + candidates + '<div class="table">' + checks + '</div>' +
    '<p class="muted">Check film validates the scale but is never used as a control. Weak return windows reopen this frozen scale; later thresholds or measurements cannot change it.</p></div>';
}
function report(result) {
  if (!result) return '<section class="card"><h2>Measurement preview</h2>' + stageCapture() + '</section>';
  const link = '/readings/' + result.id;
  const headers = [...new Set(result.rows.flatMap(row => Object.keys(row)))];
  const metrics = Object.entries(result.summary).map(([key, value]) => '<div class="metric"><small>' + escapeHTML(title(key)) +
    '</small>' + escapeHTML(fmt(value)) + '</div>').join('');
  return '<section class="card"><h2>' + escapeHTML(result.title) + '</h2><p>Saved at revision ' + result.revision +
    ' · ' + escapeHTML(result.captures.map(item => item.name).join(' · ')) + '</p><div class="metrics">' + metrics + '</div>' +
    scalePanel(result.scale) +
    (result.summary.scale_source ? '<p class="muted">Weak patches read through the frozen scale from reading ' +
      escapeHTML(result.summary.scale_source) + '.</p>' : '') +
    stage('<img src="' + base + link + '/image" alt="Measurement overlay">') + '<div class="table">' +
    (headers.length ? '<table><thead><tr>' + headers.map(key => '<th>' + escapeHTML(title(key)) + '</th>').join('') +
      '</tr></thead><tbody>' + result.rows.map(row => '<tr>' + headers.map(key => '<td>' + escapeHTML(key === 'outline' && Array.isArray(row[key]) ? row[key].length + ' boundary points' : fmt(row[key])) + '</td>').join('') +
      '</tr>').join('') + '</tbody></table>' : '<p>No matching features in the observed portion.</p>') +
    '</div><div class="action-row">' + download('Readings CSV', link + '/csv') + download('Inspection ZIP', link + '/packet') + '</div></section>';
}
function recordPanel() {
  return '<div class="grid-main">' + report(state.result) + '<section class="card"><h2>Saved inspections</h2>' +
    (state.listing.length ? state.listing.map(result => '<div class="list-item"><div><strong>' + escapeHTML(result.title) +
      '</strong><small>Revision ' + result.revision + ' · ' + escapeHTML(result.captures.map(item => item.name).join(' + ')) +
      '</small></div>' + btn('Open', 'open-reading', dataID(result.id)) + '</div>').join('') : '<p>Save a measurement from Measure to retain its input and overlay.</p>') +
    '</section></div>';
}
function render() {
  renderParts();
  const work = q('#workbench');
  if (!state.part) {
    work.innerHTML = '<section class="card empty"><h1>Read a sign face</h1><p>Register day and night captures to one panel. Measure visible return, marks and lettering before filing your inspection.</p>' +
      btn('New inspection', 'new', '', 'primary') + '</section>';
    return;
  }
  const item = state.part;
  const pages = ['Captures', 'Sampling marks', 'Measure', 'Saved inspections'];
  const nav = '<div class="tabbar">' + pages.map(name => btn(name, 'tab', 'data-tab="' + name + '"', state.tab === name ? 'active' : '')).join('') + '</div>';
  const main = state.tab === 'Captures' ? capturePanel() : state.tab === 'Sampling marks' ? marksPanel() :
    state.tab === 'Measure' ? '<div class="grid-main">' + report(state.result) + readingForm() + '</div>' : recordPanel();
  work.innerHTML = '<div class="topline"><div><h1>' + escapeHTML(item.name) + '</h1><p>' + escapeHTML(item.lot ? item.lot + ' · ' : '') +
    item.width_mm + ' × ' + item.height_mm + ' mm · revision ' + item.revision + '</p></div>' +
    (item.synthetic ? '<span class="chip">Synthetic sample</span>' : '') + '</div>' + nav + main;
}

async function loadPart(id, selected = null) {
  const sequence = ++navigation;
  const [part, readings] = await Promise.all([api('/parts/' + id), api('/parts/' + id + '/readings')]);
  if (sequence !== navigation) return;
  state.capture = part.captures.find(item => item.id === selected)?.id ?? part.captures[0]?.id ?? null;
  state.tab = 'Captures';
  state.survey = [];
  state.marks = false;
  state.result = null;
  state.listing = readings.items;
  updatePart(part);
  history.replaceState(null, '', '#inspection-' + id);
}

function modal(titleText, inner, accept, operation) {
  dialog.innerHTML = '<div class="dialog-head"><h2>' + escapeHTML(titleText) + '</h2><button type="button" id="close-dialog">Close</button></div>' +
    '<form class="form">' + inner + '<button type="submit" class="primary">' + escapeHTML(accept) + '</button></form>';
  q('#close-dialog', dialog).onclick = () => dialog.close();
  const form = q('form', dialog);
  form.onsubmit = async event => {
    event.preventDefault();
    const submit = q('button[type=submit]', form);
    submit.disabled = true;
    try {
      await operation(new FormData(form));
      dialog.close();
    } catch (error) {
      notice(error.message, true);
    } finally {
      submit.disabled = false;
    }
  };
  dialog.showModal();
}

function drawPanel(hint) {
  return '<p>' + hint + '</p><div class="draw-stage"><img id="draw-image" alt="Photograph to mark"><canvas id="draw-canvas"></canvas></div>' +
    '<div class="action-row"><button type="button" id="draw-reset">Clear points</button><button type="button" id="draw-undo">Undo point</button>' +
    '<small id="draw-count"></small></div>';
}
function drawing(url, max, initial = []) {
  const stage = q('.draw-stage', dialog);
  const photo = q('#draw-image', stage);
  const canvas = q('#draw-canvas', stage);
  const ctx = canvas.getContext('2d');
  const positions = initial.map(pair => [...pair]);
  function paint() {
    canvas.width = Math.max(1, Math.round(photo.clientWidth * devicePixelRatio));
    canvas.height = Math.max(1, Math.round(photo.clientHeight * devicePixelRatio));
    ctx.lineWidth = devicePixelRatio * 1.5;
    ctx.strokeStyle = '#8afccc';
    ctx.fillStyle = '#8afccc';
    ctx.beginPath();
    positions.forEach(([u, v], index) => ctx[index ? 'lineTo' : 'moveTo'](u * canvas.width, v * canvas.height));
    ctx.stroke();
    for (const [u, v] of positions) {
      ctx.beginPath();
      ctx.arc(u * canvas.width, v * canvas.height, devicePixelRatio * 4, 0, Math.PI * 2);
      ctx.fill();
    }
    q('#draw-count', dialog).textContent = positions.length + ' points marked';
  }
  photo.onload = paint;
  canvas.onclick = event => {
    if (positions.length >= max) return;
    const bounds = canvas.getBoundingClientRect();
    positions.push([(event.clientX - bounds.left) / bounds.width, (event.clientY - bounds.top) / bounds.height]);
    paint();
  };
  q('#draw-reset', dialog).onclick = () => { positions.length = 0; paint(); };
  q('#draw-undo', dialog).onclick = () => { positions.pop(); paint(); };
  photo.src = url;
  paint();
  return positions;
}

function newPart() {
  modal('New inspection', field('Panel name', 'name', 'text', 'required maxlength="96"') +
    field('Site reference', 'lot', 'text', 'maxlength="60"') +
    '<div class="field-grid">' + field('Calibration width (mm)', 'width_mm', 'number', 'required min="25" max="10000" step=".1" value="760"') +
    field('Calibration height (mm)', 'height_mm', 'number', 'required min="25" max="10000" step=".1" value="440"') + '</div>',
    'Create inspection', async data => loadPart((await api('/parts', 'POST', Object.fromEntries(data))).id));
}
function addPhoto() {
  const roles = Object.entries(state.config.roles).map(([key, value]) => option(key, value, 'day'));
  modal('Add inspection photograph', field('Photograph', 'file', 'file', 'required accept=".png,.jpeg,.jpg,.tiff,.tif"') +
    select('Photograph role', 'role', roles), 'Import photograph', async data => {
    data.set('revision', state.part.revision);
    const part = await api(partPath() + '/captures', 'POST', data);
    state.capture = part.captures.at(-1).id;
    updatePart(part);
  });
}
function register(id) {
  const current = state.part.captures.find(item => item.id === id);
  modal('Register panel corners', drawPanel('Mark upper left, upper right, lower right and lower left on the same measured rectangle.'),
    'Save registration', async () => updatePart(await api(capturePath(id) + '/registration', 'PUT', {revision: state.part.revision, corners: coords})));
  const coords = drawing(captureImage(id, 'raw'), 4, current.corners || []);
}
function addMark() {
  if (!state.capture) throw new Error('Add a capture before marking the inspection plane.');
  modal('Draw sampling mark', field('Name', 'name', 'text', 'required maxlength="96"') +
    select('Purpose', 'purpose', Object.entries(state.config.marks).map(([key, value]) => option(key, value, 'inspect'))) +
    drawPanel('Mark the region boundary in order.'),
    'Save mark', async data => {
      const mark = Object.fromEntries(data);
      state.marks = true;
      updatePart(await api(partPath() + '/marks', 'POST', {...mark, revision: state.part.revision, points: coords}));
    });
  const coords = drawing(captureImage(state.capture, 'plane'), 40);
}
function measureRoute() {
  if (!state.capture) throw new Error('Choose a photograph before marking the transect.');
  modal('Mark transect', drawPanel('Mark the two ends of the transect.'), 'Use these points', async () => {
    if (coords.length !== 2) throw new Error('Mark both endpoints.');
    state.survey = coords;
    q('#survey-count').textContent = coords.length + ' points marked';
  });
  const coords = drawing(captureImage(state.capture, 'plane'), 2, state.survey);
}
function verifyPacket() {
  modal('Verify an inspection packet', field('Inspection ZIP', 'file', 'file', 'required accept=".zip"'), 'Verify contents', async data => {
    const result = await api('/verify', 'POST', data);
    notice('Verified ' + result.title + ' · ' + result.verified.length + ' files');
  });
}
async function measure(submit) {
  const data = new FormData(submit);
  const names = ['capture', 'mode', 'other', 'region'];
  const args = Object.fromEntries(names.filter(name => data.has(name)).map(name => [name, data.get(name)]));
  const options = {};
  for (const [key, value] of data) if (!names.includes(key)) options[key] = key === 'closed' ? true : value;
  if (args.mode === 'profile') options.points = state.survey;
  const partID = state.part.id;
  const result = await api(partPath() + '/readings', 'POST', {...args, options, revision: state.part.revision});
  if (state.part?.id !== partID) return;
  state.result = result;
  state.listing = [result, ...state.listing];
  render();
}
async function action(actionName, dataset) {
  const id = dataset.id;
  if (actionName === 'choose') await loadPart(id);
  else if (actionName === 'new') newPart();
  else if (actionName === 'tab') {
    state.tab = dataset.tab;
    if (state.tab === 'Sampling marks') state.marks = true;
    render();
  } else if (actionName === 'register') register(id);
  else if (actionName === 'add-photo') addPhoto();
  else if (actionName === 'toggle-marks') { state.marks = !state.marks; render(); }
  else if (actionName === 'pick-photo') { state.capture = id; state.survey = []; render(); }
  else if (actionName === 'add-mark') addMark();
  else if (actionName === 'remove-mark') {
    modal('Remove this mark?', '<p>Earlier measurements retain a copy of the mark.</p>', 'Remove mark',
      async () => updatePart(await api(partPath() + '/marks/' + id, 'DELETE', {revision: state.part.revision})));
  } else if (actionName === 'mark-survey') measureRoute();
  else if (actionName === 'open-reading') { state.result = await api('/readings/' + id); render(); }
}

async function guard(call, target) {
  if (target) target.disabled = true;
  try { await call(); }
  catch (error) { notice(error.message, true); }
  finally { if (target) target.disabled = false; }
}

document.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (target) guard(() => action(target.dataset.action, target.dataset), target);
});
document.addEventListener('submit', event => {
  if (event.target.id !== 'reading-form') return;
  event.preventDefault();
  guard(() => measure(event.target), q('button[type=submit]', event.target));
});
document.addEventListener('change', event => {
  if (event.target.form?.id !== 'reading-form') return;
  if (event.target.name === 'mode') {
    state.mode = event.target.value;
    state.survey = [];
    render();
  }
  if (event.target.name === 'capture' && event.target.value !== state.capture) {
    state.capture = event.target.value;
    state.survey = [];
    render();
  }
  if (event.target.name === 'scale_reading') {
    const frozen = Boolean(event.target.value);
    q('#control-fields').hidden = frozen;
  }
});
q('#new-part').onclick = () => guard(newPart);
q('#open-verify').onclick = () => guard(verifyPacket);
q('#training').onclick = event => guard(async () => loadPart((await api('/training', 'POST', {})).id), event.currentTarget);
guard(async () => {
  const [config, parts] = await Promise.all([api('/config'), api('/parts')]);
  state.config = config;
  state.parts = parts.items;
  const id = location.hash.match(/^#inspection-([a-f0-9]{20})$/)?.[1];
  if (id && parts.items.some(item => item.id === id)) await loadPart(id);
  else render();
});
