"""
Clawtonomy — Multi-Model Adversarial Room + Experiment Runner
OpenClaw / KERF — AnnulusLabs LLC — 2026-03-16

Rooms: parallel, adversarial, round-robin, snowball
Experiments: autoresearch-style overnight runs with local models
Memory: KERF genome context injection
Session: boot, provenance, postmortem

No webapp. TUI only. ANSI color-coded.
"""
from __future__ import annotations

import hashlib, json, os, socket, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Config ────────────────────────────────────────────────────────────────

KERF_API      = os.environ.get('KERF_API', 'http://127.0.0.1:8767')
OLLAMA_API    = os.environ.get('OLLAMA_API', 'http://127.0.0.1:11434')
DATA_DIR      = Path(os.environ.get('CLAWTONOMY_DATA', 'A:/AI/KERF/.kerf'))
ROOMS_DIR     = DATA_DIR / 'rooms'
POSTMORTEM_DIR = DATA_DIR / 'postmortems'
EXPERIMENT_DIR = DATA_DIR / 'experiments'
PROVENANCE_LOG = DATA_DIR / 'provenance.jsonl'
STATE_FILE    = DATA_DIR / 'session_state.json'
LOCK_FILE     = Path(tempfile.gettempdir()) / 'clawtonomy.lock'
BOOT_WINDOW   = 3600

SERVICES = {
    11434: ('Ollama', 'local LLM'),
    18789: ('OpenClaw', 'agent orchestration'),
    8767:  ('KERF', 'genome memory'),
    8795:  ('Adversarial', 'multi-agent debate'),
}

BLOCKLIST = {
    'Clear-Disk': 'wipes partition tables',
    'Disable-PnpDevice': 'bricks USB drivers',
    'USB Root Hub': 'kills ALL USB',
    'dd if=': 'raw disk write', 'dd of=': 'raw disk write',
    'diskpart': 'destroys partitions', 'rm -rf /': 'recursive root delete',
}

DISCIPLINES = [
    'RF/microwave', 'spectroscopy', 'electrochemistry', 'crystallography',
    'materials science', 'nuclear physics', 'magnetism', 'biology',
    'acoustics', 'thermal analysis', 'astronomy', 'optics',
    'additive manufacturing', 'chaos theory', 'quantum computing',
]

RST = '\033[0m'; B = '\033[1m'; D = '\033[2m'
COLORS = {
    'claude': '\033[38;2;0;255;136m', 'hermes3': '\033[38;2;255;153;51m',
    'llama3': '\033[38;2;51;204;255m', 'codestral': '\033[38;2;255;51;102m',
    'deepseek-r1': '\033[38;2;204;102;255m', 'deepseek-coder': '\033[38;2;153;51;255m',
    'qwen': '\033[38;2;255;204;0m', 'mistral': '\033[38;2;102;255;204m',
    'gemma': '\033[38;2;255;102;153m', 'dolphin': '\033[38;2;102;119;170m',
    'devstral': '\033[38;2;255;85;51m', 'phi': '\033[38;2;255;170;102m',
    'human': '\033[38;2;255;255;255m', 'system': '\033[38;2;100;100;100m',
}

def _c(mid):
    for k, v in COLORS.items():
        if k in (mid or '').lower(): return v
    return '\033[38;2;180;180;180m'

def _s(mid):
    if not mid: return '??'
    n = mid.split('/')[-1]
    if ':' in n:
        b, t = n.split(':', 1)
        return b if t in ('latest', '8b', '7b') else f'{b}:{t[:3]}'
    return n

def out(mid, text, pfx=None):
    c = _c(mid); n = pfx or _s(mid); ts = datetime.now().strftime('%H:%M:%S')
    print(f'{D}{ts}{RST} {c}{B}{n:>14}{RST} {c}{text}{RST}')

# ── Ollama ────────────────────────────────────────────────────────────────

def _ollama_post(endpoint, payload, timeout=120):
    try:
        req = urllib.request.Request(
            f'{OLLAMA_API}{endpoint}', data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception as e:
        return {'error': str(e)}

def chat(model, messages, timeout=120):
    r = _ollama_post('/api/chat', {'model': model, 'messages': messages, 'stream': False}, timeout)
    return r.get('message', {}).get('content', '').strip() if 'error' not in r else f'[ERROR] {r["error"]}'

def generate(model, prompt, timeout=120):
    r = _ollama_post('/api/generate', {'model': model, 'prompt': prompt, 'stream': False}, timeout)
    return r.get('response', '').strip() if 'error' not in r else f'[ERROR] {r["error"]}'

def models():
    try:
        r = json.loads(urllib.request.urlopen(f'{OLLAMA_API}/api/tags', timeout=5).read())
        return [m['name'] for m in r.get('models', [])]
    except Exception: return []

# ── KERF Memory ───────────────────────────────────────────────────────────

def nucleus(tier=0):
    try:
        r = json.loads(urllib.request.urlopen(f'{KERF_API}/compile?tier={tier}', timeout=5).read())
        return r.get('compiled', '')
    except Exception: return ''

def remember(content, source='agent', because=None):
    try:
        req = urllib.request.Request(f'{KERF_API}/write',
            data=json.dumps({'content': content, 'source': source, 'because': because}).encode(),
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except Exception: pass

# ── Infra ─────────────────────────────────────────────────────────────────

def port_up(p):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3); return s.connect_ex(('127.0.0.1', p)) == 0
    except Exception: return False

def scan(): return {n: port_up(p) for p, (n, _) in SERVICES.items()}

def blocked(text):
    for pat, why in BLOCKLIST.items():
        if pat in text: return f'BLOCKED: "{pat}" — {why}'
    return None

def provenance(event, detail='', extra=None):
    e = {'ts': datetime.now().isoformat(), 'event': event, 'detail': detail[:200]}
    if extra: e.update(extra)
    try:
        PROVENANCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PROVENANCE_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(e, default=str) + '\n')
    except Exception: pass

