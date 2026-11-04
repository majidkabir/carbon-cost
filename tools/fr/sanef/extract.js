// Writes the text positions of Sanef's and SAPN's tariff brochures, as
// tools/fr/sanef.py reads them (<name>.items.txt). Sanef's site answers
// scripted downloads with a bot check, so this runs in a browser: open
// https://www.autoroutes.sanef.com/fr/grilles-tarifs-de-peage, paste
// this into the developer console, and save the files it offers into
// tools/fr/sanef/. Each file starts with the PDF's URL, size and sha256.
// Text positions come from pdf.js 4.4.168 (getTextContent): x, y are the
// item's transform[4], transform[5], font its transform[0]. Only the
// pages with the class 3 and 4 grids (and the title page) are kept from
// the Sanef brochure; all pages from the SAPN one.
(async () => {
  const pdfjs = await import('https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.min.mjs');
  pdfjs.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs';
  const docs = [
    ['/sites/default/files/2026-01/2026_02-Grille-Sanef.pdf', [1, 4, 5]],
    ['/sites/default/files/2026-01/2026_02-Grille-SAPN.pdf', [1, 2, 3, 4, 5, 6]],
  ];
  for (const [u, pages] of docs) {
    const b = new Uint8Array(await (await fetch(u)).arrayBuffer());
    const h = [...new Uint8Array(await crypto.subtle.digest('SHA-256', b))].map(x => x.toString(16).padStart(2, '0')).join('');
    const d = await pdfjs.getDocument({ data: b.slice() }).promise;
    let s = '# url https://www.autoroutes.sanef.com' + u + '\n# bytes ' + b.length + '\n# sha256 ' + h.match(/.{8}/g).join(' ') +
      '\n# pages ' + d.numPages + '\n# page|x|y|width|height|font|text (pdf.js 4.4.168 getTextContent; x, y = transform[4], transform[5]; font = transform[0])\n';
    for (const i of pages) {
      const p = await d.getPage(i);
      const v = p.getViewport({ scale: 1 });
      s += '# page ' + i + ' ' + v.width + ' ' + v.height + '\n';
      const t = await p.getTextContent();
      for (const x of t.items) {
        if (!x.str.trim()) continue;
        const r = n => Math.round(n * 100) / 100;
        s += [i, r(x.transform[4]), r(x.transform[5]), r(x.width), r(x.height), r(x.transform[0]), x.str.replace(/\|/g, '/')].join('|') + '\n';
      }
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([s], { type: 'text/plain' }));
    a.download = u.split('/').pop().replace(/\.pdf$/, '.items.txt');
    a.click();
  }
})();
