// Miau 3D Studio — interface
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const api = async (path, opts = {}) => {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Erro ${r.status}`);
  return body;
};
const fileUrl = (id, f) => `/files/${id}/${f}?t=${Date.now()}`;

const MODES = {
  image: { title: 'Imagem → 3D', hint: 'Envie uma foto ou desenho de um objeto. O fundo é removido automaticamente.' },
  multiview: { title: 'Várias fotos → 3D', hint: 'Fotos do mesmo objeto de lados diferentes (frente obrigatória). Mais fotos, forma mais fiel.' },
  text: { title: 'Texto → 3D', hint: 'Descreva um objeto. O app cria uma imagem de referência e depois o modelo 3D.' },
};
let mode = 'image';
let currentJob = null;
let currentItem = null;

// ---------- navegação ----------
function show(view) {
  $$('.nav').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $('#create').hidden = !MODES[view];
  $('#library').hidden = view !== 'library';
  $('#detail').hidden = view !== 'detail';
  if (MODES[view]) setMode(view);
  if (view === 'library') loadLibrary();
}
function setMode(m) {
  mode = m;
  $('#ctitle').textContent = MODES[m].title;
  $('#chint').textContent = MODES[m].hint;
  $$('.mode').forEach(el => (el.hidden = !el.classList.contains(`mode-${m}`)));
  $('#projcheck').hidden = m === 'text';
}
$$('.nav').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));

// ---------- áreas de soltar imagem ----------
$$('.drop').forEach(drop => {
  const input = drop.querySelector('input');
  const preview = () => {
    const f = input.files[0];
    drop.classList.toggle('filled', !!f);
    drop.style.backgroundImage = f ? `url(${URL.createObjectURL(f)})` : '';
  };
  input.addEventListener('change', preview);
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; preview(); }
  });
});

// ---------- gerar ----------
$('#form').addEventListener('submit', async e => {
  e.preventDefault();
  const form = $('#form');
  const fd = new FormData();
  fd.append('mode', mode);
  fd.append('name', form.name.value);
  fd.append('quality', form.quality.value);
  fd.append('seed', form.seed.value || '1234');
  fd.append('texture', form.texture.checked ? 'true' : 'false');
  fd.append('project', form.project.checked && mode !== 'text' ? 'true' : 'false');
  $('#formerr').hidden = true;
  try {
    if (mode === 'image') {
      if (!form.image.files[0]) throw new Error('Escolha uma imagem.');
      fd.append('image', form.image.files[0]);
    } else if (mode === 'multiview') {
      if (!form.front.files[0]) throw new Error('A foto de frente é obrigatória.');
      for (const k of ['front', 'left', 'back', 'right']) if (form[k].files[0]) fd.append(k, form[k].files[0]);
    } else {
      if (!form.prompt.value.trim()) throw new Error('Escreva uma descrição.');
      fd.append('prompt', form.prompt.value);
    }
    $('#go').disabled = true;
    const { id } = await api('/api/generate', { method: 'POST', body: fd });
    currentJob = id;
    $('#jobname').textContent = form.name.value || MODES[mode].title;
    $('#job').hidden = false;
    $('#job').className = 'job';
    $('#mv').hidden = true;
    $('#empty').hidden = false;
    $('#stageactions').hidden = true;
    pollJob(id);
  } catch (err) {
    $('#formerr').textContent = err.message;
    $('#formerr').hidden = false;
    $('#go').disabled = false;
  }
});

async function pollJob(id) {
  if (id !== currentJob) return;
  let j;
  try { j = await api(`/api/jobs/${id}`); } catch { return setTimeout(() => pollJob(id), 2000); }
  const pct = Math.round((j.progress || 0) * 100);
  $('#jobpct').textContent = `${pct}%`;
  $('#jobbar').style.width = `${pct}%`;
  $('#jobmsg').textContent = j.message || '';
  if (j.status === 'done') {
    $('#job').classList.add('done');
    const r = j.result;
    $('#jobmsg').textContent = `Pronto em ${fmtTime(r.seconds)} · ${r.faces.toLocaleString('pt-BR')} faces`
      + (r.projected ? ' · fotos projetadas' : r.projection_error ? ` · projeção falhou: ${r.projection_error}` : '');
    $('#mv').src = fileUrl(id, r.projected || r.model);
    $('#mv').hidden = false;
    $('#empty').hidden = true;
    $('#stageactions').hidden = false;
    $('#go').disabled = false;
    return;
  }
  if (j.status === 'error') {
    $('#job').classList.add('error');
    $('#go').disabled = false;
    return;
  }
  setTimeout(() => pollJob(id), 1500);
}
$('#openitem').addEventListener('click', () => openItem(currentJob));
const fmtTime = s => (s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.round(s)} s`);

