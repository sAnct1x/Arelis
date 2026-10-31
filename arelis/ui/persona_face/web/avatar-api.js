// Arelis bridge contract: window.avatar.setState(idle|listening|thinking|speaking|done), setLevel(0..1), setTint(hue degrees).
// Stub over the pass 14 scene's window.aether. A scene that defines window.avatar itself wins.
if (!window.avatar && window.aether) {
  const MODE = { idle: 'idle', listening: 'listening', thinking: 'thinking', speaking: 'talking', done: 'done' };   // m1: listening and done have their own poses in anim.js
  window.avatar = {
    setState: (s) => window.aether.setState(MODE[s] || 'idle'),
    setLevel: (v) => window.aether.setLevel(Math.max(0, Math.min(1, +v || 0))),
    setTint: (deg) => window.aether.setTint && window.aether.setTint(+deg || 0),
  };
}
addEventListener('error', (e) => { window.__error = window.__error || String(e.message || e); });
