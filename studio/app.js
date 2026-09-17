const $ = selector => document.querySelector(selector);

let projects = [];
let models = {};
let selected = localStorage.getItem('project');
let view = 'scenes';
let editing = null;
let remixing = null;
let running = false;
let favorites = new Set(JSON.parse(localStorage.getItem('favorites') || '[]'));

const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));

async function api(path, data) {
  const response = await fetch(path, data ? {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  } : {});
  const body = await response.json();
  if (!response.ok) throw Error(body.error || 'Request failed');
  return body;
}

function toast(message) {
  $('#toast').textContent = message;
  $('#toast').style.display = 'block';
  setTimeout(() => $('#toast').style.display = 'none', 4500);
}

function current() {
  return projects.find(project => project.id === selected);
}

function sceneModels() {
  return Object.entries(models).filter(([, model]) => model.workflow === 'scene_generation');
}

function remixModels() {
  return Object.entries(models).filter(([, model]) => ['video_edit', 'motion_transfer'].includes(model.workflow));
}

function quickResolutions() {
  const model = models[$('#quickModel').value];
  if (!model) return;
  $('#quickResolution').replaceChildren(...model.resolutions.map(value => new Option(value, value)));
  $('#quickDuration').disabled = Boolean(model.fixed_duration);
  if (model.fixed_duration) $('#quickDuration').value = model.fixed_duration;
}

function syncQuickControls() {
  const keys = sceneModels().map(([key]) => key);
  if (!keys.length) return;
  const project = current();
  const preferred = project?.settings.model || localStorage.getItem('quickModel') || keys[0];
  $('#quickModel').replaceChildren(...keys.map(key => new Option(models[key].name, key)));
  $('#quickModel').value = models[preferred] ? preferred : keys[0];
  quickResolutions();
  if (project && $('#quickModel').value === project.settings.model) {
    $('#quickResolution').value = project.settings.resolution;
    $('#quickDuration').value = project.settings.duration;
  }
}

async function load() {
  const result = await api('/api/projects');
  projects = result.projects;
  models = result.models;
  if (!current()) selected = projects[0]?.id;
  $('#connectionText').textContent = result.connected ? 'Credential connected' : 'Add token to local .env';
  $('#lamp').className = result.connected ? 'connected' : '';
  syncQuickControls();
  render();
}

function changeView(tab) {
  view = tab;
  document.querySelectorAll('[data-tab]').forEach(button => button.classList.toggle('active', button.dataset.tab === view));
  $('#breadcrumb').textContent = {
    scenes: 'Storyboard', assets: 'Asset library', favorites: 'Favorites',
    exports: 'Finished films', history: 'Activity'
  }[view];
  render();
  if (view === 'history') history();
}

