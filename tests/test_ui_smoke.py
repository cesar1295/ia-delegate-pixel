"""Smoke test que ejecuta la UI real con Node.js en un DOM simulado."""

import copy
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from aidelegate import config, ui_state
from aidelegate.runs import RunMeta


def test_ui_smoke_with_node(tmp_path):
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("node no está disponible")

    now = datetime(2026, 10, 4, 15, 0, 0)
    cfg = copy.deepcopy(config.DEFAULTS)

    # Crear corridas falsas con usage, time y cuota nula (ej: agy con presupuesto 0)
    metas = [
        RunMeta(
            run_id="run-smoke-01",
            agent="codex",
            mode="write",
            kind="feature",
            repo="mi-repo",
            source_dir="",
            workdir="",
            task="tarea codex",
            status="running",
            history=[
                {
                    "label": "tarea",
                    "agent": "codex",
                    "seconds": 45.0,
                    "ts": now.isoformat(),
                    "usage": {
                        "input_tokens": 1200,
                        "cached_input_tokens": 400,
                        "output_tokens": 150,
                    },
                }
            ],
        ),
        RunMeta(
            run_id="run-smoke-02",
            agent="agy",
            mode="write",
            kind="test",
            repo="mi-repo",
            source_dir="",
            workdir="",
            task="tarea agy",
            status="listo-para-revisar",
            history=[
                {
                    "label": "tarea",
                    "agent": "agy",
                    "seconds": 20.0,
                    "ts": now.isoformat(),
                    "usage": {
                        "input_tokens": 600,
                        "output_tokens": 80,
                    },
                }
            ],
        ),
    ]

    state = ui_state.build_state(metas, None, [], now=now, cfg=cfg)

    # Verificar que las condiciones pedidas están en el estado generado
    has_null_quota = any(a.get("quota", {}).get("remaining_pct") is None for a in state["agents"])
    assert has_null_quota, "Debe haber al menos un agente con cuota remaining_pct null"
    has_usage = any(a.get("usage", {}).get("tokens_today") is not None for a in state["agents"])
    assert has_usage, "Debe haber agentes con usage"
    has_time = any(a.get("time") is not None for a in state["agents"])
    assert has_time, "Debe haber agentes con time"

    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state, ensure_ascii=False))

    static_dir = Path(__file__).resolve().parent.parent / "aidelegate/ui/static"
    runner_script = tmp_path / "smoke_runner.js"

    js_code = r"""
const fs = require('fs');
const path = require('path');

const staticDir = process.argv[2];
const stateFile = process.argv[3];
const stateData = JSON.parse(fs.readFileSync(stateFile, 'utf8'));

function createMockElement(tag, id = '', className = '') {
  const listeners = {};
  const attrs = {};
  const classes = new Set(className ? className.split(/\s+/) : []);
  const styleObj = {
    _map: {},
    setProperty(k, v) { this._map[k] = v; this[k] = v; },
    getPropertyValue(k) { return this._map[k] || this[k] || ''; }
  };
  const el = {
    tagName: tag.toUpperCase(),
    id: id || '',
    className: className || '',
    dataset: {},
    hidden: false,
    disabled: false,
    checked: false,
    inert: false,
    value: '',
    children: [],
    style: styleObj,
    clientWidth: 800,
    clientHeight: 600,
    width: 800,
    height: 600,
    classList: {
      add(...cs) { cs.forEach(c => classes.add(c)); el.className = [...classes].join(' '); },
      remove(...cs) { cs.forEach(c => classes.delete(c)); el.className = [...classes].join(' '); },
      toggle(c, force) {
        let res;
        if (force === undefined) {
          if (classes.has(c)) { classes.delete(c); res = false; }
          else { classes.add(c); res = true; }
        } else {
          if (force) classes.add(c); else classes.delete(c);
          res = force;
        }
        el.className = [...classes].join(' ');
        return res;
      },
      contains(c) { return classes.has(c); }
    },
    setAttribute(k, v) { attrs[k] = String(v); el[k] = v; },
    getAttribute(k) { return attrs[k] ?? el[k] ?? null; },
    removeAttribute(k) { delete attrs[k]; delete el[k]; },
    addEventListener(event, fn) { (listeners[event] = listeners[event] || []).push(fn); },
    removeEventListener(event, fn) {
      if (listeners[event]) listeners[event] = listeners[event].filter(f => f !== fn);
    },
    dispatchEvent(ev) {
      const fns = listeners[ev.type] || [];
      fns.forEach(fn => fn(ev));
    },
    append(...args) {
      for (const a of args) {
        if (typeof a === 'string') {
          const t = createMockElement('#text');
          t.textContent = a;
          t.parentNode = el;
          el.children.push(t);
        } else if (a) {
          a.parentNode = el;
          el.children.push(a);
        }
      }
    },
    replaceChildren(...args) {
      el.children = [];
      el.append(...args);
    },
    querySelector(sel) {
      return null;
    },
    querySelectorAll(sel) {
      return [];
    },
    getBoundingClientRect() {
      return { left: 0, top: 0, width: el.clientWidth || 800, height: el.clientHeight || 600, right: 800, bottom: 600 };
    },
    focus() {},
    blur() {},
    setPointerCapture() {},
    releasePointerCapture() {}
  };

  let _textContent = '';
  Object.defineProperty(el, 'textContent', {
    get() { return _textContent; },
    set(v) {
      _textContent = String(v);
      el.children = [];
    }
  });

  if (tag.toLowerCase() === 'canvas') {
    const ctx = {
      canvas: el,
      fillStyle: '#000000',
      imageSmoothingEnabled: false,
      fillRect() {},
      clearRect() {},
      drawImage() {},
      createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
      getImageData(x, y, w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
      putImageData() {},
      save() {},
      restore() {},
      scale() {},
      translate() {},
      beginPath() {},
      closePath() {},
      stroke() {},
      fill() {},
      rect() {},
      arc() {},
      measureText(text) { return { width: (text || '').length * 6 }; }
    };
    el.getContext = () => ctx;
  }

  return el;
}

const elementsById = {};
const ids = [
  'office-canvas', 'scene', 'scene-layers', 'zoom-out', 'zoom-in',
  'day-phase', 'day-time', 'running-count', 'review-count', 'merged-count',
  'connection', 'connection-text', 'team', 'runs', 'stats', 'settings',
  'settings-open', 'sheet-counts', 'side-panel', 'team-panel', 'runs-panel',
  'stats-panel', 'settings-panel', 'modal-overlay', 'detail-panel',
  'detail-content', 'close-detail', 'top-counts', 'panel-content'
];
ids.forEach(id => {
  const tag = (id === 'office-canvas') ? 'canvas' : (id.includes('zoom') || id.includes('close') ? 'button' : 'div');
  elementsById[id] = createMockElement(tag, id);
});

const tabButtons = ['team', 'runs', 'stats', 'settings'].map(tab => {
  const btn = createMockElement('button');
  btn.dataset.tab = tab;
  btn.setAttribute('data-tab', tab);
  return btn;
});

const officeEl = createMockElement('div', '', 'office');
const docListeners = {};

const mockDoc = {
  hidden: false,
  createElement(tag) { return createMockElement(tag); },
  getElementById(id) {
    if (!elementsById[id]) {
      elementsById[id] = createMockElement(id.startsWith('portrait') ? 'canvas' : 'div', id);
    }
    return elementsById[id];
  },
  querySelector(sel) {
    if (sel === '.office') return officeEl;
    return null;
  },
  querySelectorAll(sel) {
    if (sel === '[data-tab]') return tabButtons;
    return [];
  },
  addEventListener(event, fn) {
    (docListeners[event] = docListeners[event] || []).push(fn);
  },
  removeEventListener(event, fn) {
    if (docListeners[event]) docListeners[event] = docListeners[event].filter(f => f !== fn);
  },
  dispatchEvent(ev) {
    (docListeners[ev.type] || []).forEach(f => f(ev));
  }
};

global.window = global;
global.document = mockDoc;
global.location = { search: '' };
global.localStorage = {
  _s: {},
  getItem(k) { return this._s[k] || null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
  clear() { this._s = {}; }
};
global.matchMedia = () => ({
  matches: false,
  addEventListener() {},
  removeEventListener() {}
});
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
global.requestAnimationFrame = cb => setTimeout(cb, 16);
global.cancelAnimationFrame = id => clearTimeout(id);
global.performance = { now: () => Date.now() };
global.fetch = () => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(stateData)
});

const files = ['sprites.js', 'office.js', 'engine.js', 'panels.js', 'app.js'];
for (const file of files) {
  const filePath = path.join(staticDir, file);
  const code = fs.readFileSync(filePath, 'utf8');
  eval(code);
}

if (typeof window.render !== 'function') {
  throw new Error('window.render no está definido como función');
}

// Llamar a render con el estado real
window.render(stateData);

console.log('UI_SMOKE_OK');
process.exit(0);
"""
    runner_script.write_text(js_code, encoding="utf-8")

    res = subprocess.run(
        [node_bin, str(runner_script), str(static_dir), str(state_file)],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        pytest.fail(f"Fallo en node runner:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

    assert "UI_SMOKE_OK" in res.stdout