# ── Session ───────────────────────────────────────────────────────────────

class Session:
    def __init__(self):
        self.d = {
            'id': hashlib.blake2b(f'{time.time()}:{os.getpid()}'.encode(), digest_size=8).hexdigest(),
            'started': datetime.now().isoformat(), 'prompts': 0,
            'models': [], 'rooms': [], 'errors': [], 'history': [],
        }
        self._load()

    def _load(self):
        try:
            if STATE_FILE.exists():
                s = json.loads(STATE_FILE.read_text(encoding='utf-8'))
                self.d['history'] = s.get('history', [])[-200:]
        except Exception: pass

    def save(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self.d, indent=2, default=str), encoding='utf-8')
        except Exception: pass

    def record(self, room, mode, mdls, prompt):
        self.d['prompts'] += 1
        for m in mdls:
            if m not in self.d['models']: self.d['models'].append(m)
        if room not in self.d['rooms']: self.d['rooms'].append(room)
        self.d['history'].append({'ts': datetime.now().isoformat(), 'room': room,
                                   'mode': mode, 'models': [_s(m) for m in mdls], 'prompt': prompt[:100]})
        if len(self.d['history']) > 200: self.d['history'] = self.d['history'][-100:]
        self.save()

    def summary(self):
        return {k: self.d[k] for k in ('id', 'started', 'prompts')} | {
            'models': len(self.d['models']), 'rooms': self.d['rooms'], 'errors': len(self.d['errors'])}

def boot() -> Tuple[Session, bool]:
    first = True
    try:
        if LOCK_FILE.exists() and time.time() - LOCK_FILE.stat().st_mtime < BOOT_WINDOW:
            first = False
        if first: LOCK_FILE.write_text(str(time.time()))
    except Exception: pass
    s = Session()
    if first:
        svcs = scan(); s.d['services'] = svcs; s.save()
        provenance('boot', f'id={s.d["id"]}', {'services': svcs})
        out('system', f'Session {s.d["id"]}')
        up = [n for n, v in svcs.items() if v]
        if up: out('system', f'UP: {", ".join(up)}')
    return s, first

# ── Postmortem ────────────────────────────────────────────────────────────

class Postmortem:
    def __init__(self, session, mgr):
        self.session = session; self.mgr = mgr

    def gather(self):
        rooms = {n: {'models': r.mdls, 'mode': r.mode, 'msgs': len(r.history)}
                 for n, r in self.mgr.rooms.items()}
        return {'ts': datetime.now().isoformat(), 'id': self.session.d['id'],
                'prompts': self.session.d['prompts'], 'models': self.session.d['models'],
                'rooms': rooms, 'history': self.session.d['history'][-20:]}

    def _text(self, d):
        lines = [f"Session {d['id']}", f"Prompts: {d['prompts']}, Models: {', '.join(d['models'][:6])}"]
        for n, r in d['rooms'].items():
            lines.append(f"  {n}: {r['mode']}, {r['msgs']} msgs")
        return '\n'.join(lines)

    def run(self, mdls=None):
        mdls = mdls or ['hermes3:8b', 'mistral:latest']
        data = self.gather(); txt = self._text(data)
        idx = datetime.now().timetuple().tm_yday % len(DISCIPLINES)
        results = {'data': data, 'analyses': {}, 'brainstorms': {}}
        for m in mdls:
            out(m, 'analyzing...')
            results['analyses'][m] = generate(m, f"Analyze this session. What worked, what to improve, one takeaway. <150 words.\n\n{txt}", 60)
            out(m, 'brainstorming...')
            results['brainstorms'][m] = generate(m, f"3 invention ideas for next session combining AI + {DISCIPLINES[idx]}.\n\n{txt}\n\nName + 2 sentences each.", 60)

        now = datetime.now()
        L = [f"# Postmortem: {now:%Y-%m-%d %H:%M}", f"*{data['id']} | {data['prompts']} prompts*\n", txt, '']
        for m, t in results['analyses'].items():
            if t and '[ERROR]' not in t: L += [f'### {m}', t.strip(), '']
        for m, t in results['brainstorms'].items():
            if t and '[ERROR]' not in t: L += [f'### {m} ideas', t.strip(), '']
        L += [f'Focus: {DISCIPLINES[idx]}, {DISCIPLINES[(idx+1)%len(DISCIPLINES)]}',
              '', '---', f'*AnnulusLabs — {now.isoformat()}*']

        POSTMORTEM_DIR.mkdir(parents=True, exist_ok=True)
        p = POSTMORTEM_DIR / f"{now:%Y-%m-%d_%H%M%S}.md"
        p.write_text('\n'.join(L), encoding='utf-8')
        for m, t in results['analyses'].items():
            if t and '[ERROR]' not in t:
                remember(f'[postmortem/{m}] {t[:300]}', 'postmortem', f'session {data["id"]}')
        provenance('postmortem', str(p))
        try: LOCK_FILE.unlink(missing_ok=True)
        except Exception: pass
        return p

    def quick(self): return self.gather()

# ── Experiment Runner (tree-search autoresearch) ─────────────────────────

