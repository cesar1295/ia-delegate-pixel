'use strict';
(() => {
  const art = window.PIXEL_ART;
  let names = [];
  const desks = {};
  let height = 200;
  const accents = {claude: '#d97757', codex: '#3ddc97', agy: '#7b8cff'};
  const known = new Set(['idle', 'sleep', 'working', 'fixing', 'checks', 'review', 'reviewing', 'waiting',
  'failed', 'quota', 'celebrate']);
  const emotes = {sleep: 'sleep', fixing: 'alert', checks: 'wait', review: 'question', reviewing: 'look',
    waiting: 'question', failed: 'fail', quota: 'sleep', celebrate: 'done'};
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const params = new URLSearchParams(location.search);
  const demo = params.get('demo') === '1';
  const demoMain = ['codex', 'agy'].includes(params.get('maestra')) ? params.get('maestra') : 'claude';
  const $ = id => document.getElementById(id);
  const canvas = $('office-canvas'), scene = $('scene');
  const offscreen = document.createElement('canvas');
  offscreen.width = 320; offscreen.height = 200;
  const ctx = offscreen.getContext('2d'), output = canvas.getContext('2d');
  let scale = 1, state = {agents: {}, runs: [], counts: {}, stats: []};
  let modalRequest = 0, opener = null, demoStep = 0;
  let firstEvents = true;
  const seen = new Set(), cache = {};
  const runtime = {}, layers = {};
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const safeState = name => known.has(state.agents[name]?.state) ? state.agents[name].state : 'idle';
  const randBlink = () => 3000 + Math.random() * 2000;
  function addAgent(name) {
    runtime[name] = {state: 'idle', started: performance.now(), blinkAt: performance.now() + randBlink(),
      particles: [], confetti: [], lastParticle: 0, queue: [], trip: null, minis: [], puffs: []};
    const label = node('div', 'agent-name', name.toUpperCase());
    const bubble = node('div', 'bubble');
    const bubbleText = node('span', 'bubble-text'); bubble.append(bubbleText); bubble.hidden = true;
    const hit = node('button', 'agent-hit');
    const mug = node('button', 'agent-hit mug-hit');
    const tooltip = node('div', 'quota-tooltip');
    mug.type = 'button';
    mug.append(tooltip);
    const extra = node('span', 'mini-extra');
    const minis = node('div');
    hit.type = 'button'; hit.setAttribute('aria-label',
    `Ver tarea de ${name === 'agy' ? 'agy' : name[0].toUpperCase() + name.slice(1)}`);
    label.style.setProperty('--accent', accents[name]); hit.style.setProperty('--accent', accents[name]);
    hit.addEventListener('click', () => openDetail(state.agents[name]?.run_id, hit, name));
    $('scene-layers').append(label, bubble, hit, mug, extra, minis);
    layers[name] = {label, bubble, bubbleText, hit, mug, tooltip, extra, minis};
  }
  function resize() {
    scale = Math.max(1, Math.floor(scene.parentElement.clientWidth / 320));
    canvas.width = 320 * scale; canvas.height = height * scale;
    canvas.style.width = `${canvas.width}px`; canvas.style.height = `${canvas.height}px`;
    scene.style.width = `${canvas.width}px`; scene.style.height = `${canvas.height}px`;
    output.imageSmoothingEnabled = false;
    scene.classList.toggle('scale-one', scale === 1);
    const font = base => `${Math.max(6, base * Math.min(1, scale / 2))}px`;
    scene.style.setProperty('--scene-font', font(10));
    scene.style.setProperty('--scene-number', font(16));
    scene.style.setProperty('--scene-caption', font(8));
    scene.style.setProperty('--scene-extra', font(9));
    Object.assign($('board').style, {left: `${112 * scale}px`, top: `${12 * scale}px`,
      width: `${96 * scale}px`, height: `${46 * scale}px`});
    for (const name of names) {
      const [dx, dy] = desks[name], l = layers[name];
      Object.assign(l.label.style, {left: `${(dx + 24) * scale}px`, top: `${(dy + 24) * scale}px`});
      Object.assign(l.mug.style, {left: `${(dx + 35) * scale}px`, top: `${(dy - 9) * scale}px`,
        width: `${11 * scale}px`, height: `${12 * scale}px`});
      if (!runtime[name].trip) Object.assign(l.hit.style, {left: `${(dx + 12) * scale}px`,
        top: `${(dy - 26) * scale}px`, width: `${24 * scale}px`, height: `${40 * scale}px`});
    }
    names.forEach(name => updateLayers(name));
    output.imageSmoothingEnabled = false;
  }
  function rect(x, y, w, h, color) {ctx.fillStyle = color; ctx.fillRect(x, y, w, h);}
  function outlined(x, y, w, h, color) {
    rect(x - 1, y - 1, w + 2, h + 2, '#1a1726'); rect(x, y, w, h, color);
  }
  function sprite(context, rows, palette, x, y, factor = 1) {
    rows.forEach((row, ry) => [...row].forEach((pixel, rx) => {
      if (pixel !== '.' && palette[pixel]) {
        context.fillStyle = palette[pixel]; context.fillRect(x + rx * factor, y + ry * factor, factor, factor);
      }
    }));
  }
  function faceRows(name, face) {
    const rows = art.characters[art.characters[name] ? name : 'generic'].map(row => [...row]);
    for (const [y, line] of Object.entries(art.faces[face])) {
      [...line].forEach((pixel, x) => {if (pixel !== '_') rows[Number(y)][art.faceOriginCol + x] = pixel;});
    }
    return rows.map(row => row.join(''));
  }
  function faceFor(name, t) {
    const s = safeState(name), r = runtime[name];
    if (t < r.happyUntil) return 'happy';
    if (s === 'sleep') return 'blink';
    if (s === 'review' || s === 'celebrate') return 'happy';
    if (s === 'failed' || s === 'quota') return 'sad';
    if (!motion.matches && ['idle', 'working', 'reviewing', 'checks'].includes(s)) {
      if (t >= r.blinkAt + 150) r.blinkAt = t + randBlink();
      if (t >= r.blinkAt) return 'blink';
    }
    return 'base';
  }
  function background() {
    rect(0, 0, 320, height, '#13111c'); rect(0, 0, 320, 80, '#262238');
    rect(0, 78, 320, 2, '#3a3358');
    for (let y = 80; y < height; y += 16) for (let x = 0; x < 320; x += 16)
    rect(x, y, 16, Math.min(16, height - y), ((x / 16 + (y - 80) / 16) % 2) ? '#41332e' : '#3a2e2a');
    rect(20, 14, 56, 40, '#1a1726');
    rect(110,10,100,50,'#c2c3c7'); rect(112,12,96,46,'#fff1e8');
    rect(292,68,12,12,'#b45a3c'); rect(291,66,14,2,'#8a3f2a');
    [[294,54,3,12],[298,50,3,16],[302,56,3,10]].forEach(r => rect(...r,'#2fbf71'));
    [[296,58,2,8],[300,54,2,10]].forEach(r => rect(...r,'#23a571'));
  }
  function position(name, t) {
    const [dx,dy] = desks[name], s = safeState(name), r = runtime[name];
    let offset = 0;
    if (!motion.matches) {
      if (name === 'agy') offset += Math.round(2 * Math.sin(2 * Math.PI * t / 2000));
      if (s === 'working' || s === 'fixing') offset -= Math.floor((t - r.started) / (s === 'fixing' ? 120 : 200)) % 2;
      if (s === 'celebrate' && t - r.started < 1500) offset += [0,-3,-5,-3,0][Math.floor((t-r.started)/100)%5];
    }
    return [dx + 16, dy - 14 + offset];
  }
  function drawAgent(name, t, part) {
    const [dx,dy] = desks[name], [px,py] = position(name,t), s = safeState(name), r = runtime[name];
    if (part === 'seat') {
      outlined(dx+17,dy-12,14,10,'#4a3f6b');
      if (!r.trip || r.trip.phase === 'reduced') {
        sprite(ctx,faceRows(name,faceFor(name,t)), palette(name),px,py);
        drawCharacterEffects(name,t);
      }
      return;
    }
    if (part === 'walk') { drawTrip(name, t); return; }
    rect(dx-1,dy-1,50,16,'#1a1726'); rect(dx,dy,48,4,'#8a5a3b'); rect(dx,dy+4,48,10,'#6b4430');
    rect(dx+2,dy+14,3,8,'#4a2f22'); rect(dx+43,dy+14,3,8,'#4a2f22');
    outlined(dx+17,dy-5,14,6,'#c2c3c7');
    rect(dx+23,dy-3,2,2,['working','fixing','checks'].includes(s) && Math.floor(t/500)%2 ? '#fff1e8' : accents[name]);
    drawMug(name, t);
    const l = layers[name];
    const trip = r.trip;
    const detail = trip ? (trip.event.type === 'delivered' ? 'entregando tarea' : 'llevando instrucciones')
    : t < r.feedbackUntil ? 'correcciones' : state.agents[name]?.detail;
    l.bubble.hidden = (!trip && ['idle','sleep'].includes(s)) || !detail;
    if (!l.bubble.hidden) {
      l.bubbleText.textContent = detail;
      const anchor = (trip ? trip.pos.x : px+8)*scale, width = l.bubble.offsetWidth;
      const left = Math.max(0,Math.min(anchor-width/2,canvas.width-width));
      l.bubble.style.left = `${left}px`; l.bubble.style.top = `${(trip ? trip.pos.y-36 : py-12)*scale}px`;
      l.bubble.style.setProperty('--tail',`${Math.max(6,Math.min(width-6,anchor-left))}px`);
    }
    const portrait = document.getElementById(`portrait-${name}`);
    if (portrait) {
      const pc = portrait.getContext('2d'); pc.clearRect(0,0,32,32);
      sprite(pc,faceRows(name,faceFor(name,t)),palette(name),0,0,2);
    }
  }
  function drawCharacterEffects(name,t) {
    const [dx,dy] = desks[name], [px,py] = position(name,t), s = safeState(name), r = runtime[name];
    const emote = t < r.emoteUntil ? r.emote : emotes[s];
    if (emote) sprite(ctx,art.emotes[emote],art.palettes.emote,px+12,py-9
    + (!motion.matches && s === 'sleep' ? Math.floor(t/600)%2 : 0));
    if (!motion.matches) {
      const active = ['working','fixing','reviewing'].includes(s);
      if (active && art.particles[name] && !r.trip && t-r.lastParticle >= 600 && r.particles.length < 3) {
        r.particles.push({x:dx+18+Math.floor(Math.random()*11),born:t}); r.lastParticle=t;
      }
      r.particles = r.particles.filter(p => t-p.born < 14*83);
      for (const p of r.particles) sprite(ctx,art.particles[name],art.palettes.particles[name],p.x,
      dy-8-Math.floor((t-p.born)/83));
      r.confetti = r.confetti.filter(p => t-p.born < 1000);
      for (const p of r.confetti) {
        const frame = (t-p.born)/83;
        rect(Math.round(p.x+p.vx*frame),Math.round(p.y-2*frame+.125*frame*frame),1,1,p.color);
      }
    }
  }
  function updateBubbleOverlap() {
    const visible = names.filter(name => !layers[name].bubble.hidden);
    const walkers = visible.filter(name => runtime[name].trip && runtime[name].trip.phase !== 'reduced');
    const bounds = new Map(visible.map(name => [name,layers[name].bubble.getBoundingClientRect()]));
    const intersects = (a,b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
    const foreground = [];
    for (const name of names) {
      const bubble = layers[name].bubble;
      const walking = walkers.includes(name);
      bubble.classList.toggle('walking-bubble',walking);
      const blockers = walking ? foreground : walkers;
      const covered = !bubble.hidden && blockers.some(other => intersects(bounds.get(name),bounds.get(other)));
      bubble.style.opacity = covered ? '0' : '1';
      if (walking && !covered) foreground.push(name);
    }
  }
  const phases = [
    {label: 'MADRUGADA', sky: ['#0b1026', '#121a3a', '#1d2b53'], overlay: [10, 12, 40, .35]},
    {label: 'MAÑANA', sky: ['#5fb4ff', '#8fd3ff', '#c7ecff'], overlay: [0, 0, 0, 0]},
    {label: 'TARDE', sky: ['#4fa8ff', '#7fc4ff', '#ffe7a8'], overlay: [255, 190, 90, .06]},
    {label: 'TARDE-NOCHE', sky: ['#3b2a6b', '#c4517a', '#ff9a5a'], overlay: [255, 120, 80, .10]},
    {label: 'NOCHE', sky: ['#0f1430', '#16204a', '#1d2b53'], overlay: [20, 20, 60, .25]}
  ];
  const stars = [[28, 22], [40, 30], [50, 19], [34, 40], [58, 44], [26, 34], [68, 40]];
  const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  const mix = (a, b, progress) => a.map((value, i) => value + (b[i] - value) * progress);
  const rgba = color => `rgba(${color.join(',')})`;
  let dayPhase = null, previousPhase = null, phaseStarted = 0;
  function updateClock() {
    const now = new Date(), hourParam = new URLSearchParams(location.search).get('hora');
    const fixed = hourParam !== null && /^\d{1,2}$/.test(hourParam) && Number(hourParam) < 24;
    const hour = fixed ? Number(hourParam) : now.getHours();
    const next = hour < 6 ? 0 : hour < 12 ? 1 : hour < 17 ? 2 : hour < 20 ? 3 : 4;
    if (next !== dayPhase) {
      previousPhase = dayPhase;
      dayPhase = next;
      phaseStarted = performance.now();
    }
    $('day-phase').textContent = `· ${phases[next].label}`;
    $('day-time').textContent = ` · ${String(hour).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  }
  function skyDetails(phase, t, alpha) {
    ctx.globalAlpha = alpha;
    const drift = motion.matches ? 0 : Math.floor(t / 2000) % 52;
    const cloud = (x, y, w, h) => {
      const shifted = 22 + (x - 22 + drift) % 52;
      rect(shifted, y, w, h, '#fff1e8');
      rect(shifted - 52, y, w, h, '#fff1e8');
    };
    if (phase === 0 || phase === 4) {
      rect(62, 20, 4, 4, phase === 0 ? '#fff1e8' : '#ffec27');
      if (phase === 0) rect(63, 21, 1, 1, '#c2c3c7');
      const points = phase === 0 ? [...stars.slice(0, 6), [44, 24], stars[6]] : stars;
      points.forEach(([x, y], i) => {
        if (phase === 0 && !motion.matches && (i === 1 || i === 5)
          && (t + (i === 5 ? 1000 : 0)) % 2000 >= 1500) return;
        rect(x, y, 1, 1, '#fff1e8');
      });
    } else if (phase === 1) {
      rect(60, 20, 6, 6, '#ffd75e'); rect(62, 22, 2, 2, '#fff1e8');
      cloud(28, 22, 10, 3); cloud(30, 20, 6, 2);
      cloud(46, 30, 12, 3); cloud(48, 28, 6, 2);
    } else if (phase === 2) {
      rect(60, 30, 6, 6, '#ffb627'); cloud(30, 24, 10, 3); cloud(32, 22, 6, 2);
    } else {
      rect(58, 46, 6, 6, '#ff6b4a');
      rect(28, 20, 1, 1, '#fff1e8'); rect(40, 18, 1, 1, '#fff1e8');
    }
    ctx.globalAlpha = 1;
  }
  function drawDaylight(t) {
    const progress = motion.matches || previousPhase === null ? 1 : Math.min(1, (t - phaseStarted) / 2000);
    const current = phases[dayPhase], previous = phases[previousPhase ?? dayPhase];
    rect(0, 0, 320, height, rgba(mix(previous.overlay, current.overlay, progress)));
    if (dayPhase === 0 || dayPhase === 4) {
      names.forEach(name => {
        const [dx, dy] = desks[name];
        rect(dx + 17, dy - 6, 14, 1, 'rgba(207, 232, 255, 0.6)');
        const active = ['working', 'fixing', 'checks'].includes(safeState(name));
        rect(dx + 23, dy - 3, 2, 2, active && Math.floor(t / 500) % 2 ? '#fff1e8' : accents[name]);
      });
      const main = names.find(name => state.agents[name].role === 'main');
      if (main) {
        const [dx, dy] = desks[main];
        ctx.fillStyle = 'rgba(255, 215, 94, 0.12)';
        ctx.beginPath(); ctx.moveTo(dx + 40, dy - 10); ctx.lineTo(dx + 49, dy - 10);
        ctx.lineTo(dx + 53, dy); ctx.lineTo(dx + 36, dy); ctx.closePath(); ctx.fill();
        rect(dx + 44, dy - 10, 1, 10, '#3a3358'); rect(dx + 42, dy - 12, 5, 2, '#ffd75e');
      }
    }
    ctx.save(); ctx.beginPath(); ctx.rect(22, 16, 52, 36); ctx.clip();
    current.sky.forEach((color, i) => {
      rect(22, 16 + i * 12, 52, 12, rgba([...mix(rgb(previous.sky[i]), rgb(color), progress), 1]));
    });
    if (progress < 1) skyDetails(previousPhase, t, 1 - progress);
    skyDetails(dayPhase, t, progress);
    ctx.restore();
  }
  updateClock();
  setInterval(updateClock, 30000);
  addEventListener('popstate', updateClock);
  let lastFrame = -Infinity;
  function frame(t) {
    if (t-lastFrame >= 83) {
      lastFrame = t;
      names.forEach(name => advanceTrip(name, t));
      background();
      const jobs = [];
      names.forEach(name => {
        const [x,y] = desks[name];
        jobs.push({x,y,draw: () => drawAgent(name,t,'seat')});
        jobs.push({x,y:y+22,draw: () => drawAgent(name,t,'desk')});
        if (runtime[name].trip) jobs.push({x:runtime[name].trip.pos.x,y:runtime[name].trip.pos.y,
          draw: () => drawAgent(name,t,'walk')});
        miniJobs(name,t,jobs);
      });
      jobs.sort((a,b) => a.y-b.y || a.x-b.x).forEach(job => job.draw());
      drawDaylight(t);
      updateBubbleOverlap();
      output.drawImage(offscreen,0,0,canvas.width,canvas.height);
    }
    requestAnimationFrame(frame);
  }
  const statusMap = {
    running:['--warn','EN CURSO'], 'listo-para-revisar':['--review','REVISIÓN'], ok:['--ok','LISTO'],
    integrado:['--ok','INTEGRADO'],
    'sin-cambios':['--err','SIN CAMBIOS'], 'cuota-agotada':['--err','SIN CUOTA'], descartado:['--muted',
    'DESCARTADO'], 'dry-run':['--muted','DRY-RUN'], 'escalado-a-main':['--muted','ESCALADO']
  };
  function stateColor(s) {
    if (['working','fixing','checks'].includes(s)) return '--warn';
    if (['review','reviewing','waiting'].includes(s)) return '--review';
    if (s === 'celebrate') return '--ok';
    if (['failed','quota'].includes(s)) return '--err';
    return '--muted';
  }
  function pill(text,color) {
    const p = node('span','pill',text); p.style.color = color.startsWith('--') ? `var(${color})` : color; return p;
  }
  function statusPill(status) {
    const [color,label] = statusMap[status] || ['--err',String(status || '').replace(/-/g,' ').toUpperCase()];
    const main = names.find(name => state.agents[name].role === 'main');
    return pill(label, status === 'escalado-a-main' && main ? accents[main] : color);
  }
  function render(data) {
    const agents = Array.isArray(data.agents) ? data.agents : [];
    state = {agents: Object.fromEntries(agents.map(agent => [agent.name,agent])),
      runs: data.runs || [], counts: data.counts || {}, stats: data.stats || []};
    names = agents.map(agent => agent.name);
    const workers = agents.filter(agent => agent.role === 'agent');
    height = 200 + 64 * (Math.max(1,Math.ceil(workers.length/3))-1);
    offscreen.height = height;
    agents.forEach(agent => {
      accents[agent.name] = agent.color;
      if (!runtime[agent.name]) addAgent(agent.name);
      if (agent.role === 'main') desks[agent.name] = [136,104];
    });
    workers.forEach((agent,i) => {
      const row = Math.floor(i/3), count = Math.min(3,workers.length-row*3);
      desks[agent.name] = [[136],[72,200],[40,136,232]][count-1].slice(i%3,i%3+1).concat(164+64*row);
    });
    Object.keys(layers).filter(name => !names.includes(name)).forEach(name => {
      Object.values(layers[name]).forEach(element => element.remove());
      delete layers[name]; delete runtime[name];
    });
    resize();
    const t = performance.now();
    for (const name of names) {
      const r = runtime[name], s = safeState(name);
      if (r.state !== s) {
        r.state = s; r.started = t; r.particles = []; r.confetti = []; r.lastParticle = t;
        if (s === 'celebrate' && !motion.matches) {
          const [x,y] = position(name,t);
          r.confetti = Array.from({length:12},(_,i) => ({x:x+8,y:y-2,vx:Math.random()*2-1,born:t,
            color:art.confetti[i%art.confetti.length]}));
        }
      }
    }
    for (const event of data.events || []) {
      if (!seen.has(event.id) && !firstEvents) enqueue(event);
      seen.add(event.id);
    }
    firstEvents = false;
    canvas.setAttribute('aria-label',names.map(name => {
      const agent = state.agents[name], pct = agent.quota?.remaining_pct;
      return `${agent.display}: ${stateLabels[safeState(name)].toLowerCase()}, cuota ${pct == null ? '?' : pct+'%'}`;
    }).join('. '));
    $('running-count').textContent = state.counts.running ?? 0;
    $('review-count').textContent = state.counts.review ?? 0;
    $('merged-count').textContent = state.counts.merged_today ?? 0;
    if (changed('team',agents)) $('team').replaceChildren(...names.map(name => {
      const agent = state.agents[name], row = node('div','team-row'), portrait = node('canvas','portrait');
      portrait.width=32; portrait.height=32; portrait.id=`portrait-${name}`;
      portrait.setAttribute('aria-hidden','true');
      const info = node('div','team-info'), heading = node('div','team-heading');
      const title = node('span','team-name',agent.display.toUpperCase()); title.style.color=agent.color;
      heading.append(title,pill(stateLabels[safeState(name)],stateColor(safeState(name))));
      info.append(heading);
      if (agent.detail) info.append(node('div','team-detail',agent.detail));
      info.append(quotaBar(agent));
      if (agent.subagents?.length) info.append(node('div','subagent-count',`${agent.subagents.length} subagentes`));
      row.append(portrait,info); return row;
    }));
    if (changed('runs',state.runs)) {
      const focusRun = document.activeElement?.dataset.runId;
      $('runs').replaceChildren(...(state.runs.length ? state.runs.slice(0,12).map(run => {
        const card=node('button','run-card');card.type='button';card.dataset.runId=run.run_id;
        card.style.setProperty('--accent',accents[run.agent] || 'var(--muted)');
        const meta=node('span','run-meta');meta.append(node('span','run-repo',
        `${run.repo || ''} · ${run.kind || ''}`),statusPill(run.status));
        card.append(node('span','run-task',run.task || run.phase_label || ''),meta);
        card.addEventListener('click',()=>openDetail(run.run_id,card,run.agent));return card;
      }) : [node('p','empty','Todavía no hay tareas. Delega una con ai-delegate.')]));
      if (focusRun) [...$('runs').children].find(c=>c.dataset.runId===focusRun)?.focus();
    }
    if (!changed('stats',state.stats)) return;
    if (!state.stats.length) $('stats').replaceChildren(node('p','empty','Sin datos todavía.'));
    else {
      const table=node('table'), head=node('thead'), hr=node('tr');
      ['agente','tipo','total','1ª %'].forEach(label=>{const th=node('th','',label);th.scope='col';
        hr.append(th);});head.append(hr);
      const body=node('tbody');
      state.stats.forEach(stat=>{const row=node('tr');[stat.agent,stat.kind,stat.total,
        `${stat.primera_pct ?? 0}%`].forEach(value=>row.append(node('td','',String(value))));body.append(row);});
      table.append(head,body);$('stats').replaceChildren(table);
    }
  }
  function connection(label,color) {$('connection-text').textContent=label;$('connection').style.color=`var(${color})`;}
  async function poll() {
    try {
      const response=await fetch('/api/state',{cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      render(await response.json());connection('EN VIVO','--ok');
    } catch {connection('SIN CONEXIÓN','--err');}
  }
  const overlay=$('modal-overlay'), panel=$('detail-panel'), content=$('detail-content');
  function closeDetail() {
    if (overlay.hidden) return;
    modalRequest++;overlay.hidden=true;document.querySelector('.office').inert=false;
    if (opener?.isConnected) opener.focus();
    else if (opener?.dataset.runId) [...$('runs').children].find(c=>c.dataset.runId===opener.dataset.runId)?.focus();
  }
  $('close-detail').addEventListener('click',closeDetail);
  overlay.addEventListener('click',event=>{if(event.target===overlay)closeDetail();});
  document.addEventListener('keydown',event=>{
    if(overlay.hidden)return;
    if(event.key==='Escape'){event.preventDefault();closeDetail();}
    if(event.key==='Tab') {
      const focusable=[...panel.querySelectorAll('button')];const first=focusable[0],last=focusable[focusable.length-1];
      if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  function detailView(run) {
    content.replaceChildren(node('div','detail-id',run.run_id || ''));
    const pills=node('div','detail-pills');pills.append(statusPill(run.status),pill(run.agent || '',
    accents[run.agent] || '--muted'),pill(run.kind || '','--muted'),pill(run.mode || '','--muted'));
    content.append(pills,node('p','',run.repo || ''),node('p','',
    `Checks: ${run.checks_ok === true ? 'ok' : run.checks_ok === false ? 'fallan' : 'sin checks'}`
    + ` · Correcciones: ${run.fix_rounds ?? 0}`));
    if (run.checks_ok == null) content.lastChild.classList.add('empty');
    const diff=typeof run.diffstat==='object' ? JSON.stringify(run.diffstat) : String(run.diffstat ?? '');
    content.append(node('p','',diff));
    content.append(node('h2','','Resumen'),node('pre','',run.summary || ''));
    if(run.feedback?.length){const list=node('ul');run.feedback.forEach(value=>list.append(node('li','',
      typeof value==='string'?value:JSON.stringify(value))));content.append(node('h2','','Feedback'),list);}
    content.append(node('h2','','Comandos'));
    for(const command of run.commands || []) {
      const row=node('div','command-row'), button=node('button','copy-button','COPIAR');button.type='button';
      button.addEventListener('click',async()=>{
        try {await navigator.clipboard.writeText(command);button.textContent='COPIADO';
          setTimeout(()=>button.textContent='COPIAR',1500);}
        catch {button.textContent='NO SE PUDO';button.classList.add('error');
          setTimeout(()=>{button.textContent='COPIAR';button.classList.remove('error');},1500);}
      });row.append(node('code','',command),button);content.append(row);
    }
  }
  async function openDetail(id,trigger,agent) {
    const request=++modalRequest;opener=trigger;panel.style.setProperty('--accent',accents[agent] || 'var(--muted)');
    overlay.hidden=false;document.querySelector('.office').inert=true;$('close-detail').focus();
    content.replaceChildren(node('p',id ? 'loading' : '',id ? 'CARGANDO…' : 'Sin tarea activa'));
    if(!id)return;
    try {
      let run;
      if(demo) run=demoDetail(id);
      else {
        const response=await fetch(`/api/run/${encodeURIComponent(id)}`,{cache:'no-store'});
        run=await response.json();if(!response.ok)throw new Error(run.error || `HTTP ${response.status}`);
      }
      if(request===modalRequest)detailView(run);
    } catch(error) {if(request===modalRequest)content.replaceChildren(node('p','error',
      `Error de red: ${error.message}`));}
  }
  const stateLabels = {idle:'LIBRE',sleep:'DORMIDO',working:'TRABAJANDO',fixing:'CORRIGIENDO',
    checks:'CHECKS',review:'POR REVISAR',reviewing:'REVISANDO',waiting:'ESPERANDO',failed:'FALLÓ',
    quota:'SIN CUOTA',celebrate:'¡LISTO!'};
  function changed(key,value) {
    const json=JSON.stringify(value);
    if (cache[key]===json) return false;
    cache[key]=json; return true;
  }
  function blend(color,target,amount) {
    const value=parseInt(color.slice(1),16), end=parseInt(target.slice(1),16);
    return '#'+[16,8,0].map(shift => Math.round(((value>>shift)&255)*(1-amount)
    +((end>>shift)&255)*amount).toString(16).padStart(2,'0')).join('');
  }
  function palette(name) {
    const agent=state.agents[name], common=art.palettes.common;
    if (art.characters[name]) return {...common,...art.palettes[name],...art.palettes.pants[name]};
    const color=agent.look?.color || agent.color;
    return {...common,h:agent.look?.hair || '#3a3a48',c:color,C:blend(color,'#000000',.25),
      a:blend(color,'#ffffff',.45),r:common.s,p:'#3a3a48',P:'#2a2a36'};
  }
  function quotaColor(pct) {return art.palettes.mug_fill[pct>=50?'high':pct>=20?'mid':'low'];}
  function quotaLines(agent) {
    const quota=agent.quota;
    if (!quota || quota.remaining_pct==null) return ['sin dato de cuota','?'];
    const lines=quota.estimated?['estimado']:[];
    for (const window of quota.windows || []) {
      const date=window.resets_at ? new Date(window.resets_at) : null;
      const reset=date ? date.toLocaleString('es',{...(date.toDateString()===new Date().toDateString()
        ? {hour:'2-digit',minute:'2-digit'} : {day:'numeric',month:'short'})}) : '?';
      lines.push(`${window.label}: queda ${window.used_pct==null?'?':100-window.used_pct}% · reinicia ${reset}`);
    }
    return lines;
  }
  function quotaBar(agent) {
    const row=node('div','quota-row'), bar=node('div','quota-bar'), quota=agent.quota;
    const pct=quota?.remaining_pct;
    for (let i=0;i<10;i++) {
      const segment=node('span');
      segment.style.background=pct!=null && i<Math.round(pct/10)?quotaColor(pct):'var(--line)';
      bar.append(segment);
    }
    row.append(bar,node('span','quota-value',pct==null?'SIN DATO':`${quota.estimated?'~':''}${pct}%`));
    const window=(quota?.windows || []).filter(w=>w.used_pct!=null && w.resets_at)
    .sort((a,b)=>b.used_pct-a.used_pct)[0];
    if (window) {
      const minutes=Math.max(0,Math.ceil((new Date(window.resets_at)-Date.now())/60000));
      row.append(node('span','quota-reset',`reinicia en ${Math.floor(minutes/60)} h ${minutes%60} min`));
    }
    return row;
  }
  function miniPoint(name,i) {
    const [dx,dy]=desks[name], left=dx+54+36+5>320;
    return {x:left?dx-18-12*i:dx+54+12*i,y:dy+14};
  }
  function updateLayers(name) {
    const agent=state.agents[name], l=layers[name], r=runtime[name];
    l.label.textContent=agent.display.toUpperCase();
    [l.label,l.hit,l.mug,l.extra].forEach(element=>element.style.setProperty('--accent',agent.color));
    l.hit.setAttribute('aria-label',`Ver tarea de ${agent.display}`);
    l.mug.setAttribute('aria-label',`Cuota de ${agent.display}`);
    l.tooltip.replaceChildren(...quotaLines(agent).map(line=>node('div','',line)));
    const minis=(agent.subagents || []).slice(0,4);
    minis.forEach((mini,i)=>{
      if (!r.minis[i]) r.puffs.push({...miniPoint(name,i),born:performance.now()});
    });
    r.minis.forEach((mini,i)=>{
      if (!minis[i]) r.puffs.push({...miniPoint(name,i),born:performance.now()});
    });
    r.minis=minis;
    l.minis.replaceChildren(...minis.map((mini,i)=>{
      const point=miniPoint(name,i), hit=node('span','mini-hit');
      hit.style.setProperty('--accent',agent.color);
      const tooltip=node('span','mini-tooltip',mini.label); hit.append(tooltip);
      Object.assign(hit.style,{left:`${(point.x-5)*scale}px`,top:`${(point.y-10)*scale}px`,
        width:`${10*scale}px`,height:`${10*scale}px`}); return hit;
    }));
    l.extra.hidden=(agent.subagents?.length || 0)<=4;
    l.extra.textContent=`+${(agent.subagents?.length || 0)-4}`;
    const point=miniPoint(name,3);
    Object.assign(l.extra.style,{left:`${(point.x+5)*scale}px`,top:`${(point.y-10)*scale}px`});
  }
  function miniJobs(name,t,jobs) {
    const r=runtime[name];
    r.minis.forEach((mini,i)=>{
      const point=miniPoint(name,i), bob=motion.matches?0:Math.floor((t+i*100)/400)%2;
      jobs.push({...point,draw:()=>sprite(ctx,art.mini,palette(name),point.x-5,point.y-10-bob)});
    });
    r.puffs=r.puffs.filter(p=>t-p.born<300);
    r.puffs.forEach(p=>jobs.push({...p,draw:()=>sprite(ctx,art.items.puff,art.palettes.items,p.x-2,p.y-5)}));
  }
  function drawMug(name,t) {
    const [dx,dy]=desks[name], pct=state.agents[name].quota?.remaining_pct;
    const filled=pct==null?0:Math.round(6*pct/100);
    const colors={...art.palettes.items};
    if (pct!=null && pct<20 && (motion.matches || Math.floor(t/1000)%2)) colors.k='#ff5d73';
    art.items.mug.forEach((row,y)=>sprite(ctx,[row],
    {...colors,x:y>6-filled && y<=6?quotaColor(pct):colors.x},dx+37,dy-7+y));
    if (pct>=50) {
      const odd=motion.matches?0:Math.floor(t/500)%2;
      rect(dx+38+odd,dy-9-odd,1,1,art.palettes.mug_fill.steam);
      rect(dx+40+odd,dy-10-odd,1,1,art.palettes.mug_fill.steam);
    }
  }
  function burst(name,t) {
    const r=runtime[name], [x,y]=position(name,t); r.happyUntil=t+1500;
    if (!motion.matches) r.confetti=Array.from({length:12},(_,i)=>({x:x+8,y:y-2,
      vx:Math.random()*2-1,born:t,color:art.confetti[i%art.confetti.length]}));
  }
  function effect(event,target,t) {
    const r=runtime[target]; if (!r) return;
    r.emote=event.type==='delivered'?'look':['failed','discarded'].includes(event.type)?'fail':'alert';
    r.emoteUntil=t+(['failed','discarded'].includes(event.type)?1500:900);
    if (event.type==='feedback') {
      const main=names.find(name=>state.agents[name].role==='main');
      if (runtime[main]) runtime[main].feedbackUntil=t+900;
    }
  }
  function enqueue(event) {
    const main=names.find(name=>state.agents[name].role==='main');
    if (event.type==='merged') { [main,event.agent].forEach(name=>{if(runtime[name])burst(name,performance.now());});
      return; }
    if (['failed','discarded'].includes(event.type)) {effect(event,event.agent,performance.now());return;}
    const who=event.type==='delivered'?event.agent:main;
    const target=event.type==='delivered'?main:event.type==='escalated'?event.label:event.agent;
    if (!runtime[who] || !runtime[target] || who===target) return;
    runtime[who].queue.push({event,target});
    if (runtime[who].queue.length>3) runtime[who].queue.shift();
  }
  function standing(name) {const [dx,dy]=desks[name];return {x:dx-6,y:dy+12};}
  function aisle(name) {return state.agents[name].role==='main'?142:desks[name][1]-22;}
  function advanceTrip(name,t) {
    const r=runtime[name];
    while (r.queue.length && !names.includes(r.queue[0].target)) r.queue.shift();
    if (!r.trip && r.queue.length) {
      const {event,target}=r.queue.shift(), start=standing(name), end=standing(target);
      r.trip={event,target,pos:{...start},points:[start,{x:start.x,y:aisle(name)},
        {x:end.x,y:aisle(name)},{x:end.x,y:aisle(target)},end],index:1,last:t,phase:'out',carrying:true};
      if (motion.matches) {r.trip.phase='reduced';r.trip.arrived=t;}
    }
    const trip=r.trip; if (!trip) return;
    if (!names.includes(trip.target)) {r.trip=null;return;}
    if (trip.phase==='reduced') {
      if (t-trip.arrived>=900) {effect(trip.event,trip.target,t);r.trip=null;}
      return;
    }
    if (trip.phase==='pause') {
      if (t-trip.arrived<900) return;
      trip.phase='back';trip.index=trip.points.length-2;trip.last=t;trip.carrying=false;
    }
    let distance=(t-trip.last)*48/1000;trip.last=t;trip.moving=false;
    while (distance>0 && r.trip && trip.phase!=='pause') {
      const next=trip.points[trip.index], dx=next.x-trip.pos.x,dy=next.y-trip.pos.y;
      const length=Math.hypot(dx,dy); trip.moving=length>0;
      if (distance<length) {trip.pos.x+=dx*distance/length;trip.pos.y+=dy*distance/length;break;}
      trip.pos={...next};distance-=length;
      trip.index+=trip.phase==='out'?1:-1;
      if (trip.index===trip.points.length) {
        trip.phase='pause';trip.moving=false;trip.arrived=t;effect(trip.event,trip.target,t);break;
      }
      if (trip.index<0) {r.trip=null;
        const [dx,dy]=desks[name];
        Object.assign(layers[name].hit.style,{left:`${(dx+12)*scale}px`,top:`${(dy-26)*scale}px`});
        break;}
    }
  }
  function drawTrip(name,t) {
    const trip=runtime[name].trip, [dx,dy]=desks[trip.target];
    if (trip.phase==='reduced') {
      if (Math.floor((t-trip.arrived)/150)%2===0)
      sprite(ctx,art.items[trip.event.type==='delivered'?'paper_done':'paper'],art.palettes.items,dx+21,dy-10);
      return;
    }
    const body=art.bodies[name] || art.bodies.generic;
    sprite(ctx,body[trip.moving?Math.floor(t/150)%2?'walkB':'walkA':'stand'],palette(name),
    Math.round(trip.pos.x)-8,Math.round(trip.pos.y)-24);
    const l=layers[name];
    Object.assign(l.hit.style,{left:`${(trip.pos.x-12)*scale}px`,top:`${(trip.pos.y-36)*scale}px`});
    if (!trip.carrying) return;
    let x=trip.pos.x-2,y=trip.pos.y-12;
    if (trip.phase==='pause') {
      const progress=Math.min(1,(t-trip.arrived)/300);
      x+=(dx+21-x)*progress;y+=(dy-10-y)*progress;
      if (progress===1) return;
    }
    sprite(ctx,art.items[trip.event.type==='delivered'?'paper_done':'paper'],art.palettes.items,
    Math.round(x),Math.round(y));
  }

  const demoEvents = [];
  function demoData() {
    const resets = new Date(Date.now()+7980000).toISOString();
    const agents = [
    {name:'claude',display:'Claude',color:'#d97757',role:'main'},
    {name:'codex',display:'Codex',color:'#3ddc97',role:'agent'},
    {name:'agy',display:'agy',color:'#7b8cff',role:'agent'},
    {name:'opencode',display:'OpenCode',color:'#f0a500',role:'agent',
      look:{hair:'#2e5d4b',color:'#f0a500'}}
    ];
    agents.forEach(agent => {
      agent.role = agent.name === demoMain ? 'main' : 'agent';
    });
    agents.sort((a, b) => Number(b.role === 'main') - Number(a.role === 'main'));
    agents.forEach(agent => {
      agent.state = agent.role === 'main' ? 'waiting' : 'working';
      agent.detail = agent.role === 'main' ? 'esperando a Alex' : 'Implementando tarea';
      agent.run_id = `demo-${agent.name}`; agent.subagents = [];
      agent.quota = null;
    });
    agents[1].quota = {remaining_pct:93,estimated:false,windows:[
      {label:'5 h',used_pct:7,resets_at:resets},{label:'7 d',used_pct:1,resets_at:resets}]};
    agents[2].quota = {remaining_pct:60,estimated:true,windows:[]};
    if (demoStep >= 4) agents[0].quota = {remaining_pct:15,estimated:false,windows:[]};
    if (demoStep >= 1 && demoStep < 5) agents[0].subagents = [{label:'Revisión'},{label:'Análisis'}];
    if (demoStep >= 2) agents[1].subagents = [{label:'Checks'}];
    if (demoStep === 6) {
      agents[1].state='celebrate'; agents[1].detail='¡integrado!';
      agents[2].state='quota'; agents[2].quota.remaining_pct=0;
    }
    const runs = agents.map(agent => ({run_id:agent.run_id,agent:agent.name,kind:'feature',mode:'write',
      repo:'tienda',task:agent.detail,status:agent.state==='celebrate'?'integrado':'running',checks_ok:true}));
    runs.push({run_id:'demo-read',agent:'agy',kind:'tests',mode:'read',repo:'tienda',
      task:'Revisar precios',status:'listo-para-revisar',checks_ok:null});
    return {agents,runs,events:demoEvents,counts:{running:3,review:1,merged_today:demoStep===6?1:0},
      stats:agents.map(agent => ({agent:agent.name,kind:'feature',total:8,primera_pct:75}))};
  }
  function demoDetail(id) {
    const run=state.runs.find(run=>run.run_id===id);
    if (!run) throw new Error('Corrida no encontrada');
    return {...run,summary:[run.task,run.repo,'Implementación revisada.','Archivos actualizados.',
      'Casos verificados.','Checks: ok','Diff: +42 −8',run.status].join('\n'),
      feedback:['Revisar los cambios antes de integrar.'],
      commands:['diff','feedback','merge','discard'].map(command => `ai-delegate ${command} ${id}`)};
  }
  motion.addEventListener('change',() => names.forEach(name => {
    runtime[name].particles=[]; runtime[name].confetti=[]; runtime[name].trip=null;
  }));
  new ResizeObserver(resize).observe(scene.parentElement);
  render({agents:[]}); firstEvents=true; requestAnimationFrame(frame);
  if (demo) {
    connection('DEMO','--review'); render(demoData());
    setInterval(() => {
      demoStep=demoStep%6+1;
      const types=['assigned','assigned','delivered','feedback','delivered','merged'];
      const worker = demoMain === 'codex' ? 'claude' : 'codex';
      const other = demoMain === 'agy' ? 'claude' : 'agy';
      const targets=[worker,'opencode',other,worker,worker,worker];
      demoEvents.push({id:demoEvents.length+1,type:types[demoStep-1],agent:targets[demoStep-1]});
      render(demoData());
    },5000);
  } else {poll();setInterval(poll,2000);}
})();
