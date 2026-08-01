/**
 * BALS learning-material page: tab navigation, PDF/TXT export, floating player.
 * All i18n strings come from data-* attributes on .learning-material root.
 */
(function () {
  'use strict';
  var root = document.querySelector('.learning-material');
  if (!root) return;

  var tabs = Array.prototype.slice.call(root.querySelectorAll('#lessonTabs .lesson-toc-item'));
  var prevLabel = root.dataset.prevLabel || 'Previous';
  var nextLabel = root.dataset.nextLabel || 'Next';
  var lessonTitle = root.dataset.lessonTitle || '';
  var exportMeta = JSON.parse(root.dataset.exportMeta || '{}');

  function goTo(index) {
    if (index < 0 || index >= tabs.length) return;
    bootstrap.Tab.getOrCreateInstance(tabs[index]).show();
    tabs[index].scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }

  function makeDots(activeIdx) {
    var wrap = document.createElement('div');
    wrap.className = 'lesson-progress';
    wrap.setAttribute('aria-hidden', 'true');
    tabs.forEach(function (_, i) {
      var dot = document.createElement('span');
      dot.className = 'lesson-progress-dot' + (i === activeIdx ? ' is-active' : '');
      wrap.appendChild(dot);
    });
    return wrap;
  }

  root.querySelectorAll('.lesson-card-foot').forEach(function (foot) {
    var paneId = foot.dataset.pane;
    var idx = tabs.findIndex(function (t) { return t.getAttribute('data-bs-target') === '#' + paneId; });
    if (idx < 0) return;
    var prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'btn btn-link lesson-nav-link';
    prevBtn.innerHTML = '<i class="bi bi-arrow-left me-1"></i>' + prevLabel;
    prevBtn.disabled = idx === 0;
    prevBtn.addEventListener('click', function () { goTo(idx - 1); });

    var nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'btn btn-primary';
    nextBtn.innerHTML = nextLabel + '<i class="bi bi-arrow-right ms-1"></i>';
    nextBtn.disabled = idx === tabs.length - 1;
    nextBtn.addEventListener('click', function () { goTo(idx + 1); });

    foot.append(prevBtn, makeDots(idx), nextBtn);
  });

  tabs.forEach(function (tab) {
    tab.addEventListener('shown.bs.tab', function () {
      tab.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    });
  });

  document.addEventListener('keydown', function (e) {
    if (e.target.closest('input, textarea, select, [contenteditable]')) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    var active = tabs.findIndex(function (t) { return t.classList.contains('active'); });
    if (active < 0) return;
    e.preventDefault();
    goTo(active + (e.key === 'ArrowRight' ? 1 : -1));
  });

  /* ---- PDF / TXT export ---- */
  (function () {
    var txtBtn = document.getElementById('downloadTxtBtn');
    var pdfBtn = document.getElementById('downloadPdfBtn');
    var pdfNoAnsBtn = document.getElementById('downloadPdfNoAnsBtn');
    if (!txtBtn && !pdfBtn && !pdfNoAnsBtn) return;

    var exportUrl = root.getAttribute('data-export-url') || '';
    var cachedPayload = null;

    function esc(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function nl(s) { return esc(s).replace(/\n+/g, '<br>'); }
    function safeFilename(title, ext) {
      var base = (title || 'bals-lesson').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || 'bals-lesson';
      return base + ext;
    }
    function loadPayload() {
      if (cachedPayload) return Promise.resolve(cachedPayload);
      if (!exportUrl) return Promise.reject(new Error('Missing export URL'));
      return fetch(exportUrl, { headers: { 'Accept': 'application/json' }, credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (d) { cachedPayload = d; return d; });
    }

    function renderAnswers(answers, label, includeAnswers) {
      if (!includeAnswers) return '';
      return (answers || []).filter(Boolean).map(function (a) {
        return '<p class="ans"><span class="ans-label">' + esc(label) + '</span> ' + esc(a) + '</p>';
      }).join('');
    }

    function renderListItems(items, answerLabel, includeAnswers) {
      var rows = (items || []).map(function (it) {
        if (typeof it === 'string') return '<li><div class="q">' + nl(it) + '</div></li>';
        var main = it.main || it.prompt || it.question || it.statement || it.sentence || '';
        var opts = (it.options || []).map(function (o) { return '<li>' + esc(o) + '</li>'; }).join('');
        var answers = it.answers || (it.answer ? [it.answer] : []);
        return '<li><div class="q">' + nl(main) + '</div>' +
          (opts ? '<ul class="opts">' + opts + '</ul>' : '') +
          renderAnswers(answers, answerLabel, includeAnswers) + '</li>';
      }).join('');
      return '<div class="unit unit-plain"><ol class="items">' + rows + '</ol></div>';
    }

    function renderVocab(words, meta) {
      var L = (meta && meta.labels) || {};
      var synL = L.syn || 'Syn.', antL = L.ant || 'Ant.', phraseL = L.phrase || 'Phr.', noteL = L.note || 'Note';
      return '<div class="vocab">' + (words || []).map(function (w) {
        var senses = (w.senses || []).map(function (s, idx) {
          var gloss = (s.translation || s.gloss || '').replace(/[【】\[\]]/g, '');
          var def = s.definition || s.def || '';
          var head = [gloss && '<span class="gloss">【' + esc(gloss) + '】</span>', esc(def)].filter(Boolean).join(' ');
          var example = s.example || '';
          var cols = Array.isArray(s.collocations) ? s.collocations.join(' · ') : (s.collocations || '');
          return '<div class="sense">' +
            ((w.senses || []).length > 1 ? '<span class="sense-n">' + (idx + 1) + '.</span>' : '') +
            '<span class="sense-body">' + head + '</span>' +
            (example ? '<div class="ex">' + esc(example) + '</div>' : '') +
            (cols ? '<div class="col">' + esc(cols) + '</div>' : '') + '</div>';
        }).join('');
        var asides = [];
        if (w.synonyms && w.synonyms.length) asides.push(synL + ' ' + w.synonyms.join(', '));
        if (w.antonyms && w.antonyms.length) asides.push(antL + ' ' + w.antonyms.join(', '));
        if (w.phraseology && w.phraseology.length) asides.push(phraseL + ' ' + w.phraseology.join(' · '));
        if (w.note) asides.push(noteL + ' ' + w.note);
        var ipa = (w.ipa || '').replace(/^\[|\]$/g, '');
        return '<div class="word"><div class="lemma-line">' +
          '<span class="lemma">' + esc(w.headword || w.lemma || w.term || '') + '</span>' +
          (w.grammar ? '<span class="gram">' + esc(w.grammar) + '</span>' : '') +
          (ipa ? '<span class="ipa">[' + esc(ipa) + ']</span>' : '') +
          '</div>' + senses + asides.map(function (a) { return '<div class="aside">' + esc(a) + '</div>'; }).join('') + '</div>';
      }).join('') + '</div>';
    }

    function renderGrammar(items, meta, includeAnswers) {
      var L = meta.labels || {};
      return (items || []).map(function (g) {
        var title = g.meaning
          ? esc(g.pattern || '') + ' <span class="meaning">— ' + esc(g.meaning) + '</span>'
          : esc(g.pattern || '');
        var blocks = [];
        if ((g.collocations || []).length) {
          blocks.push('<div class="block"><div class="label">' + esc(L.typical_collocations || '') + '</div><ul class="items">' +
            g.collocations.map(function (r) { return '<li>' + esc(r.phrase || '') + (r.translation ? ' — ' + esc(r.translation) : '') + '</li>'; }).join('') + '</ul></div>');
        }
        if ((g.forms || []).length) {
          blocks.push('<div class="block"><div class="label">' + esc(L.forms || '') + '</div><ul class="items">' +
            g.forms.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul></div>');
        }
        if (g.model && g.model.sentence) {
          blocks.push('<div class="block"><div class="label">' + esc(L.example_sentence || '') + '</div><p>«' + esc(g.model.sentence) + '»</p>' +
            (g.model.translation ? '<p class="ex">' + esc(g.model.translation) + '</p>' : '') + '</div>');
        }
        if (g.note) blocks.push('<div class="block"><div class="label">' + esc(L.note || '') + '</div><p>' + esc(g.note) + '</p></div>');
        if ((g.examples || []).length) {
          blocks.push('<div class="block"><div class="label">' + esc(L.more_phrases || '') + '</div><ul class="items">' +
            g.examples.map(function (ex) { return '<li>«' + esc(ex.phrase || '') + '»' + (ex.translation ? ' (' + esc(ex.translation) + ')' : '') + '</li>'; }).join('') + '</ul></div>');
        }
        var practiceItems = g.practice_items || [];
        if (practiceItems.length || g.practice_instruction || g.practice) {
          var label = [L.practice || '', g.practice_instruction || ''].filter(Boolean).join(' · ');
          var lis = practiceItems.map(function (p) {
            return '<li><div class="q">' + nl(p.prompt || '') + '</div>' + renderAnswers(p.answer ? [p.answer] : [], meta.answer, includeAnswers) + '</li>';
          }).join('');
          blocks.push('<div class="block">' + (label ? '<div class="label">' + esc(label) + '</div>' : '') +
            (lis ? '<ol class="items">' + lis + '</ol>' : '') +
            (!lis && g.practice ? '<p>' + esc(g.practice) + '</p>' : '') + '</div>');
        }
        return '<div class="unit">' + (title ? '<h3>' + title + '</h3>' : '') +
          (g.overview ? '<p class="overview">' + esc(g.overview) + '</p>' : '') + blocks.join('') + '</div>';
      }).join('');
    }

    function renderListening(tasks, answerLabel, includeAnswers) {
      return (tasks || []).map(function (task) {
        var questions = (task.items || []).map(function (item) {
          return { main: item.prompt || item.statement || item.question || item.sentence || '', options: item.options || [], answers: item.answer ? [item.answer] : [] };
        });
        var lis = questions.map(function (q) {
          var opts = (q.options || []).map(function (o) { return '<li>' + esc(o) + '</li>'; }).join('');
          return '<li><div class="q">' + nl(q.main) + '</div>' + (opts ? '<ul class="opts">' + opts + '</ul>' : '') + renderAnswers(q.answers, answerLabel, includeAnswers) + '</li>';
        }).join('');
        return '<div class="unit">' + (task.type_label ? '<h3>' + esc(task.type_label) + '</h3>' : '') +
          (task.instruction ? '<p class="overview">' + esc(task.instruction) + '</p>' : '') +
          (lis ? '<ol class="items">' + lis + '</ol>' : '') + '</div>';
      }).join('');
    }

    function renderExpression(section, meta, includeAnswers) {
      var L = meta.labels || {};
      var parts = [];
      function taskBlock(title, task) {
        if (!task || !task.prompt) return;
        parts.push('<div class="unit"><h3>' + esc(title) + (task.meta ? ' · ' + esc(task.meta) : '') + '</h3><p>' + esc(task.prompt) + '</p>' +
          ((task.useful_language || []).length ? '<div class="block"><div class="label">' + esc(L.useful_language || '') + '</div><p class="chips">' + task.useful_language.map(esc).join(' · ') + '</p></div>' : '') +
          ((task.support_phrases || []).length ? '<div class="block"><div class="label">' + esc(L.support_phrases || '') + '</div><p class="chips">' + task.support_phrases.map(esc).join(' · ') + '</p></div>' : '') +
          ((task.checklist || []).length ? '<div class="block"><div class="label">' + esc(L.checklist || '') + '</div><ol class="items">' + task.checklist.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol></div>' : '') +
          (task.sample_answer ? renderAnswers([task.sample_answer], meta.sample, includeAnswers) : '') + '</div>');
      }
      taskBlock(L.speaking || '', section.speaking);
      taskBlock(L.writing || '', section.writing);
      if ((section.review || []).length) {
        parts.push('<div class="unit"><h3>' + esc(L.review || '') + '</h3><table class="rev"><tbody>' +
          section.review.map(function (r) { return '<tr><th>' + esc(r.term || '') + '</th><td>' + esc(r.translation || '') + '</td></tr>'; }).join('') +
          '</tbody></table></div>');
      }
      return parts.join('');
    }

    function renderCaptions(rows) {
      if (!(rows || []).length) return '<p class="empty">—</p>';
      return '<table class="cap"><tbody>' + rows.map(function (r) {
        return '<tr><th>' + esc(r.time || '') + '</th><td>' + esc(r.text || '') + '</td></tr>';
      }).join('') + '</tbody></table>';
    }

    function renderSectionBody(section, meta, includeAnswers) {
      switch (section.type) {
        case 'list': return renderListItems(section.items, meta.answer, includeAnswers);
        case 'vocab': return renderVocab(section.words, meta);
        case 'grammar': return renderGrammar(section.items, meta, includeAnswers);
        case 'listening': return renderListening(section.tasks, meta.answer, includeAnswers);
        case 'qa': return renderListItems((section.items || []).map(function (it) { return { main: it.question || '', answers: it.answer ? [it.answer] : [] }; }), meta.answer, includeAnswers);
        case 'expression': return renderExpression(section, meta, includeAnswers);
        case 'captions': return renderCaptions(section.rows);
        default: return '';
      }
    }

    var FONT = '"Lucida Grande","Arial Unicode MS","Segoe UI","Helvetica Neue","Arial","PingFang SC","Hiragino Sans GB","Noto Sans SC","Microsoft YaHei",sans-serif';
    var FONT_IPA = '"Lucida Grande","Arial Unicode MS","Noto Sans","DejaVu Sans","Segoe UI",sans-serif';
    var PDF_CSS = '@page{size:A4;margin:14mm 13mm 16mm}*{box-sizing:border-box;letter-spacing:normal!important;word-spacing:normal!important}html,body{margin:0;padding:0;background:#fff!important;color:#1a1f27!important;font-family:' + FONT + ';font-size:10.75pt;line-height:1.58;-webkit-print-color-adjust:exact;print-color-adjust:exact}.wrap{max-width:180mm;margin:0 auto;color:#1a1f27;font-family:' + FONT + '}.cover{margin:0 0 18pt;padding:14pt 16pt;border:1pt solid #d5e0eb;border-radius:10pt;background:linear-gradient(180deg,#f5f8fc 0%,#fff 62%)}.brand-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:12pt}.brand{margin:0;padding:3pt 9pt;border-radius:999pt;background:#3d7eb5;color:#fff!important;font-size:9pt;font-weight:800;letter-spacing:.1em!important}.brand-sub{margin:0;color:#5c6673!important;font-size:9pt;font-weight:600}h1{margin:0 0 10pt;color:#101826!important;font-family:' + FONT + ';font-size:17.5pt;font-weight:800;line-height:1.32}.meta{display:flex;flex-wrap:wrap;gap:6pt;margin:0 0 12pt}.pill{display:inline-block;padding:3pt 9pt;border-radius:999pt;background:#e7f0f8;color:#2f628d!important;font-size:9.5pt;font-weight:700}.toc-box{margin:0;padding:10pt 12pt;border:1pt solid #dce6f0;border-radius:8pt;background:#fff}.toc-title{margin:0 0 6pt;color:#3d7eb5!important;font-size:9pt;font-weight:800}.toc{margin:0;padding:0;list-style:none;columns:2;column-gap:16pt;font-size:10pt}.toc li{break-inside:avoid;display:flex;gap:6pt;margin:0;padding:2.5pt 0;color:#1a1f27!important}.toc .n{flex:0 0 1.35em;color:#3d7eb5!important;font-weight:800;font-variant-numeric:tabular-nums}.toc .t{flex:1 1 auto;color:#243041!important;font-weight:600}.sec{margin:0 0 16pt}.sec-h{display:flex;align-items:center;gap:8pt;margin:0 0 9pt;padding:6pt 10pt;border-radius:7pt;background:#eef4fa;border-left:3.5pt solid #3d7eb5;page-break-after:avoid}.sec-h .n{display:inline-flex;align-items:center;justify-content:center;min-width:22pt;height:18pt;padding:0 5pt;border-radius:5pt;background:#3d7eb5;color:#fff!important;font-size:9.5pt;font-weight:800;font-variant-numeric:tabular-nums}.sec-h h2{margin:0;color:#142033!important;font-family:' + FONT + ';font-size:12.25pt;font-weight:800;line-height:1.3}.unit{margin:0 0 11pt;padding:9pt 11pt;border:1pt solid #e3eaf2;border-radius:8pt;background:#fbfcfe;page-break-inside:avoid}.unit.unit-plain{background:#fff}.unit h3{margin:0 0 5pt;color:#152033!important;font-family:' + FONT + ';font-size:10.75pt;font-weight:800}.unit h3 .meaning{color:#5a6573!important;font-weight:600}p,.q,.overview,.sense-body,.chips,li,td,th{margin:0 0 4.5pt;color:#1a1f27!important;font-family:' + FONT + '}.overview{color:#2a3340!important}.block{margin-top:7pt}.label{margin:0 0 2pt;color:#5c6673!important;font-size:8.5pt;font-weight:800}.items{margin:0 0 0 1.15em;padding:0}.items>li{margin:0 0 6pt}.opts{margin:2pt 0 0 .8em;padding:4pt 8pt;border-radius:5pt;background:#f3f6fa;list-style:none}.opts li{margin:0;padding:1.5pt 0;color:#2c3542!important}.opts li::before{content:"○ ";color:#7a8ea3}.ans{margin:4pt 0 0;padding:5pt 8pt;border-radius:5pt;border-left:2.5pt solid #3d7eb5;background:#eef5fb;color:#24384d!important;font-size:10pt}.ans-label{color:#3d7eb5!important;font-weight:800}.vocab .word{margin:0 0 8pt;padding:8pt 10pt;border:1pt solid #e3eaf2;border-radius:8pt;background:#fff;page-break-inside:avoid}.lemma-line{margin:0 0 3pt}.lemma{color:#101826!important;font-size:11.5pt;font-weight:800;margin-right:5pt}.gram{color:#5c6673!important;font-size:9.5pt;margin-right:5pt}.ipa{color:#4a5a6c!important;font-family:' + FONT_IPA + ';font-size:9.5pt}.gloss{color:#2f6b9a!important;font-weight:700}.sense{margin-top:2pt}.sense-n{color:#6a7583!important;margin-right:3pt;font-weight:700}.ex,.col,.aside{margin:2pt 0 0;padding-left:8pt;color:#556172!important;font-size:10pt;border-left:1.2pt solid #cfd9e4}table.cap,table.rev{width:100%;border-collapse:collapse;font-size:10pt;border:1pt solid #e0e7ef;border-radius:7pt;overflow:hidden}table.cap th,table.rev th{width:4.5em;padding:5pt 8pt;text-align:left;vertical-align:top;color:#2f6b9a!important;font-weight:800;font-variant-numeric:tabular-nums;white-space:nowrap;background:#f4f8fc}table.cap td,table.rev td{padding:5pt 8pt;vertical-align:top;color:#1a1f27!important;border-top:.5pt solid #e8eef4}table.cap tr:nth-child(even) td,table.cap tr:nth-child(even) th,table.rev tr:nth-child(even) td,table.rev tr:nth-child(even) th{background:#fafcfe}table.rev th{width:38%;color:#1a1f27!important}.empty{color:#8a93a0!important}.foot{margin-top:16pt;padding-top:8pt;border-top:.8pt solid #d5dee8;color:#7a8491!important;font-size:8.5pt;text-align:center}.print-tip{margin:0 0 12pt;padding:6pt 10pt;border-radius:6pt;background:#f6f8fb;color:#6a7583!important;font-size:8.5pt}@media print{.print-tip{display:none!important}.cover,.unit,.word{break-inside:avoid}.sec-h{break-after:avoid}}@media screen{body{padding:18pt;background:#eef2f6!important}.wrap{padding:18pt 20pt 22pt;border:1pt solid #d7e0ea;border-radius:12pt;background:#fff;box-shadow:0 8pt 28pt rgba(20,40,70,.08)}}';

    function buildHandoutHtml(payload, includeAnswers) {
      var meta = payload.meta || {};
      var sections = payload.sections || [];
      var toc = sections.map(function (s, i) {
        return '<li><span class="n">' + String(i + 1).padStart(2, '0') + '</span><span class="t">' + esc(s.title || '') + '</span></li>';
      }).join('');
      var body = sections.map(function (s, i) {
        return '<section class="sec"><div class="sec-h"><span class="n">' + String(i + 1).padStart(2, '0') + '</span><h2>' + esc(s.title || '') + '</h2></div>' + renderSectionBody(s, meta, includeAnswers) + '</section>';
      }).join('');
      var edition = includeAnswers ? '' : '<span class="pill">' + esc(exportMeta.practiceEdition || '') + '</span>';
      return '<!DOCTYPE html><html lang="' + esc(exportMeta.lang || 'en') + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + esc(meta.title || 'BALS') + '</title><style>' + PDF_CSS + '</style></head><body><div class="wrap" id="handout"><header class="cover"><div class="brand-row"><p class="brand">' + esc(meta.brand || 'BALS') + '</p><p class="brand-sub">' + esc(meta.kicker || '') + '</p></div><h1>' + esc(meta.title || '') + '</h1><div class="meta"><span class="pill">' + esc(meta.target_label || '') + ' · ' + esc(meta.target || '') + '</span><span class="pill">' + esc(meta.native_label || '') + ' · ' + esc(meta.native || '') + '</span>' + edition + '</div><div class="toc-box"><p class="toc-title">' + esc(meta.contents || '') + '</p><ol class="toc">' + toc + '</ol></div></header><p class="print-tip">' + esc(exportMeta.printTip || '') + '</p>' + body + '<footer class="foot">' + esc(meta.footer || '') + '</footer></div></body></html>';
    }

    function collectPlainText(payload, includeAnswers) {
      var meta = payload.meta || {};
      var sections = payload.sections || [];
      var parts = [meta.brand || 'BALS', meta.title || '', (meta.target_label || '') + ': ' + (meta.target || ''), (meta.native_label || '') + ': ' + (meta.native || ''), '', meta.contents || ''];
      sections.forEach(function (s, i) { parts.push((i + 1) + '. ' + (s.title || '')); });
      sections.forEach(function (s, i) {
        var host = document.createElement('div');
        host.innerHTML = renderSectionBody(s, meta, includeAnswers !== false);
        parts.push('', (i + 1) + '. ' + (s.title || ''), host.innerText.replace(/\n{3,}/g, '\n\n').trim());
      });
      return parts.join('\n').trim() + '\n';
    }

    function triggerDownload(blob, filename) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a'); a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    }

    function openHandoutPdf(payload, includeAnswers) {
      var html = buildHandoutHtml(payload, includeAnswers !== false);
      var w = window.open('', '_blank');
      if (!w) throw new Error('Popup blocked');
      w.document.open(); w.document.write(html); w.document.close();
      setTimeout(function () { try { w.document.title = (payload.meta && payload.meta.title) || 'BALS'; w.focus(); w.print(); } catch (e) {} }, 400);
    }

    function runPdfExport(btn, includeAnswers) {
      if (!btn) return;
      var label = btn.innerHTML;
      btn.disabled = true;
      if (pdfBtn) pdfBtn.disabled = true;
      if (pdfNoAnsBtn) pdfNoAnsBtn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' + (exportMeta.generating || 'Generating…');
      loadPayload().then(function (payload) {
        openHandoutPdf(payload, includeAnswers);
      }).catch(function (err) {
        console.error(err);
        alert(exportMeta.pdfError || 'Could not open PDF preview.');
      }).then(function () {
        btn.innerHTML = label;
        if (pdfBtn) pdfBtn.disabled = false;
        if (pdfNoAnsBtn) pdfNoAnsBtn.disabled = false;
      });
    }

    if (txtBtn) txtBtn.addEventListener('click', function () {
      var label = txtBtn.innerHTML; txtBtn.disabled = true;
      loadPayload().then(function (payload) {
        triggerDownload(new Blob([collectPlainText(payload, true)], { type: 'text/plain;charset=utf-8' }), safeFilename(payload.meta && payload.meta.title, '.txt'));
      }).catch(function (err) {
        console.error(err); alert(exportMeta.txtError || 'Could not load lesson data.');
      }).then(function () { txtBtn.disabled = false; txtBtn.innerHTML = label; });
    });
    if (pdfBtn) pdfBtn.addEventListener('click', function () { runPdfExport(pdfBtn, true); });
    if (pdfNoAnsBtn) pdfNoAnsBtn.addEventListener('click', function () { runPdfExport(pdfNoAnsBtn, false); });
  })();

  /* ---- Floating / resizable YouTube player ---- */
  (function () {
    var player = document.getElementById('lessonPlayer');
    var closeFloatBtn = document.getElementById('playerCloseFloatBtn');
    var showBtn = document.getElementById('playerShowBtn');
    if (!player) return;
    var drag = null, resize = null;
    var minW = 260, barH = 40, storageKey = 'bals-float-player-v4';
    function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }
    function placeDefault() {
      var w = minW, h = Math.round(w * 9 / 16) + barH;
      player.style.width = w + 'px'; player.style.height = h + 'px';
      player.style.left = (window.innerWidth - w - 16) + 'px'; player.style.top = '72px';
    }
    function saveGeom() {
      try { localStorage.setItem(storageKey, JSON.stringify({ w: player.offsetWidth, h: player.offsetHeight, left: player.offsetLeft, top: player.offsetTop })); } catch (e) {}
    }
    function loadGeom() {
      try {
        var raw = localStorage.getItem(storageKey); if (!raw) return false;
        var g = JSON.parse(raw);
        var w = clamp(g.w || 360, minW, Math.min(720, window.innerWidth - 24));
        var h = clamp(g.h || Math.round(w * 9 / 16) + barH, minW * 9 / 16 + barH, window.innerHeight - 24);
        player.style.width = w + 'px'; player.style.height = h + 'px';
        player.style.left = clamp(g.left != null ? g.left : 20, 8, window.innerWidth - w - 8) + 'px';
        player.style.top = clamp(g.top != null ? g.top : 20, 8, window.innerHeight - h - 8) + 'px';
        return true;
      } catch (e) { return false; }
    }
    function showPlayer() { player.classList.remove('is-hidden'); if (showBtn) showBtn.classList.add('d-none'); if (!loadGeom()) placeDefault(); }
    function hidePlayer() { saveGeom(); player.classList.add('is-hidden'); if (showBtn) showBtn.classList.remove('d-none'); }
    if (!loadGeom()) placeDefault();
    if (closeFloatBtn) closeFloatBtn.addEventListener('click', hidePlayer);
    if (showBtn) showBtn.addEventListener('click', showPlayer);
    var bar = player.querySelector('.player-float-bar');
    if (bar) {
      bar.addEventListener('pointerdown', function (e) {
        if (e.target.closest('.player-float-btn')) return;
        var rect = player.getBoundingClientRect();
        drag = { id: e.pointerId, ox: e.clientX - rect.left, oy: e.clientY - rect.top };
        bar.setPointerCapture(e.pointerId); e.preventDefault();
      });
      bar.addEventListener('pointermove', function (e) {
        if (!drag || e.pointerId !== drag.id) return;
        var w = player.offsetWidth, h = player.offsetHeight;
        player.style.left = clamp(e.clientX - drag.ox, 8, window.innerWidth - w - 8) + 'px';
        player.style.top = clamp(e.clientY - drag.oy, 8, window.innerHeight - h - 8) + 'px';
      });
      var endDrag = function (e) { if (drag && e.pointerId === drag.id) { drag = null; saveGeom(); } };
      bar.addEventListener('pointerup', endDrag);
      bar.addEventListener('pointercancel', endDrag);
    }
    var handle = player.querySelector('.player-resize-handle');
    if (handle) {
      handle.addEventListener('pointerdown', function (e) {
        var rect = player.getBoundingClientRect();
        resize = { id: e.pointerId, startX: e.clientX, startW: rect.width };
        handle.setPointerCapture(e.pointerId); e.preventDefault(); e.stopPropagation();
      });
      handle.addEventListener('pointermove', function (e) {
        if (!resize || e.pointerId !== resize.id) return;
        var dw = e.clientX - resize.startX;
        var w = clamp(resize.startW + dw, minW, Math.min(720, window.innerWidth - 24));
        var h = Math.round(w * 9 / 16) + barH;
        var maxH = window.innerHeight - 24;
        if (h > maxH) { h = maxH; w = Math.max(minW, Math.round((h - barH) * 16 / 9)); }
        player.style.width = w + 'px'; player.style.height = h + 'px';
        player.style.left = clamp(player.offsetLeft, 8, window.innerWidth - w - 8) + 'px';
        player.style.top = clamp(player.offsetTop, 8, window.innerHeight - h - 8) + 'px';
      });
      var endResize = function (e) { if (resize && e.pointerId === resize.id) { resize = null; saveGeom(); } };
      handle.addEventListener('pointerup', endResize);
      handle.addEventListener('pointercancel', endResize);
    }
    window.addEventListener('resize', function () {
      if (player.classList.contains('is-hidden')) return;
      var w = player.offsetWidth, h = player.offsetHeight;
      player.style.left = clamp(player.offsetLeft, 8, window.innerWidth - w - 8) + 'px';
      player.style.top = clamp(player.offsetTop, 8, window.innerHeight - h - 8) + 'px';
    });
  })();
})();