class ExperimentRunner:
    """Tree-search autoresearch: best-first expansion, multi-model ensemble,
    stateless summarization, results.tsv accumulation, overnight loop."""

    def __init__(self, work_dir: str, program_md: str = '',
                 fast_model: str = 'hermes3:8b', deep_model: str = 'mistral:latest',
                 train_cmd: str = 'python train.py', timeout_s: int = 300):
        self.work_dir = Path(work_dir)
        self.program = program_md
        self.fast = fast_model; self.deep = deep_model
        self.train_cmd = train_cmd; self.timeout_s = timeout_s
        # Tree: list of nodes {id, parent, hypothesis, code, val_bpb, status, metrics}
        self.tree: List[dict] = []
        self.failures: List[str] = []
        self.log_file = EXPERIMENT_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}.jsonl"
        self.tsv = self.work_dir / 'results.tsv'
        self._ensure_tsv()
        # Seed node 0: baseline (current train.py)
        train_py = self.work_dir / 'train.py'
        baseline = train_py.read_text(encoding='utf-8') if train_py.exists() else ''
        self.tree.append({'id': 0, 'parent': -1, 'hypothesis': 'baseline',
                          'code': baseline, 'val_bpb': None, 'status': 'seed',
                          'metrics': {}})

    # ── helpers ───────────────────────────────────────────────────────

    def _ensure_tsv(self):
        if not self.tsv.exists():
            self.tsv.write_text('id\tparent\thypothesis\tval_bpb\tstatus\tkept\n',
                                encoding='utf-8')
        gi = self.work_dir / '.gitignore'
        if gi.exists():
            txt = gi.read_text(encoding='utf-8')
            if 'results.tsv' not in txt:
                gi.write_text(txt.rstrip() + '\nresults.tsv\n', encoding='utf-8')

    def _append_tsv(self, node, kept):
        try:
            with open(self.tsv, 'a', encoding='utf-8') as f:
                h = node['hypothesis'].replace('\t', ' ')[:80]
                f.write(f"{node['id']}\t{node['parent']}\t{h}\t"
                        f"{node['val_bpb']}\t{node['status']}\t{kept}\n")
        except Exception: pass

    def _log(self, entry):
        try:
            EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, default=str) + '\n')
        except Exception: pass

    def _best_node(self) -> dict:
        """Best-first: node with lowest val_bpb, or seed."""
        scored = [n for n in self.tree if n.get('val_bpb') is not None]
        return min(scored, key=lambda n: n['val_bpb']) if scored else self.tree[0]

    def _extract_metrics(self, stdout: str, stderr: str, rc: int) -> dict:
        """Stateless summarization: parse stdout into compact metrics dict."""
        m: dict = {'returncode': rc}
        losses = []
        for line in stdout.splitlines():
            low = line.lower()
            if 'val_bpb' in low:
                try: m['val_bpb'] = float(line.split('=')[-1].strip().split()[0])
                except Exception: pass
            if 'param' in low:
                try:
                    for tok in line.replace(',', '').split():
                        if tok.isdigit() and int(tok) > 1000:
                            m['params'] = int(tok); break
                except Exception: pass
            if 'loss' in low:
                try:
                    v = float(line.split('=')[-1].strip().split()[0])
                    losses.append(v)
                except Exception: pass
        if losses:
            m['loss_first'] = losses[0]; m['loss_last'] = losses[-1]
            m['loss_delta'] = losses[-1] - losses[0]
        if stderr and rc != 0: m['error_tail'] = stderr[-200:]
        return m

    def _metrics_summary(self, node: dict) -> str:
        """One-line metrics string for LLM prompts."""
        m = node.get('metrics', {})
        parts = []
        if node.get('val_bpb') is not None: parts.append(f"val_bpb={node['val_bpb']:.4f}")
        if 'params' in m: parts.append(f"params={m['params']}")
        if 'loss_first' in m: parts.append(f"loss {m['loss_first']:.3f}->{m['loss_last']:.3f}")
        return ', '.join(parts) or 'no metrics'

    def _failure_digest(self, n=5) -> str:
        if not self.failures: return ''
        return 'Recent failures:\n' + '\n'.join(f'- {f}' for f in self.failures[-n:])

    # ── hypothesis generation ─────────────────────────────────────────

    def gen_hypotheses(self, n: int = 4) -> List[str]:
        """Auto-generate hypotheses: fast model from program + best + failures."""
        best = self._best_node()
        prompt = (
            f"You are an ML researcher. Given the program spec and current best result, "
            f"propose exactly {n} distinct hypotheses to improve val_bpb. "
            f"Each hypothesis is one line, actionable, specific to code changes.\n\n"
            f"Program:\n{self.program[:800]}\n\n"
            f"Current best: {self._metrics_summary(best)} (node {best['id']})\n"
            f"{self._failure_digest()}\n\n"
            f"Output {n} lines, one hypothesis per line, nothing else."
        )
        raw = generate(self.fast, prompt, timeout=60)
        if '[ERROR]' in raw: return []
        return [h.strip().lstrip('0123456789.-) ') for h in raw.strip().splitlines()
                if h.strip() and len(h.strip()) > 10][:n]

    def pick_best_hypothesis(self, candidates: List[str]) -> str:
        """Deep model ranks candidates, returns the best one."""
        if len(candidates) <= 1: return candidates[0] if candidates else ''
        best = self._best_node()
        numbered = '\n'.join(f'{i+1}. {h}' for i, h in enumerate(candidates))
        prompt = (
            f"You are selecting the single best hypothesis to try next.\n\n"
            f"Program:\n{self.program[:600]}\n\n"
            f"Current best: {self._metrics_summary(best)}\n"
            f"{self._failure_digest(3)}\n\n"
            f"Candidates:\n{numbered}\n\n"
            f"Reply with ONLY the number of the best candidate."
        )
        pick = generate(self.deep, prompt, timeout=60)
        try:
            idx = int(''.join(c for c in pick if c.isdigit())) - 1
            if 0 <= idx < len(candidates): return candidates[idx]
        except Exception: pass
        return candidates[0]

    # ── core experiment step ──────────────────────────────────────────

    def run_one(self, hypothesis: str, model: str = '') -> dict:
        """Branch from best node, propose code, train, eval, keep/revert."""
        import subprocess
        model = model or self.deep
        parent = self._best_node()
        nid = len(self.tree)
        out(model, f'[{nid}] Hypothesis: {hypothesis[:80]}')
        out('system', f'  branching from node {parent["id"]} ({self._metrics_summary(parent)})')

        # Generate patched code
        patch = generate(model, (
            f"You are modifying train.py for an ML experiment.\n\n"
            f"Program constraints:\n{self.program[:1000]}\n\n"
            f"Hypothesis: {hypothesis}\n\n"
            f"Current train.py (from best node {parent['id']}, "
            f"{self._metrics_summary(parent)}):\n"
            f"```python\n{parent['code'][:3000]}\n```\n\n"
            f"Output ONLY the complete modified train.py, no explanation."
        ), timeout=120)

        if '[ERROR]' in patch:
            node = {'id': nid, 'parent': parent['id'], 'hypothesis': hypothesis,
                    'code': parent['code'], 'val_bpb': None, 'status': 'gen_error',
                    'metrics': {'error': patch[:200]}}
            self.tree.append(node); self._log(node)
            self.failures.append(f'{hypothesis[:60]}: generation error')
            self._append_tsv(node, False); return node

        # Write code and train
        train_py = self.work_dir / 'train.py'
        train_py.write_text(patch, encoding='utf-8')
        out('system', f'  training ({self.timeout_s}s budget)...')

        try:
            r = subprocess.run(self.train_cmd.split(), cwd=str(self.work_dir),
                               capture_output=True, text=True, timeout=self.timeout_s)
            stdout = r.stdout[-2000:] if r.stdout else ''
            stderr = r.stderr[-500:] if r.stderr else ''
        except subprocess.TimeoutExpired:
            train_py.write_text(parent['code'], encoding='utf-8')
            node = {'id': nid, 'parent': parent['id'], 'hypothesis': hypothesis,
                    'code': patch, 'val_bpb': None, 'status': 'timeout', 'metrics': {}}
            self.tree.append(node); self._log(node)
            self.failures.append(f'{hypothesis[:60]}: timeout')
            self._append_tsv(node, False); return node
        except Exception as e:
            train_py.write_text(parent['code'], encoding='utf-8')
            node = {'id': nid, 'parent': parent['id'], 'hypothesis': hypothesis,
                    'code': patch, 'val_bpb': None, 'status': 'error',
                    'metrics': {'error': str(e)[:200]}}
            self.tree.append(node); self._log(node)
            self.failures.append(f'{hypothesis[:60]}: {e}')
            self._append_tsv(node, False); return node

        metrics = self._extract_metrics(stdout, stderr, r.returncode)
        val_bpb = metrics.get('val_bpb')
        status = 'ok' if r.returncode == 0 else 'fail'
        node = {'id': nid, 'parent': parent['id'], 'hypothesis': hypothesis,
                'code': patch, 'val_bpb': val_bpb, 'status': status, 'metrics': metrics}
        self.tree.append(node); self._log(node)

        # Keep or revert — compare against parent (best node)
        prev_best = parent.get('val_bpb')
        improved = (val_bpb is not None and r.returncode == 0 and
                    (prev_best is None or val_bpb < prev_best))
        if improved:
            out('system', f'  KEPT node {nid} (val_bpb={val_bpb} < prev={prev_best})')
            self._append_tsv(node, True)
            try:
                subprocess.run(['git', 'add', 'train.py'], cwd=str(self.work_dir),
                               capture_output=True, timeout=10)
                msg = f"exp[{nid}]: {hypothesis[:50]} | val_bpb={val_bpb}"
                subprocess.run(['git', 'commit', '-m', msg], cwd=str(self.work_dir),
                               capture_output=True, timeout=10)
            except Exception: pass
        else:
            train_py.write_text(parent['code'], encoding='utf-8')
            out('system', f'  reverted (val_bpb={val_bpb}, best={prev_best})')
            self._append_tsv(node, False)
            if hypothesis: self.failures.append(f'{hypothesis[:60]}: val_bpb={val_bpb}')

        return node

    # ── ensemble step: fast proposes, deep refines ────────────────────

    def ensemble_step(self, n_candidates: int = 4) -> dict:
        """One ensemble cycle: fast model proposes N, deep picks+runs one."""
        candidates = self.gen_hypotheses(n_candidates)
        if not candidates:
            out('system', 'No hypotheses generated'); return {}
        out(self.fast, f'Proposed {len(candidates)} hypotheses')
        for i, h in enumerate(candidates): out('system', f'  {i+1}. {h[:80]}')
        best_h = self.pick_best_hypothesis(candidates)
        out(self.deep, f'Selected: {best_h[:80]}')
        return self.run_one(best_h)

    # ── overnight auto loop ───────────────────────────────────────────

    def auto_loop(self, hours: float = 8.0, n_per_cycle: int = 4):
        """Unattended loop: generate, run, keep improvements, for N hours."""
        deadline = time.time() + hours * 3600
        cycle = 0
        out('system', f'Auto-loop: {hours}h, {n_per_cycle} candidates/cycle')
        provenance('experiment_auto_start', f'{self.work_dir} {hours}h')
        while time.time() < deadline:
            cycle += 1
            remaining = (deadline - time.time()) / 3600
            out('system', f'--- cycle {cycle} ({remaining:.1f}h left) ---')
            result = self.ensemble_step(n_per_cycle)
            if not result: break
            remember(f'[exp cycle {cycle}] {result.get("hypothesis","?")[:60]} '
                     f'val_bpb={result.get("val_bpb")} status={result.get("status")}',
                     'experiment', f'auto-loop {self.work_dir}')
        out('system', f'Auto-loop done: {cycle} cycles')
        provenance('experiment_auto_end', self.summary())

    # ── reporting ─────────────────────────────────────────────────────

    def summary(self) -> str:
        scored = [n for n in self.tree if n.get('val_bpb') is not None]
        if not scored: return f'{len(self.tree)} nodes, none with metrics.'
        best = min(scored, key=lambda n: n['val_bpb'])
        return (f"{len(self.tree)} nodes, {len(scored)} scored, "
                f"{len(self.failures)} failures. "
                f"Best val_bpb={best['val_bpb']:.4f} node {best['id']} "
                f"({best['hypothesis'][:50]})")

    def tree_view(self) -> str:
        """Compact tree display for TUI."""
        lines = []
        for n in self.tree:
            star = '*' if n == self._best_node() and n.get('val_bpb') else ' '
            bpb = f"{n['val_bpb']:.4f}" if n.get('val_bpb') is not None else '  n/a '
            lines.append(f" {star} [{n['id']:>3}]<-[{n['parent']:>3}] "
                         f"{bpb} {n['status']:>8}  {n['hypothesis'][:50]}")
        return '\n'.join(lines)