function render() {
  const project = current();
  $('#projects').replaceChildren(...projects.map(item => {
    const button = document.createElement('button');
    button.textContent = item.name;
    button.className = item.id === selected ? 'selected' : '';
    button.onclick = () => {
      selected = item.id;
      localStorage.setItem('project', selected);
      syncQuickControls();
      render();
    };
    return button;
  }));

  $('#title').textContent = project?.name || 'Make every scene count.';
  $('#subtitle').textContent = project
    ? `${project.scenes.length} scenes · ${project.scenes.filter(scene => scene.video).length} clips ready · A complete story, one moment at a time.`
    : 'Create your first storyboard to get started.';
  $('#projectLabel').textContent = view === 'scenes' ? 'YOUR STORYBOARD' : view.toUpperCase();
  $('#grid').hidden = view === 'history';
  $('#activity').hidden = view !== 'history';
  $('#build').disabled = !project || running || project.scenes.some(scene => !scene.video);
  $('#generate').disabled = !project || running || !project.scenes.some(scene => !scene.video);
  $('#settingsToggle').disabled = !project;
  $('#summary').textContent = project
    ? `${project.scenes.filter(scene => !scene.video).length} scenes waiting for animation`
    : 'Create a project to begin';
  $('#cost').textContent = project ? `$${project.estimate.toFixed(2)} estimate` : '$0.00';
  if (project) {
    if (!$('#quickModel').value) $('#quickModel').value = project.settings.model;
    $('#quickDuration').value = project.settings.duration;
    $('#progress').textContent = `${project.scenes.filter(scene => scene.video).length}/${project.scenes.length} ready`;
  }
  if (view === 'history') return;

  const query = $('#search').value.toLowerCase();
  const filter = $('#filter').value;
  let entries = [];
  if (view === 'exports') {
    entries = projects.filter(item => item.video).map(item => ({
      project: item,
      scene: {shot_id: 'final', video: item.video, scene_description: 'Finished captioned export'},
      index: 0
    }));
  } else {
    for (const item of view === 'scenes' ? (project ? [project] : []) : projects) {
      item.scenes.forEach((scene, index) => entries.push({project: item, scene, index}));
    }
  }
  entries = entries.filter(({project: item, scene}) => (
    view !== 'favorites' || favorites.has(`${item.id}/${scene.shot_id}`)
  ) && (
    view !== 'assets' || scene.image || scene.video
  ) && (
    !query || `${scene.scene_description} ${item.name} ${scene.shot_id}`.toLowerCase().includes(query)
  ) && (
    filter !== 'ready' || scene.video
  ) && (
    filter !== 'missing' || !scene.video
  ) && (
    filter !== 'images' || scene.image
  ));

  $('#grid').innerHTML = entries.length ? entries.map(({project: item, scene, index}) => {
    const key = `${item.id}/${scene.shot_id}`;
    const label = scene.shot_id === 'final' ? 'FINAL CUT' : `${String(index + 1).padStart(2, '0')} / ${item.scenes.length}`;
    const media = scene.image
      ? `<img src="${esc(scene.image)}" loading="lazy" alt="Scene ${index + 1} start frame">`
      : scene.video
        ? `<video src="${esc(scene.video)}#t=0.1" preload="metadata" muted></video>`
        : '<div class="empty"><span class="icon">＋</span><span>Add a start frame</span></div>';
    return `<article class="scene" data-project="${esc(item.id)}" data-shot="${esc(scene.shot_id)}">
      <div class="media" data-action="${scene.video ? 'preview' : 'edit'}">${media}
        <span class="badge">${label}</span>
        <button class="star ${favorites.has(key) ? 'on' : ''}" data-action="favorite" aria-label="Favorite scene">${favorites.has(key) ? '★' : '☆'}</button>
        ${scene.video ? '<span class="play">▶</span>' : ''}
      </div>
      <div class="scene-info"><div class="row"><strong>${scene.shot_id === 'final' ? esc(item.name) : `Scene ${String(index + 1).padStart(2, '0')}`}</strong><small>${scene.video ? '● Ready' : scene.image ? 'Frame ready' : 'Needs frame'}</small></div>
        <p>${esc(scene.scene_description || 'Give this moment an action and a place.')}</p>
        <div class="scene-actions">${scene.shot_id !== 'final' ? '<button data-action="edit">Edit scene ↗</button>' : ''}${scene.video && scene.shot_id !== 'final' ? '<button data-action="remix">Remix ↗</button>' : ''}${scene.video ? `<a href="${esc(scene.video)}" download>Download ↓</a>` : ''}${!scene.video && scene.image ? `<a href="${esc(scene.image)}" download>Image ↓</a>` : ''}</div>
      </div>
    </article>`;
  }).join('') : `<div class="blank">${view === 'favorites' ? 'Your favorite scenes will appear here. Tap ☆ to save one.' : view === 'exports' ? 'Your finished videos will appear here after assembly.' : 'No scenes match this view. Create a project or change your filters.'}</div>`;
}

function showViewer(url) {
  const video = document.createElement('video');
  video.src = url;
  video.controls = true;
  video.autoplay = true;
  $('#viewerContent').replaceChildren(video);
  $('#viewer').showModal();
}

