// Loading without fetch(). Browsers block fetch() of local files when index.html is opened straight
// from disk (file://), but <script> tags still work. So the data ships as .js files that set
// window.GAMBITO_DATA[name] (written by site_data.py / site_build.py). This works hosted too.
export function loadScript(src) {
  return new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => res();
    s.onerror = () => rej(new Error('could not load ' + src));
    document.head.appendChild(s);
  });
}

export async function loadData(name) {
  const D = window.GAMBITO_DATA || (window.GAMBITO_DATA = {});
  if (!(name in D)) await loadScript(`data/${name}.js`);
  const d = D[name];
  delete D[name];               // the caller keeps its own copy; don't hold two
  if (d === undefined) throw new Error(`data/${name}.js loaded but did not define "${name}"`);
  return d;
}