# ── Room ──────────────────────────────────────────────────────────────────

class Room:
    MODES = ('round-robin', 'adversarial', 'parallel', 'snowball', 'sparse', 'free-mad')

    def __init__(self, name='default'):
        self.name = name; self.mdls: List[str] = []; self.mode = 'parallel'
        self.history: List[dict] = []; self.ctx = ''
        ROOMS_DIR.mkdir(parents=True, exist_ok=True)

    def add(self, m):
        if m not in self.mdls: self.mdls.append(m); out(m, 'joined'); self.save()
    def rm(self, m):
        hit = next((x for x in self.mdls if m in x), None)
        if hit: self.mdls.remove(hit); out(hit, 'left'); self.save()

    def _log(self, m, t, role='assistant'):
        e = {'model': m, 'role': role, 'content': t, 'ts': time.time()}
        self.history.append(e)
        if len(self.history) > 200: self.history = self.history[-100:]
        return e

    def _msgs(self, for_m, extra=''):
        sys = (f"You are {_s(for_m)} in a multi-AI room. "
               f"Others: {', '.join(_s(m) for m in self.mdls if m != for_m)}. "
               f"Be direct, disagree when warranted.")
        if self.ctx: sys += f"\n\n[CONTEXT]\n{self.ctx}"
        if extra: sys += f"\n\n{extra}"
        msgs = [{'role': 'system', 'content': sys}]
        for e in self.history[-20:]:
            if e['role'] == 'user': msgs.append({'role': 'user', 'content': e['content']})
            elif e['model'] == for_m: msgs.append({'role': 'assistant', 'content': e['content']})
            else: msgs.append({'role': 'user', 'content': f"[{_s(e['model'])}]: {e['content'][:300]}"})
        return msgs

    def query(self, prompt):
        self.ctx = nucleus(0)
        self._log('human', prompt, 'user'); out('human', prompt, 'YOU'); print()
        {'round-robin': self._rr, 'adversarial': self._adv,
         'parallel': self._par, 'snowball': self._snow,
         'sparse': self._sparse, 'free-mad': self._freemad}[self.mode](prompt)
        self.save()

    def _rr(self, p):
        for m in self.mdls:
            r = chat(m, self._msgs(m) + [{'role': 'user', 'content': p}])
            self._log(m, r); out(m, r); print()

    def _adv(self, p):
        if len(self.mdls) < 2: out('system', 'Need 2+ models'); return
        f = self.mdls[0]
        init = chat(f, self._msgs(f) + [{'role': 'user', 'content': p}])
        self._log(f, init); out(f, init); print()
        crits = []
        for c in self.mdls[1:]:
            # Anti-sycophancy: force critics to lead with disagreement
            anti_syc = ('You MUST start your response with "I disagree because..." '
                        'and provide genuine critical analysis. Do not capitulate.')
            r = chat(c, self._msgs(c, anti_syc) + [{'role': 'user', 'content': f'Review critically:\n\n{init}'}])
            self._log(c, f'[REVIEW] {r}'); out(c, f'[REVIEW] {r}'); print()
            crits.append(f"{_s(c)}: {r[:200]}")
        final = chat(f, self._msgs(f) + [{'role': 'user', 'content': f"Address critiques:\n\nOriginal: {init[:300]}\n\n" + '\n'.join(crits)}])
        self._log(f, f'[FINAL] {final}'); out(f, f'[FINAL] {final}'); print()

    def _par(self, p):
        out('system', f'{len(self.mdls)} parallel...')
        def q(m): return m, chat(m, self._msgs(m) + [{'role': 'user', 'content': p}])
        with ThreadPoolExecutor(max_workers=len(self.mdls)) as pool:
            for fut in as_completed([pool.submit(q, m) for m in self.mdls]):
                m, r = fut.result(); self._log(m, r); out(m, r); print()

    def _snow(self, p):
        acc = p
        for m in self.mdls:
            r = chat(m, self._msgs(m) + [{'role': 'user', 'content': f'Build on this:\n\n{acc}'}])
            self._log(m, r); out(m, r); print(); acc = r
        remember(f"[snowball] {', '.join(_s(m) for m in self.mdls)}: {acc[:500]}", 'agent', f'snowball: {p[:100]}')

    def _sparse(self, p):
        """Sparse-graph debate: each model sees only 1-2 peers, 2 rounds, majority vote."""
        import random
        if len(self.mdls) < 2: out('system', 'Need 2+ models'); return
        out('system', f'Sparse debate — {len(self.mdls)} models, 2 rounds')
        # Round 1: independent generation
        responses = {}
        def q1(m): return m, chat(m, self._msgs(m) + [{'role': 'user', 'content': p}])
        with ThreadPoolExecutor(max_workers=len(self.mdls)) as pool:
            for fut in as_completed([pool.submit(q1, m) for m in self.mdls]):
                m, r = fut.result(); responses[m] = r
                self._log(m, f'[R1] {r}'); out(m, f'[R1] {r}'); print()
        # Round 2: each model sees 1-2 random peers' outputs (sparse edges)
        peers = list(self.mdls)
        r2 = {}
        def q2(m):
            others = [x for x in peers if x != m]
            visible = random.sample(others, min(2, len(others)))
            peer_text = '\n\n'.join(f'[{_s(v)}]: {responses[v][:300]}' for v in visible)
            prompt2 = f'Original question: {p}\n\nYou can see these peer responses:\n{peer_text}\n\nGive your revised answer.'
            return m, chat(m, self._msgs(m) + [{'role': 'user', 'content': prompt2}])
        with ThreadPoolExecutor(max_workers=len(self.mdls)) as pool:
            for fut in as_completed([pool.submit(q2, m) for m in self.mdls]):
                m, r = fut.result(); r2[m] = r
                self._log(m, f'[R2] {r}'); out(m, f'[R2] {r}'); print()
        # Majority vote: ask first model to pick the majority answer
        ballot = '\n\n'.join(f'[{_s(m)}]: {r[:300]}' for m, r in r2.items())
        judge = self.mdls[0]
        verdict = chat(judge, [{'role': 'user', 'content':
            f'These models answered a question. Pick the majority answer and state it.\n\n{ballot}'}])
        self._log(judge, f'[VOTE] {verdict}'); out(judge, f'[VOTE] {verdict}'); print()

    def _freemad(self, p):
        """Free Multi-Agent Debate: independent gen, judge scoring, anti-conformity."""
        if len(self.mdls) < 2: out('system', 'Need 2+ models'); return
        out('system', f'Free-MAD — {len(self.mdls)} models, judge scoring')
        # Independent generation (like parallel)
        responses = {}
        def q(m): return m, chat(m, self._msgs(m) + [{'role': 'user', 'content': p}])
        with ThreadPoolExecutor(max_workers=len(self.mdls)) as pool:
            for fut in as_completed([pool.submit(q, m) for m in self.mdls]):
                m, r = fut.result(); responses[m] = r
                self._log(m, r); out(m, r); print()
        # Anti-conformity check: flag if all responses substantially agree
        check_text = '\n---\n'.join(f'[{_s(m)}]: {r[:300]}' for m, r in responses.items())
        judge = self.mdls[0]
        conformity = chat(judge, [{'role': 'user', 'content':
            f'Do these responses all essentially agree? Reply YES or NO, one word.\n\n{check_text}'}])
        if conformity.strip().upper().startswith('YES'):
            out('system', '!! ECHO CHAMBER WARNING — all responses agree, potential conformity bias')
        # Judge scoring: one model scores all others on correctness, completeness, novelty
        score_prompt = (
            f'You are a judge. Score each response to this question on three axes '
            f'(1-10 each): correctness, completeness, novelty. '
            f'Output JSON: {{"model": {{"correctness": N, "completeness": N, "novelty": N}}}}.\n\n'
            f'Question: {p}\n\n{check_text}')
        scores_raw = chat(judge, [{'role': 'user', 'content': score_prompt}])
        self._log(judge, f'[JUDGE] {scores_raw}'); out(judge, f'[JUDGE] {scores_raw}'); print()
        # Parse scores and pick winner
        best_m, best_score = None, -1
        try:
            # Extract JSON from judge response
            import re
            jmatch = re.search(r'\{[^{}]*\{[^{}]*\}[^{}]*\}', scores_raw, re.DOTALL)
            if jmatch:
                parsed = json.loads(jmatch.group())
                for label, axes in parsed.items():
                    total = sum(axes.values()) if isinstance(axes, dict) else 0
                    # Match label back to model
                    for m in self.mdls:
                        if _s(m) in label or label in _s(m):
                            if total > best_score: best_m = m; best_score = total
        except Exception:
            pass
        if best_m:
            out('system', f'Winner: {_s(best_m)} (score {best_score})')
            self._log(best_m, f'[WINNER] {responses[best_m]}')
            out(best_m, f'[WINNER] {responses[best_m]}'); print()
        else:
            out('system', 'Could not parse scores — all responses shown above')

    def synthesize(self):
        """Synthesize last round's outputs: majority-vote for reasoning, LLM aggregator for generative."""
        # Gather last round outputs (most recent entry per model)
        last = {}
        for e in reversed(self.history):
            m = e.get('model', '')
            if m and m != 'human' and m not in last:
                last[m] = e.get('content', '')
            if len(last) >= len(self.mdls): break
        if not last: out('system', 'No outputs to synthesize'); return
        combined = '\n\n'.join(f'[{_s(m)}]: {t[:400]}' for m, t in last.items())
        # Detect reasoning vs generative: code/math markers
        import re
        has_code_math = any(re.search(r'(```|def |class |import |\\frac|\\sum|\d+\.\d{3,}|=>|==)', t)
                           for t in last.values())
        if has_code_math:
            # Reasoning: majority vote
            judge = self.mdls[0]
            result = chat(judge, [{'role': 'user', 'content':
                f'These are solutions to a technical/reasoning task. '
                f'Identify the majority answer and produce the single correct solution.\n\n{combined}'}])
            out(judge, f'[SYNTHESIZED-VOTE] {result}'); print()
        else:
            # Generative: LLM aggregator
            judge = self.mdls[0]
            result = chat(judge, [{'role': 'user', 'content':
                f'Synthesize these responses into one unified, comprehensive answer. '
                f'Keep the best insights from each.\n\n{combined}'}])
            out(judge, f'[SYNTHESIZED] {result}'); print()
        self._log(judge, f'[SYNTH] {result}')
        self.save()

    def save(self):
        try:
            with open(ROOMS_DIR / f'{self.name}.json', 'w') as f:
                json.dump({'name': self.name, 'models': self.mdls, 'mode': self.mode,
                           'history': self.history[-100:]}, f, indent=2)
        except Exception: pass

    @classmethod
    def load(cls, name):
        p = ROOMS_DIR / f'{name}.json'
        if not p.exists(): return None
        try:
            d = json.loads(p.read_text())
            r = cls(d['name']); r.mdls = d.get('models', []); r.mode = d.get('mode', 'parallel')
            r.history = d.get('history', []); return r
        except Exception: return None

