(function () {
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch];
    });
  }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({headers: {'Content-Type': 'application/json'}}, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function setNotice(text) { $('notice').textContent = text || ''; }

  function reasonClass(code) {
    return code === 'CROSS_BATCH_DIFF' ? 'reason-diff' : (code === 'PAYER_COVERAGE' ? 'reason-cover' : 'reason-fill');
  }

  function evidenceHtml(evidence) {
    if (!evidence || !evidence.batch_evidence || !evidence.batch_evidence.length) return '<span class="empty">无</span>';
    var items = evidence.batch_evidence.map(function (batch) {
      var lines = batch.payments.map(function (p) {
        return '<li>' + esc(p.payer) + ' · ' + esc(p.claim_id) + ' · 核准 ' + esc(p.approved_cents) + ' 分</li>';
      }).join('');
      return '<li><code>' + esc(batch.run_id) + '</code> 给付 ' + esc(batch.payment_total) +
        ' 分 <small>' + esc(batch.signed_at) + '</small><ul>' + lines + '</ul></li>';
    }).join('');
    return '<details><summary>' + evidence.batch_evidence.length + ' 个批次依据</summary><ul>' + items + '</ul></details>';
  }

  function renderPeriod(view) {
    if (!view) {
      $('sample-meta').textContent = '尚未生成';
      $('sample-body').innerHTML = '<tr><td class="empty" colspan="6">先签发批次，再生成抽检名单</td></tr>';
      $('sample-publish').disabled = true;
      return;
    }
    $('sample-meta').textContent = view.period_no + ' · ' + view.status + ' · 已占 ' + view.filled + '/' + view.quota;
    $('sample-publish').disabled = view.status !== 'BUILDING' || view.filled === 0;
    if (!view.selections.length) {
      $('sample-body').innerHTML = '<tr><td class="empty" colspan="6">当期候选宇宙中暂无可抽检理赔组</td></tr>';
      return;
    }
    $('sample-body').innerHTML = view.selections.map(function (item) {
      var ev = item.evidence || {};
      return '<tr>' +
        '<td class="num">' + esc(item.rank_no + 1) + '</td>' +
        '<td>' + esc(item.group_key) + '</td>' +
        '<td>' + esc((ev.payers || []).join(', ')) + '</td>' +
        '<td><span class="sample-reason ' + reasonClass(item.reason_code) + '">' + esc(item.reason_code) + '</span><br><small>' + esc(item.reason_detail) + '</small></td>' +
        '<td class="num">' + esc(ev.payment_gap || 0) + '</td>' +
        '<td>' + evidenceHtml(ev) + '</td>' +
        '</tr>';
    }).join('');
  }

  async function loadCurrent() {
    try {
      renderPeriod(await request('/api/sampling/periods/current'));
    } catch (error) {
      renderPeriod(null);
    }
  }

  async function generate() {
    try {
      setNotice('');
      $('sample-generate').disabled = true;
      var quota = parseInt($('sample-quota').value, 10);
      var view = await request('/api/sampling/generate', {method: 'POST', body: JSON.stringify({quota: quota})});
      renderPeriod(view);
    } catch (error) { setNotice(error.message); }
    finally { $('sample-generate').disabled = false; }
  }

  async function publish() {
    try {
      setNotice('');
      var view = await request('/api/sampling/publish', {method: 'POST', body: '{}'});
      renderPeriod(view);
    } catch (error) { setNotice(error.message); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('sample-generate').addEventListener('click', generate);
    $('sample-publish').addEventListener('click', publish);
    loadCurrent();
  });
})();
