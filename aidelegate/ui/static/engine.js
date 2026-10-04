'use strict';
(() => {
  const office = window.OFFICE, art = window.PIXEL_ART;
  const phases = [
    {label: 'MADRUGADA', sky: ['#0b1026', '#121a3a', '#1d2b53'], overlay: [10, 12, 40, .35]},
    {label: 'MAÑANA', sky: ['#5fb4ff', '#8fd3ff', '#c7ecff'], overlay: [0, 0, 0, 0]},
    {label: 'TARDE', sky: ['#4fa8ff', '#7fc4ff', '#ffe7a8'], overlay: [255, 190, 90, .06]},
    {label: 'TARDE-NOCHE', sky: ['#3b2a6b', '#c4517a', '#ff9a5a'], overlay: [255, 120, 80, .10]},
    {label: 'NOCHE', sky: ['#0f1430', '#16204a', '#1d2b53'], overlay: [20, 20, 60, .25]}
  ];
  const offsets = [[18, 4], [30, 4], [18, 16], [30, 16]];
  const key = tile => tile.join(',');
  const same = (a, b) => key(a) === key(b);
  const atTile = tile => ({x: tile[0] * 16, y: tile[1] * 16 - 8});
  const element = (tag, cls, text) => {
    const el = document.createElement(tag);
    el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  class OfficeEngine {
    constructor(api) {
      this.api = api;
      this.scene = document.getElementById('scene');
      this.canvas = document.getElementById('office-canvas');
      this.output = this.canvas.getContext('2d');
      this.world = document.createElement('canvas');
      this.world.width = office.cols * 16;
      this.world.height = office.rows * 16;
      this.ctx = this.world.getContext('2d');
      this.floor = document.createElement('canvas');
      this.floor.width = this.world.width;
      this.floor.height = this.world.height;
      this.people = new Map();
      this.roomLabels = [];
      this.motion = matchMedia('(prefers-reduced-motion: reduce)');
      this.zoom = 1;
      this.camera = {x: this.world.width / 2, y: this.world.height / 2};
      this.fitMode = true;
      this.config = {};
      this.phase = null;
      this.last = 0;
      this.blocked = new Set([...office.map.placements, ...office.map.desks]
        .flatMap(item => item.blocks || []).map(key));
      this.buildFloor();
      for (const room of Object.values(office.map.rooms)) {
        const label = element('div', 'room-label', room.name);
        document.getElementById('scene-layers').append(label);
        this.roomLabels.push({label, x: room.rect[0] * 16 + 2, y: room.rect[1] * 16 + 16});
      }
      try {
        const saved = JSON.parse(localStorage.getItem('office-camera-v4'));
        if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
          this.zoom = Math.max(1, Math.min(6, Math.round(saved.zoom) || 1));
          this.camera = {x: saved.x, y: saved.y};
          this.fitMode = false;
        }
      } catch { /* La cámara sigue funcionando si el almacenamiento no está disponible. */ }
      this.controls();
      new ResizeObserver(() => this.resize()).observe(this.scene);
      this.resize();
      this.motion.addEventListener('change', () => {
        for (const p of this.people.values()) { p.confetti = []; p.particles = []; }
      });
      this.visibility();
    }
    rect(x, y, w, h, color, ctx = this.ctx) {
      ctx.fillStyle = color;
      ctx.fillRect(x, y, w, h);
    }
    sprite(rows, palette, x, y, flip = false) {
      if (!rows) return;
      const width = rows[0].length;
      rows.forEach((row, ry) => [...row].forEach((pixel, rx) => {
        if (pixel !== '.' && palette[pixel]) {
          this.rect(Math.round(x) + (flip ? width - rx - 1 : rx), Math.round(y) + ry, 1, 1, palette[pixel]);
        }
      }));
    }
    buildFloor() {
      const ctx = this.floor.getContext('2d');
      office.map.grid.forEach((row, y) => [...row].forEach((ch, x) => {
        const tile = office.tiles[ch];
        tile.rows.forEach((line, ry) => [...line].forEach((pixel, rx) => {
          this.rect(x * 16 + rx, y * 16 + ry, 1, 1, office.palette[tile.keys[pixel]], ctx);
        }));
      }));
    }
    controls() {
      document.getElementById('zoom-out').onclick = () => this.setZoom(this.zoom - 1);
      document.getElementById('zoom-in').onclick = () => this.setZoom(this.zoom + 1);
      this.scene.addEventListener('dblclick', () => {
        this.fitMode = true;
        this.camera = {x: this.world.width / 2, y: this.world.height / 2};
        this.resize();
        this.saveCamera();
      });
      this.scene.addEventListener('wheel', event => {
        if (!event.ctrlKey) return;
        event.preventDefault();
        this.setZoom(this.zoom + (event.deltaY < 0 ? 1 : -1));
      }, {passive: false});
      this.scene.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        this.drag = {id: event.pointerId, x: event.clientX, y: event.clientY,
          camera: {...this.camera}, moved: false};
      });
      this.scene.addEventListener('pointermove', event => {
        if (!this.drag || this.drag.id !== event.pointerId) return;
        const dx = event.clientX - this.drag.x, dy = event.clientY - this.drag.y;
        if (!this.drag.moved && Math.hypot(dx, dy) < 4) return;
        this.drag.moved = true;
        this.scene.setPointerCapture(event.pointerId);
        this.camera.x = this.drag.camera.x - dx / this.zoom;
        this.camera.y = this.drag.camera.y - dy / this.zoom;
        this.clamp();
      });
      const end = () => {
        this.dragged = this.drag?.moved;
        this.drag = null;
        this.saveCamera();
        setTimeout(() => { this.dragged = false; }, 0);
      };
      this.scene.addEventListener('pointerup', end);
      this.scene.addEventListener('pointercancel', end);
      this.scene.addEventListener('click', event => {
        if (this.dragged) { event.preventDefault(); event.stopPropagation(); }
      }, true);
    }
    setZoom(zoom) {
      this.fitMode = false;
      this.zoom = Math.max(1, Math.min(6, zoom));
      this.clamp();
      this.saveCamera();
    }
    saveCamera() {
      try { localStorage.setItem('office-camera-v4', JSON.stringify({...this.camera, zoom: this.zoom})); }
      catch { /* Almacenamiento opcional. */ }
    }
    clamp() {
      for (const [axis, dimension] of [['x', 'width'], ['y', 'height']]) {
        const half = this.canvas[dimension] / this.zoom / 2;
        const min = half - 32, max = this.world[dimension] + 32 - half;
        this.camera[axis] = min > max ? (axis === 'y' ? half : this.world.width / 2)
          : Math.max(min, Math.min(max, this.camera[axis]));
      }
    }
    resize() {
      this.canvas.width = this.scene.clientWidth;
      this.canvas.height = this.scene.clientHeight;
      if (this.fitMode) {
        this.zoom = Math.max(1, Math.min(6, Math.floor(this.canvas.width / this.world.width)));
        this.camera = {x: this.world.width / 2, y: this.canvas.height / this.zoom / 2};
      }
      this.output.imageSmoothingEnabled = false;
      this.clamp();
    }
    screenPoint(x, y) {
      return [Math.round((x - this.camera.x) * this.zoom + this.canvas.width / 2),
        Math.round((y - this.camera.y) * this.zoom + this.canvas.height / 2)];
    }
    place(el, x, y, w, h) {
      const [left, top] = this.screenPoint(x, y);
      el.style.left = `${left}px`;
      el.style.top = `${top}px`;
      if (w !== undefined) el.style.width = `${w * this.zoom}px`;
      if (h !== undefined) el.style.height = `${h * this.zoom}px`;
    }
    createPerson(agent, desk) {
      const hit = element('button', 'agent-hit');
      hit.type = 'button';
      hit.onclick = () => this.api.openDetail(this.people.get(agent.name)?.agent.run_id, hit, agent.name);
      const mug = element('button', 'agent-hit mug-hit');
      mug.type = 'button';
      const tooltip = element('div', 'quota-tooltip');
      mug.append(tooltip);
      const label = element('div', 'agent-name');
      const bubble = element('div', 'bubble');
      const text = element('span', 'bubble-text');
      bubble.append(text);
      const extra = element('div', 'mini-extra');
      const minis = element('div', 'mini-layer');
      document.getElementById('scene-layers').append(hit, mug, label, bubble, extra, minis);
      const home = agent.role === 'main' ? office.map.spots.master : desk;
      return {agent, desk, home, tile: home.seat_tile, pos: {x: home.seated_sprite[0], y: home.seated_sprite[1]},
        pose: 'seat', destination: 'home', changed: performance.now() - 2000, queue: [], path: [],
        confetti: [], particles: [], puffs: [], miniCount: 0, hit, mug, tooltip, label, bubble, text, extra, minis};
    }
    update(agents) {
      this.agents = agents;
      const visible = agents.filter(a => a.role === 'main' || a.role === 'agent');
      const workers = visible.filter(a => a.role === 'agent').slice(0, 9);
      const included = visible.filter(a => a.role === 'main' || workers.includes(a));
      for (const [name, p] of this.people) {
        if (!included.some(a => a.name === name)) {
          ['hit', 'mug', 'label', 'bubble', 'extra', 'minis'].forEach(k => p[k].remove());
          this.people.delete(name);
        }
      }
      for (const agent of included) {
        const desk = office.map.desks[workers.indexOf(agent)];
        let p = this.people.get(agent.name);
        if (p && p.agent.role !== agent.role) {
          ['hit', 'mug', 'label', 'bubble', 'extra', 'minis'].forEach(k => p[k].remove());
          this.people.delete(agent.name);
          p = null;
        }
        if (!p) {
          p = this.createPerson(agent, desk);
          this.people.set(agent.name, p);
        }
        if (p.agent.state !== agent.state) {
          p.changed = performance.now();
          if (agent.state === 'celebrate') this.burst(p);
        }
        p.agent = agent;
        p.desk = desk;
        p.home = agent.role === 'main' ? office.map.spots.master : desk;
        for (const el of [p.hit, p.mug, p.label, p.extra]) el.style.setProperty('--accent', agent.color);
        p.label.textContent = agent.display.toUpperCase();
        p.hit.setAttribute('aria-label', `Ver tarea de ${agent.display}`);
        p.mug.setAttribute('aria-label', `Cuota de ${agent.display}`);
        p.tooltip.replaceChildren(...this.api.quotaLines(agent).map(line => element('div', '', line)));
        const minis = (agent.subagents || []).slice(0, 4);
        if (minis.length !== p.miniCount && !this.motion.matches) {
          for (let i = Math.min(minis.length, p.miniCount); i < Math.max(minis.length, p.miniCount); i++) {
            p.puffs.push({i, born: performance.now()});
          }
        }
        p.miniCount = minis.length;
        p.minis.replaceChildren(...minis.map(mini => {
          const hit = element('span', 'mini-hit');
          hit.append(element('span', 'mini-tooltip', mini.label));
          return hit;
        }));
        p.extra.hidden = (agent.subagents?.length || 0) <= 4;
        p.extra.textContent = `+${(agent.subagents?.length || 0) - 4}`;
      }
    }
    walkable(tile) {
      return office.map.walkable.includes(office.map.grid[tile[1]]?.[tile[0]]) && !this.blocked.has(key(tile));
    }
    path(start, end) {
      if (same(start, end)) return [];
      const queue = [start], prev = new Map([[key(start), null]]);
      for (let i = 0; i < queue.length; i++) {
        const tile = queue[i];
        if (same(tile, end)) {
          const route = [];
          let current = end;
          while (!same(current, start)) { route.unshift(current); current = prev.get(key(current)); }
          return route;
        }
        for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) {
          const next = [tile[0] + dx, tile[1] + dy];
          if (this.walkable(next) && !prev.has(key(next))) { prev.set(key(next), tile); queue.push(next); }
        }
      }
      return null;
    }
    go(p, destination, done) {
      p.destination = destination.id;
      p.final = destination;
      p.done = done;
      p.path = this.path(p.tile, destination.tile);
      if (this.motion.matches || !p.path?.length) { this.arrive(p); return; }
      p.pos = atTile(p.tile);
      p.pose = 'walk';
    }
    arrive(p) {
      p.tile = p.final.tile;
      p.pos = p.final.pos || atTile(p.tile);
      p.pose = p.final.pose || 'stand';
      p.flip = p.final.flip || false;
      p.direction = p.final.direction || 'down';
      p.sofa = p.final.sofa;
      p.path = [];
      const done = p.done;
      p.done = null;
      done?.();
    }
    home(p) {
      return {id: 'home', tile: p.home.seat_tile,
        pos: {x: p.home.seated_sprite[0], y: p.home.seated_sprite[1]}, pose: 'seat'};
    }
    desired(p, occupied) {
      const s = p.agent.state, spots = office.map.spots;
      if (p.agent.role === 'main') {
        return s === 'waiting' ? {id: 'waiting', tile: spots.master.audience[1]} : this.home(p);
      }
      if (s === 'quota') {
        const tile = spots.kitchen.find(t => !occupied.has(key(t)));
        if (tile) { occupied.add(key(tile)); return {id: `kitchen:${key(tile)}`, tile, direction: 'up'}; }
        return {id: 'kitchen-full', tile: p.desk.visit_tile, direction: 'down'};
      }
      const since = typeof p.agent.since === 'number' ? p.agent.since * 1000 : Date.parse(p.agent.since);
      if (s === 'sleep' || (s === 'idle' && Date.now() - since > 120000)) {
        const seat = spots.lounge_sofa.find(s => !occupied.has(key(s.tile)));
        if (seat) {
          occupied.add(key(seat.tile));
          const sofa = office.map.placements.find(item => item.role === seat.sofa);
          const [sx, sy] = office.furniture.sofa.seats[seat.seat];
          return {id: `sofa:${key(seat.tile)}`, tile: seat.tile, pose: 'sofa', sofa,
            pos: {x: sofa.x + sx, y: sofa.y + sy},
            direction: 'side', flip: sofa.flip};
        }
        const tile = spots.lounge_stand.find(t => !occupied.has(key(t))) || spots.lounge_stand[0];
        occupied.add(key(tile));
        return {id: `lounge:${key(tile)}`, tile};
      }
      return this.home(p);
    }
    advance(p, t, delta) {
      if (p.path?.length) {
        let distance = delta * 48 / 1000;
        while (distance > 0 && p.path.length) {
          const next = atTile(p.path[0]), dx = next.x - p.pos.x, dy = next.y - p.pos.y;
          p.direction = dy > 0 ? 'down' : dy < 0 ? 'up' : 'side';
          p.flip = dx < 0;
          const length = Math.hypot(dx, dy);
          if (distance < length) {
            p.pos.x += dx / length * distance;
            p.pos.y += dy / length * distance;
            break;
          }
          distance -= length;
          p.pos = next;
          p.tile = p.path.shift();
          if (!p.path.length) this.arrive(p);
        }
      }
      if (p.pauseUntil && t >= p.pauseUntil) {
        p.pauseUntil = 0;
        p.carry = null;
        this.go(p, this.home(p), () => {
          p.busy = false;
          if (p.assisted) { p.assisted.busy = false; p.assisted = null; }
        });
      }
      if (!p.busy && !p.path.length && p.queue.length) this.trip(p, p.queue.shift());
    }
    enqueue(event) {
      const master = [...this.people.values()].find(p => p.agent.role === 'main');
      const agent = this.people.get(event.agent);
      if (event.type === 'merged') { if (master) this.burst(master); if (agent) this.burst(agent); return; }
      if (['failed', 'discarded'].includes(event.type)) { if (agent) this.emote(agent, 'fail', 1500); return; }
      if (!['assigned', 'feedback', 'escalated', 'delivered'].includes(event.type)) return;
      const visitor = event.type === 'delivered' ? agent : master;
      const target = event.type === 'delivered' ? master : this.people.get(event.label) || agent;
      if (!visitor || !target || !target.home || visitor === target) return;
      visitor.queue.push({event, target});
      if (visitor.queue.length > 3) visitor.queue.shift();
    }
    trip(p, {event, target}) {
      if (!this.people.has(target.agent.name)) return;
      if (target.busy && event.type !== 'delivered') {
        p.queue.unshift({event, target});
        return;
      }
      p.busy = true;
      const delivered = event.type === 'delivered';
      if (!delivered) { target.busy = true; p.assisted = target; }
      const start = () => {
        p.carry = delivered ? 'paper_done' : 'paper';
        let tile;
        if (delivered) {
          tile = office.map.spots.master.audience.find(tile => ![...this.people.values()]
            .some(other => other !== p && same(other.final?.tile || other.tile, tile)))
            || office.map.spots.master.audience[1];
        } else tile = target.desk?.visit_tile;
        if (!tile) { p.busy = false; return; }
        this.go(p, {id: 'visit', tile}, () => {
          this.emote(target, delivered ? 'look' : 'alert', 900);
          p.pauseUntil = performance.now() + 900;
        });
      };
      if (!delivered && target.destination !== 'home') {
        target.busy = true;
        this.go(target, this.home(target), start);
      } else if (delivered && p.destination !== 'home') this.go(p, this.home(p), start);
      else start();
    }
    emote(p, emote, duration) { p.emote = emote; p.emoteUntil = performance.now() + duration; }
    burst(p) {
      p.happyUntil = performance.now() + 1500;
      if (!this.motion.matches) p.confetti = Array.from({length: 12}, (_, i) => ({born: performance.now(),
        vx: Math.random() * 2 - 1, color: art.confetti[i % art.confetti.length]}));
    }
    furniture(item) {
      const f = office.furniture[item.kind];
      for (const [x, y, w, h, color] of f.rects) {
        this.rect(item.x + (item.flip ? f.w - x - w : x), item.y + y, w, h, office.palette[color]);
      }
      for (const [x, y, w, h] of f.outline || []) {
        const left = item.x + (item.flip ? f.w - x - w : x), top = item.y + y;
        this.rect(left, top, w, 1, office.palette.k);
        this.rect(left, top + h - 1, w, 1, office.palette.k);
        this.rect(left, top, 1, h, office.palette.k);
        this.rect(left + w - 1, top, 1, h, office.palette.k);
      }
    }
    screen(item, state, t, light = false) {
      const f = office.furniture[item.kind];
      if (!f.screen) return;
      const [sx, sy, w, h] = f.screen;
      const x = item.x + sx, y = item.y + sy;
      const on = ['working', 'fixing', 'checks', 'review', 'failed', 'quota'].includes(state);
      if (light) {
        if (on) this.cone(x, y + h, w, 14, 4, 'rgba(79,168,255,0.10)');
        return;
      }
      const color = ['working', 'fixing'].includes(state) ? office.palette.screenOn
        : state === 'checks' ? '#ffcc4d' : state === 'review' ? '#7bdcff'
        : ['failed', 'quota'].includes(state) ? '#ff5d73' : office.palette.screen;
      this.rect(x, y, w, h, color);
      if (['working', 'fixing'].includes(state)) {
        if (!item.lines || (!this.motion.matches && t - item.linesAt >= 400)) {
          item.lines = Array.from({length: 3}, () => 4 + Math.floor(Math.random() * 8));
          item.linesAt = t;
        }
        item.lines.forEach((width, i) => {
          this.rect(x, y + 2 + i * 2, Math.min(width, w), 1, '#c7ecff');
        });
      }
      if (state === 'checks') [2, 4].forEach(dy => this.rect(x + 1, y + dy, w - 2, 1, '#13111c'));
    }
    cone(x, y, w, h, spread, color) {
      this.ctx.fillStyle = color;
      this.ctx.beginPath();
      this.ctx.moveTo(x, y); this.ctx.lineTo(x + w, y);
      this.ctx.lineTo(x + w + spread, y + h); this.ctx.lineTo(x - spread, y + h);
      this.ctx.closePath(); this.ctx.fill();
    }
    mugPoint(p) {
      if (p.agent.role === 'main') return office.map.spots.master.mug;
      return [p.desk.desk[0] + office.furniture.desk.mug[0], p.desk.desk[1] + office.furniture.desk.mug[1]];
    }
    drawMug(p, t) {
      const [x, y] = this.mugPoint(p), pct = p.agent.quota?.remaining_pct;
      const fill = pct == null ? 0 : Math.round(6 * pct / 100);
      const colors = {...art.palettes.items};
      if (pct != null && pct < 20 && (this.motion.matches || Math.floor(t / 1000) % 2)) colors.k = '#ff5d73';
      art.items.mug.forEach((row, ry) => this.sprite([row],
        {...colors, x: ry > 6 - fill && ry <= 6 ? this.api.quotaColor(pct) : colors.x}, x, y + ry));
      if (pct >= 50) {
        const odd = this.motion.matches ? 0 : Math.floor(t / 500) % 2;
        this.rect(x + 1 + odd, y - 2 - odd, 1, 1, art.palettes.mug_fill.steam);
        this.rect(x + 3 + odd, y - 3 - odd, 1, 1, art.palettes.mug_fill.steam);
      }
    }
    drawPerson(p, t) {
      const name = art.directions[p.agent.name] ? p.agent.name : 'generic';
      const directions = art.directions[name], palette = this.api.palette(p.agent.name);
      const frame = p.pose === 'walk' && !this.motion.matches ? (Math.floor(t / 150) % 2 ? 'walkB' : 'walkA')
        : 'stand';
      const rows = p.pose === 'seat' ? directions.seated_back
        : p.pose === 'sofa' ? directions.side.stand.slice(0, 16) : directions[p.direction || 'down'][frame];
      this.sprite(rows, palette, p.pos.x, p.pos.y, p.flip);
      if (t < p.happyUntil && p.pose !== 'seat') {
        const face = art.faces.happy;
        for (const [ry, line] of Object.entries(face)) {
          [...line].forEach((pixel, rx) => {
            if (pixel !== '_' && palette[pixel]) this.rect(p.pos.x + art.faceOriginCol + rx,
              p.pos.y + Number(ry), 1, 1, palette[pixel]);
          });
        }
      }
      if (p.carry) this.sprite(art.items[p.carry], art.palettes.items, p.pos.x + 5, p.pos.y + 12);
      const states = {sleep: 'sleep', quota: 'wait', waiting: 'question', fixing: 'alert', checks: 'wait',
        review: 'question', reviewing: 'look', failed: 'fail', celebrate: 'done'};
      const emote = t < p.emoteUntil ? p.emote : states[p.agent.state];
      if (emote) this.sprite(art.emotes[emote], art.palettes.emote, p.pos.x + 12, p.pos.y - 9);
      if (!this.motion.matches) {
        if (['working', 'fixing', 'reviewing'].includes(p.agent.state) && art.particles[p.agent.name]
          && t - (p.lastParticle || 0) > 600 && p.particles.length < 3) {
          p.particles.push({born: t, x: 2 + Math.random() * 10}); p.lastParticle = t;
        }
        p.particles = p.particles.filter(item => t - item.born < 1162);
        for (const item of p.particles) this.sprite(art.particles[p.agent.name],
          art.palettes.particles[p.agent.name], p.pos.x + item.x, p.pos.y - (t - item.born) / 83);
        p.confetti = p.confetti.filter(item => t - item.born < 1000);
        for (const item of p.confetti) {
          const frame = (t - item.born) / 83;
          this.rect(Math.round(p.pos.x + 8 + item.vx * frame),
            Math.round(p.pos.y - 2 * frame + .125 * frame * frame), 1, 1, item.color);
        }
      }
      const portrait = document.getElementById(`portrait-${p.agent.name}`);
      if (portrait) {
        const ctx = portrait.getContext('2d');
        ctx.clearRect(0, 0, 32, 32);
        if (!p.blinkAt) p.blinkAt = t + 3000 + Math.random() * 2000;
        if (t >= p.blinkAt + 150) p.blinkAt = t + 3000 + Math.random() * 2000;
        const blinking = !this.motion.matches && t >= p.blinkAt;
        const face = t < p.happyUntil || p.agent.state === 'celebrate' ? 'happy'
          : ['failed', 'quota'].includes(p.agent.state) ? 'sad'
        : p.agent.state === 'sleep' || blinking ? 'blink' : 'base';
        this.api.faceRows(p.agent.name, face).forEach((row, y) => [...row].forEach((ch, x) => {
          if (ch !== '.' && palette[ch]) this.rect(x * 2, y * 2, 2, 2, palette[ch], ctx);
        }));
      }
    }
    layers(p) {
      const font = base => `${Math.max(6, base * Math.min(1, this.zoom / 2))}px`;
      p.label.style.fontSize = font(8);
      p.bubble.style.fontSize = font(10);
      p.extra.style.fontSize = font(9);
      const home = p.agent.role === 'main' ? [p.home.seated_sprite[0] + 8, p.home.seated_sprite[1] + 16 + 6]
        : [p.desk.desk[0] + 16, p.desk.seated_sprite[1] + 16 + 3];
      this.place(p.label, ...home);
      this.place(p.hit, p.pos.x, p.pos.y, 16, p.pose === 'seat' || p.pose === 'sofa' ? 16 : 24);
      this.place(p.mug, ...this.mugPoint(p), 11, 12);
      p.bubble.hidden = !p.agent.detail || ['idle', 'sleep'].includes(p.agent.state);
      p.text.textContent = p.carry ? p.carry === 'paper' ? 'llevando instrucciones' : 'entregando tarea'
        : p.agent.detail || '';
      p.bubble.style.maxWidth = `${Math.min(180, this.canvas.width)}px`;
      const [anchorX, anchorY] = this.screenPoint(p.pos.x + 8, p.pos.y - 12);
      const width = p.bubble.offsetWidth, height = p.bubble.offsetHeight;
      const left = Math.max(0, Math.min(anchorX - width / 2, this.canvas.width - width));
      const top = Math.max(height, Math.min(anchorY, this.canvas.height - 8));
      p.bubble.style.left = `${left}px`;
      p.bubble.style.top = `${top}px`;
      p.bubble.style.setProperty('--tail', `${Math.max(6, Math.min(width - 6, anchorX - left))}px`);
      [...p.minis.children].forEach((el, i) => {
        this.place(el, p.pos.x + offsets[i][0], p.pos.y + offsets[i][1], 10, 10);
      });
      this.place(p.extra, p.pos.x + 42, p.pos.y + 16);
    }
    setConfig(config) { this.config = config; }
    clock(t) {
      const now = new Date(), raw = new URLSearchParams(location.search).get('hora');
      const override = raw !== null && /^\d{1,2}$/.test(raw) && Number(raw) < 24;
      const hour = override ? Number(raw) : this.config.ui?.time_mode === 'fixed'
        ? Number(this.config.ui.fixed_hour) : now.getHours();
      const phase = hour < 6 ? 0 : hour < 12 ? 1 : hour < 17 ? 2 : hour < 20 ? 3 : 4;
      if (phase !== this.phase) { this.previous = this.phase; this.phase = phase; this.phaseStarted = t; }
      document.getElementById('day-phase').textContent = `· ${phases[phase].label}`;
      document.getElementById('day-time').textContent =
        ` · ${String(hour).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
      return phase;
    }
    daylight(t, monitors) {
      const phase = this.clock(t), current = phases[phase], previous = phases[this.previous ?? phase];
      const amount = this.motion.matches || this.previous == null ? 1 : Math.min(1, (t - this.phaseStarted) / 2000);
      const mix = (a, b) => a.map((v, i) => v + (b[i] - v) * amount);
      this.rect(0, 0, this.world.width, this.world.height,
        `rgba(${mix(previous.overlay, current.overlay).join(',')})`);
      const rgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
      for (const item of office.map.placements.filter(item => item.kind === 'window')) {
        for (const [sx, sy, w, h] of office.furniture.window.sky) {
          [4, 3, h - 7].forEach((height, i) => this.rect(item.x + sx, item.y + sy + [0, 4, 7][i], w, height,
            `rgb(${mix(rgb(previous.sky[i]), rgb(current.sky[i])).join(',')})`));
        }
      }
      const night = phase === 0 || phase === 4;
      for (const {item, state} of monitors) if (night) this.screen(item, state, t, true);
      const lamp = office.map.placements.find(item => item.role === 'night_lamp');
      const [x, y, w, h] = office.furniture.lamp.bulb;
      if (night) this.cone(lamp.x + 1, lamp.y + h, 6, 40, 7, 'rgba(255,215,94,0.12)');
      this.rect(lamp.x + x, lamp.y + y, w, h, night ? '#ffd75e' : office.palette.cream);
    }
    draw(t) {
      if (document.hidden) { this.raf = null; return; }
      if (t - this.last >= 1000 / 12) {
        const delta = Math.min(250, this.last ? t - this.last : 0);
        this.last = t;
        const occupied = new Set();
        for (const p of this.people.values()) {
          const desired = this.desired(p, occupied);
          if (!p.busy && !p.path.length && t - p.changed >= 2000 && p.destination !== desired.id) {
            this.go(p, desired);
          }
          this.advance(p, t, delta);
        }
        this.ctx.drawImage(this.floor, 0, 0);
        const jobs = [], monitors = [];
        const master = [...this.people.values()].find(p => p.agent.role === 'main');
        for (const item of office.map.placements) {
          jobs.push({x: item.x, z: item.z ?? item.y + office.furniture[item.kind].h, draw: () => {
            this.furniture(item);
            if (item.role === 'master_laptop') this.screen(item, master?.agent.state, t);
          }});
          if (item.role === 'master_laptop') monitors.push({item, state: master?.agent.state});
        }
        office.map.desks.forEach(desk => {
          const person = [...this.people.values()].find(p => p.desk === desk);
          if (!desk.monitor) desk.monitor = {kind: 'desk', x: desk.desk[0], y: desk.desk[1]};
          const item = desk.monitor;
          jobs.push({x: item.x, z: item.y + office.furniture.desk.h,
            draw: () => { this.furniture(item); this.screen(item, person?.agent.state, t); }});
          const stool = {kind: 'stool', x: desk.stool[0], y: desk.stool[1]};
          jobs.push({x: stool.x, z: stool.y + office.furniture.stool.h, draw: () => this.furniture(stool)});
          monitors.push({item, state: person?.agent.state});
        });
        for (const p of this.people.values()) {
          const z = p.pose === 'sofa' ? p.sofa.y + office.furniture.sofa.h + 1
            : p.pose === 'seat' ? p.agent.role === 'main' ? 129
              : p.desk.stool[1] + office.furniture.stool.h + 1 : p.pos.y + 24;
          jobs.push({x: p.pos.x, z, draw: () => this.drawPerson(p, t)});
          const mug = this.mugPoint(p);
          jobs.push({x: mug[0], z: p.agent.role === 'main' ? 114 : p.desk.desk[1] + 23,
            draw: () => this.drawMug(p, t)});
          offsets.slice(0, p.miniCount).forEach(([dx, dy]) => jobs.push({x: p.pos.x + dx,
            z: p.pos.y + dy + 10, draw: () => this.sprite(art.mini, this.api.palette(p.agent.name),
              p.pos.x + dx, p.pos.y + dy)}));
          p.puffs = p.puffs.filter(puff => t - puff.born < 300);
          if (!this.motion.matches) for (const puff of p.puffs) jobs.push({x: p.pos.x, z: z + 1,
            draw: () => this.sprite(art.items.puff, art.palettes.items,
              p.pos.x + offsets[puff.i][0], p.pos.y + offsets[puff.i][1])});
          this.layers(p);
        }
        jobs.sort((a, b) => a.z - b.z || a.x - b.x).forEach(job => job.draw());
        this.daylight(t, monitors);
        const shown = [];
        for (const p of this.people.values()) {
          p.bubble.style.opacity = '1';
          if (p.bubble.hidden) continue;
          const bounds = p.bubble.getBoundingClientRect();
          if (shown.some(a => a.left < bounds.right && a.right > bounds.left
            && a.top < bounds.bottom && a.bottom > bounds.top)) p.bubble.style.opacity = '0';
          else shown.push(bounds);
        }
        for (const {label, x, y} of this.roomLabels) {
          label.style.fontSize = `${Math.max(6, 8 * Math.min(1, this.zoom / 2))}px`;
          this.place(label, x, y);
        }
        this.output.clearRect(0, 0, this.canvas.width, this.canvas.height);
        const [x, y] = this.screenPoint(0, 0);
        this.output.drawImage(this.world, x, y, this.world.width * this.zoom, this.world.height * this.zoom);
      }
      this.raf = requestAnimationFrame(time => this.draw(time));
    }
    visibility() {
      if (document.hidden) {
        if (this.raf) cancelAnimationFrame(this.raf);
        this.raf = null;
      } else if (!this.raf) {
        for (const p of this.people.values()) p.queue = p.queue.slice(-3);
        this.last = 0;
        this.raf = requestAnimationFrame(t => this.draw(t));
      }
    }
  }
  window.OfficeEngine = OfficeEngine;
})();