class Rooms:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}; self.cur: Optional[str] = None
        ROOMS_DIR.mkdir(parents=True, exist_ok=True)
        for f in ROOMS_DIR.glob('*.json'):
            r = Room.load(f.stem)
            if r: self.rooms[r.name] = r

    def create(self, n) -> Room:
        if n in self.rooms: return self.rooms[n]
        r = Room(n); self.rooms[n] = r; self.cur = n; return r
    def join(self, n): self.cur = n; return self.rooms.get(n)
    def get(self): return self.rooms.get(self.cur) if self.cur else None
    def ls(self): return list(self.rooms.keys())
    def delete(self, n):
        if n in self.rooms:
            del self.rooms[n]
            try: (ROOMS_DIR / f'{n}.json').unlink()
            except Exception: pass
            if self.cur == n: self.cur = None

# ── TUI ───────────────────────────────────────────────────────────────────

HELP = """\
{D}
    {Y}  (\\/)  {R}{D}      {G}  (\\/)  {R}{D}      {Y}  (\\/)  {R}{D}      {G}  (\\/)  {R}{D}      {Y}  (\\/)  {R}{D}
    {Y} ( {R}oo{Y} ) {R}{D}     {G} ( {R}oo{G} ) {R}{D}     {Y} ( {R}oo{Y} ) {R}{D}     {G} ( {R}oo{G} ) {R}{D}     {Y} ( {R}oo{Y} ) {R}{D}
    {Y}  /||\\  {R}{D}      {G}  /||\\  {R}{D}      {Y}  /||\\  {R}{D}      {G}  /||\\  {R}{D}      {Y}  /||\\  {R}{D}
    {Y} / || \\ {R}{D}     {G} / || \\ {R}{D}     {Y} / || \\ {R}{D}     {G} / || \\ {R}{D}     {Y} / || \\ {R}{D}
   {D}___\\__/______\\__/______\\__/______\\__/______\\__/___
   {G}>>>{R}{D}  hypothesize  generate    train      eval     keep  {G}>>>{R}
   {D}____________________________________________________________{R}
{G}{B}              C L A W T O N O M Y{R}

{B2}Room:{R}  /create /join /rooms /delete
{B2}Model:{R} /add /rm /models /active
{B2}Mode:{R}  /mode parallel|adversarial|round-robin|snowball|sparse|free-mad
{B2}Synth:{R} /synthesize — unify last round's outputs
{B2}Mem:{R}   /context /history
{B2}Exp:{R}   /experiment <dir> [fast [deep]] | /experiment auto <dir> [hours]
       /experiment tree — show solution tree
{B2}Sess:{R}  /status /services /postmortem [quick] /provenance /block
{B2}Other:{R} /clear /save /q
"""