// ---------- biblioteca ----------
async function loadLibrary() {
  const items = await api('/api/library');
  const grid = $('#grid');
  grid.innerHTML = '';
  if (!items.length) grid.innerHTML = '<p class="hint">Nenhum modelo ainda. Crie o primeiro em "Imagem → 3D".</p>';
  for (const it of items) {
    const card = document.createElement('div');
    card.className = 'card';
    const badge = it.status === 'done' ? '' : it.status === 'error'
      ? '<span class="badge err">erro</span>' : '<span class="badge run">gerando</span>';
    const date = new Date(it.created).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    card.innerHTML = `<div class="thumb" style="background-image:url('${fileUrl(it.id, 'referencia.png')}')">${badge}</div>
      <div class="meta"><b></b><small>${date}</small></div>`;
    card.querySelector('b').textContent = it.name;
    card.addEventListener('click', () => it.status === 'done' ? openItem(it.id) : null);
    card.title = it.error || '';
    grid.appendChild(card);
  }
}

// ---------- detalhe ----------
async function openItem(id) {
  const it = await api(`/api/library/${id}`);
  currentItem = it;
  show('detail');
  $('#dname').textContent = it.name;
  const r = it.result || {};
  const modeName = MODES[it.mode]?.title || it.mode;
  $('#dinfo').textContent = `${modeName} · ${(r.faces || 0).toLocaleString('pt-BR')} faces · ${fmtTime(r.seconds || 0)}`
    + (it.params?.prompt ? ` · “${it.params.prompt}”` : '');
  $('#dref').src = fileUrl(id, 'referencia.png');
  $$('.viewtoggle [data-show=model]')[0].hidden = r.model !== 'modelo.glb';
  $$('.viewtoggle [data-show=projected]')[0].hidden = !r.projected;
  setShow(r.projected ? 'projected' : r.model === 'modelo.glb' ? 'model' : 'shape');
  $('#projbox').hidden = !(['image', 'multiview'].includes(it.mode) && r.model === 'modelo.glb');
  $('#project').textContent = r.projected ? 'Projetar de novo' : 'Projetar fotos originais';
  $('#projmsg').textContent = r.projection ? projSummary(r.projection) : '';
  renderExports(it.exports);
  $('#toolmsg').textContent = '';
}
const VIEW_FILES = { projected: 'modelo_fotos.glb', model: 'modelo.glb', shape: 'forma.glb' };
const VIEW_NAMES = { front: 'frente', left: 'esquerda', back: 'costas', right: 'direita' };
function setShow(which) {
  $$('.viewtoggle [data-show]').forEach(b => b.classList.toggle('active', b.dataset.show === which));
  $('#dmv').src = fileUrl(currentItem.id, VIEW_FILES[which]);
}
function projSummary(p) {
  const parts = Object.entries(p.fotos || {}).map(([v, r]) =>
    `${VIEW_NAMES[v] || v}: ${r.usada ? `usada (encaixe ${Math.round(r.encaixe * 100)}%)` : `ignorada, não encaixou (${Math.round(r.encaixe * 100)}%)`}`);
  return parts.join(' · ');
}
$('#project').addEventListener('click', async () => {
  const id = currentItem.id;
  $('#project').disabled = true;
  $('#projmsg').textContent = 'Projetando as fotos… (cerca de 1 minuto)';
  const tick = setInterval(async () => {
    try { const j = await api(`/api/jobs/${id}:fotos`); if (j.message) $('#projmsg').textContent = `${Math.round(j.progress * 100)}% · ${j.message}`; } catch {}
  }, 1500);
  try {
    const report = await api(`/api/library/${id}/project`, { method: 'POST' });
    clearInterval(tick);
    if (currentItem?.id === id) await openItem(id);
    $('#projmsg').textContent = projSummary(report);
  } catch (err) {
    clearInterval(tick);
    $('#projmsg').textContent = err.message;
  } finally {
    $('#project').disabled = false;
  }
});
$$('.viewtoggle [data-show]').forEach(b => b.addEventListener('click', () => setShow(b.dataset.show)));
$('#wire').addEventListener('click', e => { $('#dmv').classList.toggle('light'); e.target.classList.toggle('active'); });
$('#back').addEventListener('click', () => show('library'));

