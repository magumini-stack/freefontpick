/* 타닥타닥 구독 폰트 칸 (2026-10-01)
 *
 * 폰트픽에서 타닥타닥(유료 구독)으로 사람을 보내는 장치다. 사용자님이 고른 자리:
 *   메인          히어로 바로 아래 빨간 띠 — 카드 8장 가로 스크롤 (#subBand) — 10/1 쓰는 자리 바 아래(옛 광고 띠 자리)로 옮김
 *   전체 폰트 보기  '모양으로 찾기' 맨 앞 빨간 칩(#subChip) + 무료 목록 첫 줄 4장(#subPin)
 *                 칩을 누르면(#subscribe) 구독 폰트만 모아 보는 화면(#subView)
 *
 * 지킨 것
 *   - 무료 목록에 섞지 않는다. 카드마다 '구독' 배지와 플랜 이름을 붙이고,
 *     버튼은 '타닥타닥에서 보기 ↗' 로 새 창. 어디로 가는지 누르기 전에 알 수 있게.
 *   - 폰트별 상품 페이지는 없어서 그 폰트가 든 묶음 플랜 페이지로 보낸다.
 *   - 첫 줄 고정 4장은 관리자가 '구독 폰트' 탭에서 고른다(/api/subscribe-picks, 10/1 사용자님 지시).
 *     고른 폰트가 모자라면 제작사를 돌아가며 채운다. New 배지·New 먼저는 뺐다.
 *   - 폰트 총수는 화면에 쓰지 않는다(폰트픽 규칙).
 *
 * 자료는 tools/build_subfonts.py 가 만든 /static/subfonts/fonts.json 과 견본 문구
 * 글자만 담은 웹폰트다. 그래서 '미리 써보기'에 친 문구는 구독 카드에 적용하지 않는다
 * (없는 글자가 빈칸으로 나온다) — 늘 견본 문구로 그린다.
 */