def main():
    if sys.platform == 'win32':
        import io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        os.system('')

    session, _ = boot()
    mgr = Rooms(); pm = Postmortem(session, mgr)

    G = '\033[38;2;0;255;136m'; B2 = '\033[38;2;102;119;170m'; Y = '\033[38;2;255;204;0m'
    print(HELP.format(G=G, B=B, B2=B2, D=D, R=RST, Y=Y))

    if not mgr.rooms: room = mgr.create('default')
    else: mgr.cur = list(mgr.rooms.keys())[0]; room = mgr.rooms[mgr.cur]

    if not room.mdls:
        for d in ['hermes3:8b', 'mistral:latest']:
            if d in models(): room.add(d)

    out('system', f'{room.name} | {room.mode} | {len(room.mdls)} models')
    print()
    _exp_runner = None  # persists across /experiment invocations

    while True:
        try: line = input(f'{B}[{_s(room.name) if room else "??"}]> {RST}').strip()
        except (EOFError, KeyboardInterrupt): break
        if not line: continue
        room = mgr.get()

        blk = blocked(line)
        if blk: out('system', blk, 'BLOCK'); provenance('blocked', line); continue

        if not line.startswith('/'):
            if not room: out('system', 'No room. /create <name>'); continue
            if not room.mdls: out('system', 'No models. /add <model>'); continue
            session.record(room.name, room.mode, room.mdls, line)
            provenance('query', line[:100], {'room': room.name})
            room.query(line); continue

        parts = line[1:].split(None, 1); cmd = parts[0].lower(); arg = parts[1] if len(parts) > 1 else ''

        if cmd in ('q', 'quit', 'exit'): break
        elif cmd == 'create': room = mgr.create(arg or 'new'); out('system', f'"{room.name}" created')
        elif cmd == 'join':
            r = mgr.join(arg)
            if r: room = r; out('system', f'Joined "{room.name}"')
            else: out('system', f'Not found. Rooms: {", ".join(mgr.ls())}')
        elif cmd == 'rooms':
            for n in mgr.ls():
                r = mgr.rooms[n]; out('system', f'{n}: {len(r.mdls)}m {r.mode} {len(r.history)}msg{" [*]" if n == mgr.cur else ""}')
        elif cmd == 'delete': mgr.delete(arg); room = mgr.get(); out('system', f'Deleted "{arg}"')
        elif cmd == 'add' and room:
            av = models(); room.add(next((m for m in av if arg in m), arg))
        elif cmd in ('rm', 'remove') and room: room.rm(arg)
        elif cmd == 'models':
            av = models(); out('system', f'{len(av)} available:')
            for m in av: print(f'  {_c(m)}{m}{RST}{" [*]" if room and m in room.mdls else ""}')
        elif cmd == 'active':
            if room and room.mdls: [out(m, 'active') for m in room.mdls]
            else: out('system', 'No models')
        elif cmd == 'mode':
            if room and arg in Room.MODES: room.mode = arg; out('system', f'Mode: {arg}')
            else: out('system', f'Modes: {", ".join(Room.MODES)}')
        elif cmd == 'context': ctx = nucleus(); print(f'{D}{ctx[:600] if ctx else "No context"}{RST}')
        elif cmd == 'history' and room:
            for e in room.history[-10:]: out(e.get('model', '?'), e.get('content', '')[:120])
        elif cmd == 'clear':
            if room: room.history = []
            os.system('cls' if sys.platform == 'win32' else 'clear')
            print(HELP.format(G=G, B=B, B2=B2, D=D, R=RST, Y=Y))
        elif cmd == 'save' and room: room.save(); out('system', 'Saved')
        elif cmd == 'synthesize' and room: room.synthesize()
        elif cmd == 'status':
            for k, v in session.summary().items(): out('system', f'{k}: {v}')
        elif cmd == 'services':
            for n, up in scan().items():
                port = next((pt for pt, (nm, _) in SERVICES.items() if nm == n), None)
                if port: out('system', f':{port} {n} {"UP" if up else "DOWN"}')
        elif cmd == 'postmortem':
            if arg == 'quick':
                for k, v in pm.quick().items():
                    if k != 'history': out('system', f'{k}: {v}')
            else:
                path = pm.run(arg.split(',') if arg else None)
                out('system', f'Saved: {path}')
        elif cmd == 'provenance':
            try:
                if PROVENANCE_LOG.exists():
                    for ln in PROVENANCE_LOG.read_text(encoding='utf-8').strip().splitlines()[-10:]:
                        e = json.loads(ln); out('system', f'{e.get("ts","?")[11:19]} {e.get("event","?")} {e.get("detail","")[:60]}')
                else: out('system', 'No log')
            except Exception as e: out('system', f'Error: {e}')
        elif cmd == 'block':
            if arg: out('system', blocked(arg) or 'Clean')
            else: out('system', f'Blocklist: {", ".join(BLOCKLIST.keys())}')
        elif cmd == 'experiment':
            eparts = arg.split()
            if not eparts:
                out('system', '/experiment <dir> [fast [deep]]  — interactive')
                out('system', '/experiment auto <dir> [hours]   — overnight')
                out('system', '/experiment tree                 — show tree')
                continue
            # /experiment tree — show current tree if runner exists
            if eparts[0] == 'tree':
                if _exp_runner: print(_exp_runner.tree_view())
                else: out('system', 'No active experiment. Run /experiment <dir> first.')
                continue
            # /experiment auto <dir> [hours] — overnight loop
            if eparts[0] == 'auto':
                if len(eparts) < 2: out('system', '/experiment auto <dir> [hours]'); continue
                exp_dir = eparts[1]
                exp_hours = float(eparts[2]) if len(eparts) > 2 else 8.0
                prog = ''; prog_path = Path(exp_dir) / 'program.md'
                if prog_path.exists(): prog = prog_path.read_text(encoding='utf-8')
                fast_m = eparts[3] if len(eparts) > 3 else 'hermes3:8b'
                deep_m = eparts[4] if len(eparts) > 4 else 'mistral:latest'
                _exp_runner = ExperimentRunner(exp_dir, prog, fast_m, deep_m)
                out('system', f'Auto-loop: {exp_dir}, {exp_hours}h, fast={fast_m}, deep={deep_m}')
                _exp_runner.auto_loop(exp_hours)
                out('system', _exp_runner.summary())
                provenance('experiment', _exp_runner.summary())
                continue
            # /experiment <dir> [fast [deep]] — interactive tree-search
            exp_dir = eparts[0]
            fast_m = eparts[1] if len(eparts) > 1 else 'hermes3:8b'
            deep_m = eparts[2] if len(eparts) > 2 else 'mistral:latest'
            prog = ''; prog_path = Path(exp_dir) / 'program.md'
            if prog_path.exists(): prog = prog_path.read_text(encoding='utf-8')
            _exp_runner = ExperimentRunner(exp_dir, prog, fast_m, deep_m)
            out('system', f'Tree-search experiment: {exp_dir}')
            out('system', f'  fast={fast_m}, deep={deep_m}')
            out('system', 'Commands: hypothesis text | "auto" N | "tree" | empty=ensemble step | q=stop')
            while True:
                try: h = input(f'{D}  exp[{len(_exp_runner.tree)}]> {RST}').strip()
                except (EOFError, KeyboardInterrupt): break
                if not h:
                    # Empty line = one ensemble step (auto-generate + pick + run)
                    result = _exp_runner.ensemble_step()
                    if result:
                        out('system', f'Result: {result.get("status")} '
                            f'val_bpb={result.get("val_bpb")} node={result.get("id")}')
                    continue
                if h in ('q', 'quit', 'stop'): break
                if h == 'tree': print(_exp_runner.tree_view()); continue
                if h.startswith('auto'):
                    ap = h.split(); hrs = float(ap[1]) if len(ap) > 1 else 1.0
                    _exp_runner.auto_loop(hrs); continue
                # Anything else is a manual hypothesis
                result = _exp_runner.run_one(h)
                out('system', f'Result: {result.get("status")} '
                    f'val_bpb={result.get("val_bpb")} node={result.get("id")}')
            out('system', _exp_runner.summary())
            provenance('experiment', _exp_runner.summary())
        else: out('system', f'Unknown: /{cmd}')

    if room: room.save()
    session.save()
    provenance('end', f'prompts={session.d["prompts"]}')
    print(f'\n{D}Closed. /postmortem to analyze.{RST}')

if __name__ == '__main__':
    main()