function openEditor(project, scene) {
  if (scene.shot_id === 'final') return;
  editing = {project: project.id, shot: scene.shot_id};
  $('#sceneNumber').textContent = `SCENE ${project.scenes.indexOf(scene) + 1}`;
  $('#prompt').value = scene.scene_description || '';
  $('#narration').value = scene.narration || '';
  $('#camera').value = scene.camera_move || '';
  $('#editorStatus').textContent = scene.video ? 'Existing clip is kept. Save changes for future generations.' : '';
  $('#preview').innerHTML = scene.image ? `<img src="${esc(scene.image)}?v=${Date.now()}" alt="Start frame">` : 'Portrait start frame';
  $('#editor').showModal();
}

function updateRemixControls() {
  if (!remixing) return;
  const model = models[$('#remixModel').value];
  if (!model) return;
  const scene = remixing.scene;
  const sourceDuration = Math.round(Number(scene.duration_sec) || 4);
  const previousResolution = $('#remixResolution').value;
  $('#remixResolution').replaceChildren(...model.resolutions.map(value => new Option(value, value)));
  $('#remixResolution').value = model.resolutions.includes(previousResolution)
    ? previousResolution : (model.default_resolution || model.resolutions[0]);
  const minimum = model.min_duration || 2;
  const maximum = model.max_duration || 60;
  const duration = Math.max(minimum, Math.min(maximum, sourceDuration));
  $('#remixDuration').min = minimum;
  $('#remixDuration').max = maximum;
  $('#remixDuration').value = duration;
  const cost = model.rates[$('#remixResolution').value] * duration;
  $('#remixPromptLabel').hidden = model.workflow === 'motion_transfer';
  $('#remixReferenceLabel').hidden = model.workflow !== 'motion_transfer';
  $('#remixEstimate').textContent = `${model.name} · ${duration}s source · estimated $${cost.toFixed(3)} · backed up before replacement`;
  $('#remixHelp').textContent = model.workflow === 'motion_transfer'
    ? 'Wan 2.2 Animate copies the source clip’s movement onto the character image. It does not use a text prompt.'
    : 'Wan 2.7 VideoEdit changes the clip with a natural-language instruction while preserving the original movement. Add a reference image only when the edit needs one.';
}

function refreshRemixEstimate() {
  if (!remixing) return;
  const model = models[$('#remixModel').value];
  const resolution = $('#remixResolution').value;
  const duration = Number($('#remixDuration').value) || 0;
  const cost = model.rates[resolution] * duration;
  $('#remixEstimate').textContent = `${model.name} · ${duration}s source · estimated $${cost.toFixed(3)} · backed up before replacement`;
}

function openRemix(project, scene) {
  const options = remixModels();
  if (!scene.video || !options.length) return toast('No compatible Replicate remix models are configured');
  remixing = {project: project.id, shot: scene.shot_id, scene};
  $('#remixSource').textContent = `${project.name} · ${scene.shot_id} · existing clip will be backed up before replacement`;
  $('#remixModel').replaceChildren(...options.map(([key, model]) => new Option(model.name, key)));
  $('#remixModel').value = options.find(([, model]) => model.workflow === 'video_edit')?.[0] || options[0][0];
  $('#remixPrompt').value = '';
  $('#remixReference').value = '';
  updateRemixControls();
  $('#remix').showModal();
}

document.querySelectorAll('[data-tab]').forEach(button => button.onclick = () => changeView(button.dataset.tab));
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => {
  const dialog = $(`#${button.dataset.close}`);
  dialog.close();
  if (dialog.id === 'viewer') $('#viewerContent').replaceChildren();
  if (dialog.id === 'remix') remixing = null;
});
$('#viewer').addEventListener('close', () => $('#viewerContent').replaceChildren());
$('#remix').addEventListener('close', () => { remixing = null; });
$('#projects').addEventListener('click', () => syncQuickControls());
$('#search').oninput = render;
$('#filter').onchange = render;
$('#newProject').onclick = () => $('#create').showModal();