(function () {
  'use strict';
  var DATA_URL = '/static/subfonts/fonts.json';
  var PICKS_URL = '/api/subscribe-picks';
  var PLAN_BASE = 'https://tdtd.io/_subpage/kor/buy/list.php?viewMode=view&idx=';
  var PLANS = [['Basic Plan', 6], ['Premium Plan', 11], ['Calli Font Plan', 26], ['Basic Plus Plan', 23]];
  var VENDORS = ['전체', '타닥타닥', '상상토끼', 'RakFont'];
  var CATS = ['전체', '고딕', '명조', '손글씨', '캘리', '디자인'];

  var CSS = [
    ':root{--ffs-red:#e60012;--ffs-red-ink:#c4000f}',
    '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ffs-red:#ff4d55;--ffs-red-ink:#ff7178}}',
    ':root[data-theme="dark"]{--ffs-red:#ff4d55;--ffs-red-ink:#ff7178}',
    '.ffs-box{border:1px solid var(--ffs-red);border-radius:4px;background:var(--bg-card);padding:20px 20px 18px}',
    '.ffs-band{margin:0 0 26px}',
    '.ffs-head{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:flex-end;justify-content:space-between;margin-bottom:14px}',
    '.ffs-kick{display:inline-block;font-size:13px;font-weight:800;color:var(--ffs-red);margin-bottom:6px}',
    '.ffs-head h2{margin:0;font-size:24px;font-weight:800;letter-spacing:-.6px;line-height:1.3;color:var(--text-primary);text-wrap:balance}',
    '.ffs-head p{margin:4px 0 0;color:var(--text-secondary);font-size:13.5px;max-width:62ch}',
    '.ffs-cta{display:inline-flex;align-items:center;gap:6px;font-weight:800;font-size:14px;color:var(--ffs-red-ink);background:var(--bg-card);border:1px solid var(--border);border-radius:14px;padding:9px 16px;text-decoration:none;white-space:nowrap;transition:border-color .15s}',
    '.ffs-cta:hover{border-color:var(--text-primary)}',
    '.ffs-row{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(240px,1fr);gap:12px;overflow-x:auto;padding-bottom:6px;scroll-snap-type:x mandatory}',
    '.ffs-row .ffs-card{scroll-snap-align:start}',
    '.ffs-plans{display:flex;gap:6px;flex-wrap:wrap;margin-top:14px}',
    '.ffs-plans a{font-size:12px;font-weight:700;color:var(--ffs-red-ink);text-decoration:none;border:1px solid var(--border);background:var(--bg-card);border-radius:14px;padding:4px 9px;white-space:nowrap}',
    '.ffs-plans a:hover{border-color:var(--text-primary)}',
    '.ffs-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}',
    '@media(max-width:1100px){.ffs-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}',
    '@media(max-width:820px){.ffs-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.ffs-head h2{font-size:20px}.ffs-box{padding:16px 14px 14px}}',
    '@media(max-width:520px){.ffs-grid{grid-template-columns:minmax(0,1fr)}.ffs-row{grid-auto-columns:minmax(78%,1fr)}}',
    '.ffs-card{display:flex;flex-direction:column;gap:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:4px;padding:16px 16px 14px;text-decoration:none;color:var(--text-primary);transition:border-color .15s,box-shadow .15s;min-width:0}',
    '.ffs-card:hover{border-color:var(--border-hover)}',
    '.ffs-card:focus-visible,.ffs-cta:focus-visible,.ffs-chip:focus-visible,.ffs-fchip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}',
    '.ffs-top{display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-width:0}',
    '.ffs-badge{font-size:11px;font-weight:800;color:var(--ffs-red)}',
    '.ffs-plan{font-size:11px;font-weight:700;color:var(--text-secondary);border:1px solid var(--border);border-radius:2px;padding:0 6px}',
    '.ffs-nm{font-size:13.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}',
    '.ffs-meta{font-size:11.5px;color:var(--text-muted);margin-top:-8px}',
    '.ffs-pv{font-size:23px;line-height:1.35;min-height:2.7em;overflow-wrap:anywhere;word-break:keep-all;color:var(--text-primary)}',
    '.ffs-go{margin-top:auto;display:flex;justify-content:space-between;align-items:center;border-top:1px solid var(--border);padding-top:11px;font-size:12.5px;font-weight:800;color:var(--ffs-red-ink)}',
    '.ffs-go span:last-child{font-weight:400;color:var(--text-muted);font-size:11.5px}',
    '.ffs-chip{flex:0 0 auto;font:inherit;font-size:13px;font-weight:700;border:1px solid var(--border);border-radius:14px;padding:6px 11px;cursor:pointer;white-space:nowrap;color:var(--ffs-red-ink);background:var(--bg-card);transition:border-color .15s;margin-right:6px}',
    '.ffs-chip:hover{border-color:var(--text-primary)}',
    '.ffs-chip[aria-pressed="true"]{border-color:var(--text-primary);font-weight:800}',
    '.ffs-pin{margin:0 0 16px;padding:14px}',
    '.ffs-pin-h{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}',
    '.ffs-pin-h b{font-size:15px;font-weight:800;color:var(--text-primary)}',
    '.ffs-pin-h b span{color:var(--ffs-red-ink)}',
    '.ffs-pin-h a{font-size:13px;font-weight:800;color:var(--ffs-red-ink);text-decoration:none}',
    '.ffs-view{margin:0 0 30px}',
    '.ffs-intro{display:flex;gap:16px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;margin:0 0 14px;padding:16px 18px}',
    '.ffs-intro h2{margin:0 0 4px;font-size:18px;font-weight:800;letter-spacing:-.3px;color:var(--text-primary)}',
    '.ffs-intro p{margin:0;color:var(--text-secondary);font-size:13.5px;max-width:70ch}',
    '.ffs-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px}',
    '.ffs-lbl{font-size:12.5px;color:var(--text-muted);margin-right:2px}',
    '.ffs-sep{width:1px;align-self:stretch;background:var(--border);margin:2px 4px}',
    '.ffs-fchip{font:inherit;font-size:13px;border:1px solid var(--border);background:var(--bg-card);color:var(--text-secondary);border-radius:14px;padding:5px 11px;cursor:pointer;white-space:nowrap}',
    '.ffs-fchip:hover{border-color:var(--text-primary);color:var(--text-primary)}',
    '.ffs-fchip[aria-pressed="true"]{background:var(--text-primary);border-color:var(--text-primary);color:var(--bg-card)}',
    '#fontGrid[hidden]{display:none!important}',
    '.ffs-empty{grid-column:1/-1;text-align:center;color:var(--text-muted);padding:40px}',
    '@media (prefers-reduced-motion:reduce){.ffs-card{transition:none}}'
  ].join('\n');

  var data = null, loading = null, sample = '', picked = [];
  var loadedFaces = {};
  var io = null;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function planUrl(idx, medium) {
    return PLAN_BASE + idx + '&utm_source=freefontpick&utm_medium=' + medium;
  }
  function injectCss() {
    if (document.getElementById('ffsCss')) return;
    var st = document.createElement('style');
    st.id = 'ffsCss';
    st.textContent = CSS;
    document.head.appendChild(st);
  }
  function load() {
    if (data) return Promise.resolve(data);
    if (!loading) {
      // 관리자가 고른 폰트는 못 불러와도 칸은 그린다 — 그때는 제작사를 돌아가며 채운다.
      var picksReq = fetch(PICKS_URL).then(function (r) { return r.ok ? r.json() : { picks: [] }; })
        .catch(function () { return { picks: [] }; });
      loading = Promise.all([fetch(DATA_URL).then(function (r) { return r.json(); }), picksReq]).then(function (res) {
        var d = res[0], hs = (res[1] && res[1].picks) || [];
        sample = d.sample || '';
        var byH = {};
        d.fonts.forEach(function (f) { byH[f.h] = f; });
        // 고른 폰트를 고른 순서대로 앞에, 나머지는 자료 순서(제작사 → 이름) 그대로.
        picked = hs.map(function (h) { return byH[h]; }).filter(Boolean);
        data = picked.concat(d.fonts.filter(function (f) { return picked.indexOf(f) < 0; }));
        return data;
      });
    }
    return loading;
  }

  /* 웹폰트는 카드가 화면에 들어올 때 하나씩 부른다 — 구독 칸 전체를 펼쳐도
     보이는 카드만 받는다. */
  function loadFace(h) {
    if (loadedFaces[h] || !window.FontFace) return;
    loadedFaces[h] = 1;
    var face = new FontFace('ffs-' + h, 'url(/static/subfonts/' + h + '.woff2) format("woff2")', { display: 'swap' });
    face.load().then(function (f) { document.fonts.add(f); }).catch(function () {});
  }
  function observe(root) {
    var els = root.querySelectorAll('[data-ffs-h]');
    if (!('IntersectionObserver' in window)) {
      els.forEach(function (el) { loadFace(el.getAttribute('data-ffs-h')); });
      return;
    }
    if (!io) {
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { loadFace(e.target.getAttribute('data-ffs-h')); io.unobserve(e.target); }
        });
      }, { rootMargin: '300px' });
    }
    els.forEach(function (el) { io.observe(el); });
  }

  function card(f, medium) {
    return '<a class="ffs-card" href="' + esc(planUrl(f.i, medium)) + '" target="_blank" rel="noopener"' +
      ' aria-label="' + esc(f.n) + ' — 타닥타닥 ' + esc(f.p) + ' 페이지 새 창으로 열기">' +
      '<div class="ffs-top"><span class="ffs-badge">구독</span><span class="ffs-plan">' + esc(f.p) + '</span></div>' +
      '<div class="ffs-nm">' + esc(f.n) + '</div>' +
      '<div class="ffs-meta">' + esc(f.v) + ' · ' + esc(f.c) + (f.s > 1 ? ' · 굵기 ' + f.s + '종' : '') + '</div>' +
      '<div class="ffs-pv" data-ffs-h="' + esc(f.h) + '" style="font-family:\'ffs-' + esc(f.h) + '\',\'Noto Sans KR\',sans-serif;font-weight:' + (f.w || 400) + '">' + esc(sample) + '</div>' +
      '<div class="ffs-go"><span>타닥타닥에서 보기 ↗</span><span>tdtd.io</span></div></a>';
  }
  function planLinks(medium) {
    return PLANS.map(function (p) {
      return '<a href="' + esc(planUrl(p[1], medium)) + '" target="_blank" rel="noopener">' + esc(p[0]) + ' ↗</a>';
    }).join('');
  }
  /* 관리자가 고른 폰트를 먼저 채우고, 모자라면 제작사를 돌아가며 섞는다. */
  function pick(n) {
    var out = picked.slice(0, n);
    if (out.length >= n) return out;
    var by = {}, k = 0;
    data.forEach(function (f) { if (picked.indexOf(f) < 0) (by[f.v] = by[f.v] || []).push(f); });
    var vs = ['타닥타닥', '상상토끼', 'RakFont'];
    while (out.length < n) {
      var added = false;
      vs.forEach(function (v) { var f = (by[v] || [])[k]; if (f && out.length < n) { out.push(f); added = true; } });
      if (!added) break;
      k++;
    }
    return out;
  }

  /* ── 메인: 히어로 아래 띠 ── */
  function mountBand(el) {
    if (!el) return;
    injectCss();
    load().then(function () {
      el.className = 'ffs-box ffs-band';
      el.setAttribute('aria-label', '타닥타닥 구독 폰트');
      el.innerHTML =
        '<div class="ffs-head"><div><span class="ffs-kick">타닥타닥 구독</span>' +
        '<h2>무료로 부족할 땐, 타닥타닥 구독 폰트</h2>' +
        '<p>폰트 구독 서비스 타닥타닥의 유료 폰트입니다. 구독 플랜으로 손글씨·캘리·디자인 폰트를 마음껏 쓸 수 있습니다.</p></div>' +
        '<a class="ffs-cta" href="/fonts#subscribe">구독 폰트 모두 보기 →</a></div>' +
        '<div class="ffs-row">' + pick(8).map(function (f) { return card(f, 'home_band'); }).join('') + '</div>' +
        '<div class="ffs-plans">' + planLinks('home_band') + '</div>';
      el.hidden = false;
      observe(el);
    }).catch(function () { el.hidden = true; });
  }

  /* ── 전체 폰트 보기 ── */
  var F = null, vendor = '전체', cat = '전체';
  function renderView() {
    var rows = data.filter(function (f) {
      return (vendor === '전체' || f.v === vendor) && (cat === '전체' || f.c === cat);
    });
    var chips = function (list, cur, key) {
      return list.map(function (v) {
        return '<button type="button" class="ffs-fchip" data-' + key + '="' + esc(v) + '" aria-pressed="' + (v === cur) + '">' + esc(v) + '</button>';
      }).join('');
    };
    F.view.innerHTML =
      '<section class="ffs-box ffs-intro"><div><h2>타닥타닥 구독 폰트</h2>' +
      '<p>폰트 구독 서비스 타닥타닥에서 쓸 수 있는 유료 폰트입니다. 무료 폰트와는 따로 모았습니다. ' +
      '폰트를 누르면 그 폰트가 들어 있는 구독 플랜 페이지가 열립니다.</p></div>' +
      '<div class="ffs-plans" style="margin-top:0">' + planLinks('fonts_list') + '</div></section>' +
      '<div class="ffs-filters"><span class="ffs-lbl">제작사</span>' + chips(VENDORS, vendor, 'v') +
      '<span class="ffs-sep" aria-hidden="true"></span><span class="ffs-lbl">갈래</span>' + chips(CATS, cat, 'c') + '</div>' +
      '<div class="ffs-grid">' + (rows.length ? rows.map(function (f) { return card(f, 'fonts_list'); }).join('')
        : '<div class="ffs-empty">이 조건의 구독 폰트가 없습니다</div>') + '</div>';
    observe(F.view);
  }
  function setMode(on) {
    if (!F) return;
    F.chip.setAttribute('aria-pressed', on ? 'true' : 'false');
    F.view.hidden = !on;
    F.grid.hidden = on;
    syncPin();
    if (on) {
      load().then(function () { renderView(); });
      // 보던 '모양' 칩 표시를 지운다 — 지금 보는 것은 구독 폰트다.
      document.querySelectorAll('#tagsScroll .tag.active').forEach(function (t) { t.classList.remove('active'); });
    }
  }
  /* 구독 화면에 있으면 무료 목록으로 — 주소의 #subscribe 는 hashchange 없이 지운다
     (route() 가 다시 돌면 보던 카테고리·검색을 지운다). */
  function leave() {
    if (!F || F.chip.getAttribute('aria-pressed') !== 'true') return;
    if (location.hash === '#subscribe') history.replaceState(history.state, '', location.pathname + location.search);
    setMode(false);
  }
  /* 첫 줄 고정은 무료 목록을 그대로 훑을 때만 보인다 — 검색 중이거나 구독 화면이면 감춘다. */
  function syncPin() {
    if (!F || !F.pin) return;
    var q = document.getElementById('globalSearch');
    var searching = q && q.value.trim();
    F.pin.hidden = F.chip.getAttribute('aria-pressed') === 'true' || !!searching || !F.pinReady;
  }
  function mountFonts(opts) {
    if (!opts || !opts.chip || !opts.view || !opts.grid) return;
    injectCss();
    F = { chip: opts.chip, view: opts.view, grid: opts.grid, pin: opts.pin, pinReady: false };
    F.chip.addEventListener('click', function () {
      if (F.chip.getAttribute('aria-pressed') === 'true') { location.hash = ''; }
      else { location.hash = '#subscribe'; }
    });
    F.view.addEventListener('click', function (e) {
      var v = e.target.closest('[data-v]'), c = e.target.closest('[data-c]');
      if (v) { vendor = v.getAttribute('data-v'); renderView(); }
      if (c) { cat = c.getAttribute('data-c'); renderView(); }
    });
    var onHash = function () { setMode(location.hash === '#subscribe'); };
    window.addEventListener('hashchange', onHash);
    var q = document.getElementById('globalSearch');
    if (q) q.addEventListener('input', function () { if (q.value.trim()) leave(); syncPin(); });
    /* 구독 화면에서 '무료전체'·모양 칩을 누르면 무료 목록으로 돌아간다.
       칩(setTag)은 history.pushState 로 주소를 바꿔 hashchange 가 오지 않으므로 직접 나간다.
       주소는 setTag 가 '#tag/…' 또는 맨 주소로 바꾼다. */
    var bar = document.getElementById('tagsScroll');
    if (bar) bar.addEventListener('click', function (e) { if (e.target.closest('.tag')) leave(); });
    load().then(function () {
      if (F.pin) {
        F.pin.className = 'ffs-box ffs-pin';
        F.pin.innerHTML =
          '<div class="ffs-pin-h"><b><span>구독 폰트</span> · 이런 폰트는 어떠세요</b>' +
          '<a href="#subscribe">구독 폰트 모두 보기 →</a></div>' +
          '<div class="ffs-grid">' + pick(4).map(function (f) { return card(f, 'fonts_pin'); }).join('') + '</div>';
        F.pinReady = true;
        observe(F.pin);
      }
      onHash();
    }).catch(function () { F.chip.hidden = true; });
  }

  window.FFPSub = { mountBand: mountBand, mountFonts: mountFonts };
})();
