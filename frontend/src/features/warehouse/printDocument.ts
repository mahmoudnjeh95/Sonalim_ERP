export interface PrintableDocument {
  title: string;
  /** Label and value pairs shown above the table. */
  fields: [string, string][];
  headers: string[];
  rows: (string | number)[][];
  footer?: string;
}

function escapeHtml(value: string | number) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
}

function toHtml(doc: PrintableDocument) {
  const fields = doc.fields.map(([label, value]) => `<div><b>${escapeHtml(label)} :</b> ${escapeHtml(value)}</div>`).join("");
  const head = doc.headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("");
  const rows = doc.rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("")}</tr>`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(doc.title)}</title><style>
    body{font:13px sans-serif;margin:24px;color:#111}h1{font-size:20px;margin:0 0 4px}
    .brand{color:#555;margin-bottom:16px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:4px 24px;margin-bottom:16px}
    table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:6px 8px;text-align:left;height:18px}th{background:#eee}
    .footer{margin-top:16px;white-space:pre-wrap}
  </style></head><body><div class="brand">Sonalim</div><h1>${escapeHtml(doc.title)}</h1><div class="fields">${fields}</div>
  <table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>
  ${doc.footer ? `<div class="footer">${escapeHtml(doc.footer)}</div>` : ""}</body></html>`;
}

/** A document in its own window: the manual's Aperçu shows it, its Imprimer also opens the print dialog,
 *  from which it can be saved as a PDF. */
export function openDocument(doc: PrintableDocument, options: { print: boolean }) {
  const opened = window.open("", "_blank");
  if (!opened) return false;
  opened.document.write(toHtml(doc));
  opened.document.close();
  if (options.print) {
    opened.focus();
    opened.print();
  }
  return true;
}