$('#grid').onclick = event => {
  const actionTarget = event.target.closest('[data-action]');
  const card = event.target.closest('.scene');
  if (!actionTarget || !card) return;
  const project = projects.find(item => item.id === card.dataset.project);
  const scene = card.dataset.shot === 'final'
    ? {video: project.video, shot_id: 'final'}
    : project.scenes.find(item => item.shot_id === card.dataset.shot);
  if (!project || !scene) return;
  if (actionTarget.dataset.action === 'favorite') {
    const key = `${project.id}/${scene.shot_id}`;
    favorites.has(key) ? favorites.delete(key) : favorites.add(key);
    localStorage.setItem('favorites', JSON.stringify([...favorites]));
    render();
  } else if (actionTarget.dataset.action === 'preview') {
    showViewer(scene.video);
  } else if (actionTarget.dataset.action === 'remix') {
    openRemix(project, scene);
  } else {
    openEditor(project, scene);
  }
};

$('#createForm').onsubmit = async event => {
  event.preventDefault();
  try {
    const project = await api('/api/create', {
      name: $('#name').value,
      count: Number($('#count').value),
      prompt: $('#createPrompt').value
    });
    selected = project.id;
    $('#create').close();
    changeView('scenes');
    await load();
    toast('Storyboard created. Open a scene to begin.');
  } catch (error) { toast(error.message); }
};

$('#sceneForm').onsubmit = async event => {
  event.preventDefault();
  try {
    await api('/api/scene', {...editing, prompt: $('#prompt').value, narration: $('#narration').value, camera: $('#camera').value});
    $('#editor').close();
    await load();
    toast('Scene saved');
  } catch (error) { toast(error.message); }
};

const toBase64 = file => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result.split(',')[1]);
  reader.onerror = reject;
  reader.readAsDataURL(file);
});

$('#upload').onchange = async event => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 10_000_000) return toast('Choose an image smaller than 10 MB');
  try {
    await api('/api/upload', {...editing, content: await toBase64(file)});
    await load();
    const scene = projects.find(item => item.id === editing.project).scenes.find(item => item.shot_id === editing.shot);
    $('#preview').innerHTML = `<img src="${esc(scene.image)}?v=${Date.now()}" alt="Start frame">`;
    toast('Portrait frame saved');
  } catch (error) { toast(error.message); }
  event.target.value = '';
};

function resolutions() {
  const model = models[$('#model').value];
  $('#resolution').replaceChildren(...model.resolutions.map(value => new Option(value, value)));
  $('#duration').disabled = Boolean(model.fixed_duration);
  if (model.fixed_duration) $('#duration').value = model.fixed_duration;
}

$('#settingsToggle').onclick = () => {
  const project = current();
  if (!project) return;
  $('#model').replaceChildren(...sceneModels().map(([key, model]) => new Option(model.name, key)));
  $('#model').value = project.settings.model;
  resolutions();
  $('#resolution').value = project.settings.resolution;
  $('#duration').value = project.settings.duration;
  $('#budget').value = project.settings.budget;
  $('#settings').showModal();
};
$('#model').onchange = resolutions;

$('#settingsForm').onsubmit = async event => {
  event.preventDefault();
  try {
    await api('/api/settings', {project: selected, settings: {
      model: $('#model').value, resolution: $('#resolution').value,
      duration: Number($('#duration').value), budget: Number($('#budget').value)
    }});
    $('#settings').close();
    await load();
    toast('Generation settings saved');
  } catch (error) { toast(error.message); }
};

$('#remixModel').onchange = updateRemixControls;
$('#remixResolution').onchange = refreshRemixEstimate;
$('#remixDuration').oninput = refreshRemixEstimate;

