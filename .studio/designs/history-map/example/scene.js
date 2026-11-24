import { create, meta } from './napoleon.js';

const id = 'history-map-example';
const fontFamily = '历史地图思源黑体';
const canvas = document.querySelector('#map-canvas');
const overlay = document.querySelector('#map-text');
const query = new URLSearchParams(location.search);
const mode = query.get('mode') === 'standalone' ? 'standalone' : 'page';
let film, timeline, disposed = false;
const clock = { seconds: 0 };
const textSource = () => film?.world?.texts() || [];
const textSources = window.__hfTextSources ||= [];
textSources.push(textSource);

async function seek(time) {
  await ready;
  if (disposed) return;
  timeline.totalTime(Math.max(0, Math.min(meta.dur, time)), true);
  film.apply(clock.seconds);
}
function handleSeek(event) {
  const pending = seek(event.detail.time);
  if (event.detail.waitUntil) event.detail.waitUntil(pending);
  else pending.catch(error => window.dispatchEvent(new ErrorEvent('error', { error, message: error.message })));
}
function dispose() {
  if (disposed) return;
  disposed = true;
  window.removeEventListener('hf-seek', handleSeek);
  textSources.splice(textSources.indexOf(textSource), 1);
  if (timeline) {
    timeline.kill();
    delete window.__timelines[id];
  }
  film?.dispose();
  film = null;
}
const ready = (async () => {
  const faces = await document.fonts.load(`48px "${fontFamily}"`, '三皇会战');
  if (faces.length === 0) throw new Error('缺少思源黑体');
  if (disposed) return;
  film = create({ canvas, overlay, fontFamily, mode });
  await film.ready;
  if (disposed) return;
  timeline = gsap.timeline({ paused: true }).to(clock, { seconds: meta.dur, duration: meta.dur, ease: 'none' });
  (window.__timelines ||= {})[id] = timeline;
  film.apply(Math.max(0, Math.min(meta.dur, Number(query.get('t')) || 0)));
})().catch(error => { dispose(); throw error; });
window.addEventListener('hf-seek', handleSeek);
window.__example = { ready, seek, dispose, duration: meta.dur, get film() { return film; } };