$('#dname').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } });
$('#dname').addEventListener('blur', async e => {
  const name = e.target.textContent.trim();
  if (currentItem && name && name !== currentItem.name) {
    currentItem = { ...currentItem, ...(await api(`/api/library/${currentItem.id}/rename`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })) };
  }
});

$('#decimate').addEventListener('input', e => ($('#decv').textContent = `${e.target.value}%`));
$('#remesh').addEventListener('change', e => {
  $('#remeshvalwrap').hidden = !e.target.value;
  $('#remeshlabel').textContent = e.target.value === 'quad' ? 'Faces desejadas' : 'Detalhe (resolução)';
  $('#remeshval').value = e.target.value === 'quad' ? 5000 : 128;
});

$('#export').addEventListener('click', async () => {
  const ops = { ground: true };
  const dec = Number($('#decimate').value);
  if (dec < 100) ops.decimate = dec / 100;
  if ($('#remesh').value) ops.remesh = { mode: $('#remesh').value, value: Number($('#remeshval').value) };
  if ($('#height').value) ops.height_cm = Number($('#height').value);
  if ($('#base').checked) ops.base = { height_mm: 3, margin_mm: 5 };
  const source = VIEW_FILES[$('.viewtoggle .active[data-show]')?.dataset.show || 'model'];
  $('#export').disabled = true;
  $('#toolmsg').textContent = 'O Blender está processando…';
  try {
    const r = await api(`/api/library/${currentItem.id}/tool`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format: $('#format').value, ops, source }),
    });
    const i = r.info || {};
    $('#toolmsg').textContent = `Exportado: ${(i.faces || 0).toLocaleString('pt-BR')} faces`
      + (i.size_cm ? ` · ${i.size_cm.map(v => v.toLocaleString('pt-BR')).join(' × ')} cm` : '');
    const it = await api(`/api/library/${currentItem.id}`);
    renderExports(it.exports);
    if (/\.glb$/.test(r.file)) $('#dmv').src = fileUrl(currentItem.id, r.file);
  } catch (err) {
    $('#toolmsg').textContent = err.message;
  } finally {
    $('#export').disabled = false;
  }
});
function renderExports(list) {
  $('#exports').innerHTML = '';
  for (const f of list || []) {
    const d = document.createElement('div');
    d.textContent = `📦 ${f}`;
    $('#exports').appendChild(d);
  }
}
$('#folder').addEventListener('click', () => api(`/api/library/${currentItem.id}/open-folder`, { method: 'POST' }));
$('#del').addEventListener('click', async () => {
  if (!confirm(`Mover "${currentItem.name}" para a lixeira do app?`)) return;
  await api(`/api/library/${currentItem.id}`, { method: 'DELETE' });
  show('library');
});

// ---------- status do motor ----------
async function status() {
  try {
    const s = await api('/api/status');
    const g = $('#gpu');
    if (s.error) g.innerHTML = `<span class="err">Motor com erro:</span><br>${s.error}`;
    else if (!s.ready) g.textContent = 'Carregando o motor de IA…';
    else {
      const e = s.engine || {};
      g.innerHTML = `<span class="dot"></span>${e.gpu || 'GPU'} · ${e.vram_total_gb} GB<br>`
        + (s.busy ? 'Gerando um modelo…' : 'Pronto para gerar')
        + (!s.busy && e.loaded?.length ? '<br><small>Modelos na memória: a próxima sai mais rápido</small>' : '')
        + (s.queue ? ` · ${s.queue} na fila` : '')
        + (e.text_to_3d ? '' : '<br><small>Texto → 3D: modelo ainda baixando</small>');
    }
  } catch { $('#gpu').textContent = 'Sem conexão com o motor'; }
  setTimeout(status, 4000);
}
status();
show('image');