$('#remixForm').onsubmit = async event => {
  event.preventDefault();
  if (!remixing) return;
  const model = models[$('#remixModel').value];
  const prompt = $('#remixPrompt').value.trim();
  const reference = $('#remixReference').files[0];
  const duration = Number($('#remixDuration').value);
  const resolution = $('#remixResolution').value;
  if (!model) return toast('Choose a remix model');
  if (model.workflow === 'video_edit' && !prompt) return toast('Add an editing instruction first');
  if (model.workflow === 'motion_transfer' && !reference) return toast('Choose a character image first');
  if (reference && reference.size > 10_000_000) return toast('Choose an image smaller than 10 MB');
  const cost = model.rates[resolution] * duration;
  const budget = current()?.settings?.budget || 2;
  if (cost > budget) return toast(`This remix is estimated at $${cost.toFixed(3)}. Raise the budget cap in Settings first.`);
  if (!confirm(`Run ${model.name} on this clip? Estimated provider cost: $${cost.toFixed(3)}. The current clip will be backed up.`)) return;
  try {
    await api('/api/remix', {
      project: remixing.project,
      shot: remixing.shot,
      model: $('#remixModel').value,
      resolution,
      duration,
      prompt,
      reference: reference ? await toBase64(reference) : null
    });
    $('#remix').close();
    remixing = null;
    running = true;
    changeView('history');
    toast('Remix is generating');
  } catch (error) { toast(error.message); }
  $('#remixReference').value = '';
};

async function start(action, shot) {
  try {
    const project = current();
    if (action === 'run') {
      const model = models[project.settings.model];
      const cost = model.rates[project.settings.resolution] * (model.unit === 'second' ? project.settings.duration : 1);
      const scope = shot ? 'this scene' : 'the missing scenes';
      if (!confirm(`Generate ${scope} for ${project.name}? Estimated provider cost: $${(shot ? cost : project.estimate).toFixed(2)}. Budget cap: $${project.settings.budget.toFixed(2)}.`)) return;
    }
    await api('/api/' + action, {project: selected, ...(shot ? {shot} : {})});
    running = true;
    changeView('history');
    toast(shot ? 'Generating one scene' : 'Job started');
  } catch (error) { toast(error.message); }
}

$('#generate').onclick = () => start('run');
$('#build').onclick = () => start('assemble');

async function history() {
  try {
    const rows = await api('/api/history');
    $('#history').innerHTML = rows.map(job => `<div class="job">${esc(job.action)} · ${esc(job.project)} · ${job.returncode === 0 ? 'Completed' : 'Failed'}<br><small>${new Date(job.finished_at * 1000).toLocaleString()}</small></div>`).join('') || '<p>No completed studio jobs yet.</p>';
  } catch (error) { toast(error.message); }
}

async function poll() {
  try {
    const status = await api('/api/status');
    const wasRunning = running;
    running = status.running;
    $('#logs').textContent = status.log || 'No job running. Your next scene starts here.';
    $('#notice').textContent = status.running
      ? `Working on ${status.project} · progress is available in Activity`
      : status.returncode && status.returncode !== 0
        ? 'The last job stopped. Open Activity for details.' : '';
    $('#generate').disabled = running || !current()?.scenes.some(scene => !scene.video);
    $('#build').disabled = running || !current() || current().scenes.some(scene => !scene.video);
    if (wasRunning && !running) {
      await load();
      if (view === 'history') history();
    }
  } catch (error) { $('#notice').textContent = 'Studio disconnected. Keep the local server running.'; }
}

const reuseLabel = document.createElement('label');
reuseLabel.textContent = 'Or reuse a frame from your library';
const reuseSelect = document.createElement('select');
reuseLabel.append(reuseSelect);
const reuseButton = document.createElement('button');
reuseButton.type = 'button';
reuseButton.textContent = 'Use selected frame';
reuseLabel.append(reuseButton);
$('.upload').after(reuseLabel);

$('#editor').addEventListener('toggle', () => {
  if ($('#editor').open) {
    reuseSelect.replaceChildren(
      new Option('Choose a saved frame', ''),
      ...projects.flatMap(project => project.scenes.filter(scene => scene.image).map(scene => new Option(`${project.name} · ${scene.shot_id}`, `${project.id}|${scene.shot_id}`)))
    );
  }
});

reuseButton.onclick = async () => {
  if (!reuseSelect.value) return;
  try {
    const [source_project, source_shot] = reuseSelect.value.split('|');
    await api('/api/reuse', {...editing, source_project, source_shot});
    await load();
    const scene = projects.find(project => project.id === editing.project).scenes.find(item => item.shot_id === editing.shot);
    $('#preview').innerHTML = `<img src="${esc(scene.image)}?v=${Date.now()}" alt="Start frame">`;
    toast('Frame reused');
  } catch (error) { toast(error.message); }
};

const regenerate = document.createElement('button');
regenerate.type = 'button';
regenerate.textContent = 'Save & generate this scene';
$('#editor .dialog-actions').append(regenerate);
regenerate.onclick = async () => {
  const project = projects.find(item => item.id === editing.project);
  const model = models[project.settings.model];
  const cost = model.rates[project.settings.resolution] * (model.unit === 'second' ? project.settings.duration : 1);
  if (!confirm(`Generate just this scene? Estimated cost $${cost.toFixed(2)}. Your previous clip will be backed up. The final video must be rebuilt afterward.`)) return;
  try {
    await api('/api/scene', {...editing, prompt: $('#prompt').value, narration: $('#narration').value, camera: $('#camera').value});
    await api('/api/run', editing);
    $('#editor').close();
    running = true;
    changeView('history');
    toast('Generating one scene');
  } catch (error) { toast(error.message); }
};

$('#quickModel').onchange = () => {
  localStorage.setItem('quickModel', $('#quickModel').value);
  quickResolutions();
};
$('#quickResolution').onchange = () => localStorage.setItem('quickResolution', $('#quickResolution').value);
$('#quickReference').onchange = event => {
  const file = event.target.files[0];
  if (file) toast(`${file.name} selected as the reference frame`);
};

$('#promptForm').onsubmit = async event => {
  event.preventDefault();
  const prompt = $('#promptBar').value.trim();
  const modelKey = $('#quickModel').value;
  const model = models[modelKey];
  const file = $('#quickReference').files[0];
  if (!prompt) return toast('Describe what should happen in the clip first');
  if (!model) return toast('Choose a video model');
  if (model.fixed_duration && !file) return toast('Wan 2.2 Fast needs a portrait reference frame');
  if (file && file.size > 10_000_000) return toast('Choose a reference image smaller than 10 MB');
  const duration = model.fixed_duration || Number($('#quickDuration').value);
  const resolution = $('#quickResolution').value;
  const budget = current()?.settings?.budget || 2;
  const cost = model.rates[resolution] * (model.unit === 'second' ? duration : 1);
  if (cost > budget) return toast(`This clip is estimated at $${cost.toFixed(2)}. Raise the budget cap in Settings first.`);
  if (!confirm(`Generate a new prompt clip? Estimated provider cost: $${cost.toFixed(2)}. It will be saved as a one-scene project.`)) return;
  try {
    const name = prompt.replace(/\s+/g, ' ').slice(0, 56) || 'Prompt clip';
    const project = await api('/api/create', {name, count: 1, prompt});
    await api('/api/settings', {project: project.id, settings: {model: modelKey, resolution, duration, budget}});
    if (file) await api('/api/upload', {project: project.id, shot: project.scenes[0].shot_id, content: await toBase64(file)});
    selected = project.id;
    localStorage.setItem('project', selected);
    await api('/api/run', {project: selected, shot: project.scenes[0].shot_id});
    $('#promptBar').value = '';
    $('#quickReference').value = '';
    running = true;
    changeView('history');
    toast('Prompt clip is generating');
  } catch (error) { toast(error.message); }
};

load().catch(error => toast(error.message));
setInterval(poll, 3000);
poll();
