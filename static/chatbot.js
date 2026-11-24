/* 폰트픽 폰트 추천 챗봇 — 모든 페이지 우측 하단 말풍선 (2026-11-24)
 *
 * 사용자님: "모든 페이지 우측 하단에 챗봇 상담처럼, 말풍선 아이콘, 채팅창, 폰트 추천은 리스트로, 클릭하면 상세페이지로 가도 채팅창은 그대로"
 * 참고: fontmoa.com 의 '폰트 추천 AI'. 다만 여기는 AI(API) 없이, 추천 자판기(/font-vending)와 같은 데이터·같은 뽑기 규칙을 쓴다.
 *   - 데이터: /static/vending/data.json (쓰임×느낌 48개 통 + 폰트별 점수·인기 순위). 채팅창을 처음 열 때만 받는다.
 *   - 흐름: 질문 3개(쓰임·느낌·인기)를 단추로 묻고 → 3종 리스트. 이어서 글로 "더 귀엽게", "명조로", "다른 거" 같은 말을 사전으로 해석해 다시 뽑는다.
 *   - 상세페이지로 가도 대화가 이어지게 sessionStorage 에 저장하고, 새 페이지에서 열린 채로 복원한다(같은 탭).
 * 이 파일은 header.py 의 inject_header 가 </head> 앞에 defer 로 끼운다. 규칙 판은 font-vending.html 의 poolFor·drawPage 를 그대로 옮긴 것이다.
 */
(function () {
  'use strict';
  if (window.__ffc) return;
  window.__ffc = 1;
  if (/^\/(font-vending|admin)/.test(location.pathname)) return;   // 자판기 화면에선 겹치니 뺀다

  var KEY = 'ffc.v1';
  var DATA_URL = '/static/vending/data.json?v=20261113';
  var USES = [['썸네일', '유튜브 썸네일'], ['자막', '영상 자막'], ['인스타', '인스타 피드'], ['블로그', '문서·웹 본문'],
    ['PPT', 'PPT·발표'], ['포스터', '포스터·전단'], ['로고', '로고·간판'], ['굿즈', '굿즈·스티커']];
  var MOODS = [['깔끔한', '깔끔한'], ['귀여운', '귀여운'], ['감성적인', '감성적인'], ['강렬한', '강렬한'], ['고급스러운', '고급스러운'], ['레트로', '레트로']];
  var MODES = [['hot', '인기 폰트'], ['hidden', '숨은 보석'], ['any', '상관없어요']];
  var POP_ADD = {hot: [100, 60, 60], any: [35, 20, 20], hidden: [0, 0, 0]};
  var TEMP = [15, 22, 25];
  var WANT_W = {'썸네일': 900, '자막': 500, '인스타': 500, '블로그': 400, 'PPT': 600, '포스터': 900, '로고': 500, '굿즈': 900};

  // 말을 조건으로 바꾸는 사전 (소문자·공백 없앤 글에서 찾는다)
  var K_USE = {
    '썸네일': ['썸네일'], '자막': ['자막', '브이로그', '영상', '릴스', '쇼츠'], '인스타': ['인스타', '피드', '카드뉴스', 'sns'],
    '블로그': ['블로그', '티스토리', '웹본문', '웹페이지', '문서', '본문'],
    'PPT': ['ppt', '피피티', '발표', '프레젠테이션', '보고서'],
    '포스터': ['포스터', '전단', '현수막', '메뉴판', '팜플렛', '광고', '배너'], '로고': ['로고', '간판', '브랜드', '상호', '명함'],
    '굿즈': ['굿즈', '스티커', '키링', '포장', '패키지']};
  var K_MOOD = {
    '깔끔한': ['깔끔', '단정', '심플', '정갈', '모던', '깨끗', '정돈'], '귀여운': ['귀여', '귀욤', '아기자기', '말랑', '동글', '발랄', '아기', '앙증'],
    '감성적인': ['감성', '따뜻', '서정', '아날로그', '청첩', '편지', '잔잔', '포근'], '강렬한': ['강렬', '임팩트', '눈에띄', '시선', '파워', '자극'],
    '고급스러운': ['고급', '럭셔리', '우아', '격식', '품격', '세련'], '레트로': ['레트로', '옛날', '복고', '빈티지', '올드']};
  var K_GRP = {'고딕': ['고딕', '산세리프'], '명조': ['명조', '세리프'], '손글씨': ['손글씨', '필기', '손으로'], '붓글씨': ['붓글씨', '붓', '캘리'], '장식': ['장식', '디스플레이']};
  var K_POP = {hot: ['인기', '유명', '많이쓰는', '핫', '대세', '트렌디'], hidden: ['숨은', '보석', '희귀', '안쓰는', '아무도', '특이', '독특', '나만'], any: ['상관없']};
  var K_MORE = ['다른', '더보', '더줘', '또', '다시', '바꿔', '새로', '말고', '다음'];
  var K_RESET = ['처음', '리셋', '초기', '새로시작'];
  var K_BOLD = ['굵', '두꺼', '볼드', '묵직'], K_THIN = ['얇', '가는', '가늘', '라이트', '슬림'];
  var K_THANKS = ['고마', '감사', '굿'];
  var EXAMPLES = ['브이로그 자막용 폰트', '감성 손글씨', '유튜브 썸네일 제목', '문서·웹 본문용 폰트', '굵고 임팩트 있는 포스터 제목'];

  var D = null, F = null, loading = null;
  var S = load() || {open: false, msgs: [], sel: {}, seen: {}, grp: null, wt: null, step: 0, tipSeen: 0};
  var root, panel, body, input, launcher, tip;

  function load() { try { return JSON.parse(sessionStorage.getItem(KEY)); } catch (e) { return null; } }
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]; }); }
  function ga(name, p) { try { if (window.gtag) window.gtag('event', name, p || {}); } catch (e) {} }

  // ── 화면 ───────────────────────────────────────────────────────
  var CSS = '' +
    '.ffc{--c:#12318B;--c2:#EEF2FB;position:fixed;right:20px;bottom:20px;z-index:99990;font-family:"Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif;font-size:14px;color:#1f2430;letter-spacing:-.01em}' +
    '.ffc *{box-sizing:border-box}' +
    // 말풍선 모양 단추 — 오른쪽 아래 모서리만 뾰족하게 해서 꼬리처럼 보이게 한다
    '.ffc-btn{position:relative;display:flex;align-items:center;gap:10px;height:66px;padding:0 22px 0 12px;border:0;border-radius:33px 33px 8px 33px;background:linear-gradient(135deg,#2547b3 0%,#12318B 55%,#0b2268 100%);color:#fff;cursor:pointer;box-shadow:0 8px 26px rgba(18,49,139,.42),inset 0 1px 0 rgba(255,255,255,.22);font:inherit;transition:transform .15s,box-shadow .15s}' +
    '.ffc-btn:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(18,49,139,.5),inset 0 1px 0 rgba(255,255,255,.22)}.ffc-btn:focus-visible{outline:3px solid #9db3ee;outline-offset:3px}' +
    '.ffc-bi{flex:none;width:42px;height:42px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,.18)}' +
    '.ffc-bt{display:flex;flex-direction:column;align-items:flex-start;line-height:1.15;text-align:left}.ffc-bt small{font-size:11px;font-weight:600;opacity:.8;letter-spacing:.02em}.ffc-bt b{font-size:17px;font-weight:800;letter-spacing:-.02em}' +
    '.ffc-btn:before{content:"";position:absolute;inset:-5px;border-radius:38px 38px 11px 38px;border:2px solid rgba(37,71,179,.35);animation:ffcp 2.6s ease-out infinite;pointer-events:none}' +
    '@keyframes ffcp{0%{opacity:.9;transform:scale(.96)}100%{opacity:0;transform:scale(1.12)}}' +
    '@media(prefers-reduced-motion:reduce){.ffc-btn:before{display:none}}' +
    '.ffc.open .ffc-btn:before{display:none}' +
    '.ffc-tip{position:absolute;right:6px;bottom:78px;background:#fff;border-radius:12px;padding:9px 13px;font-weight:600;white-space:nowrap;box-shadow:0 4px 16px rgba(0,0,0,.16);cursor:pointer;animation:ffcin .35s}' +
    '.ffc-tip:after{content:"";position:absolute;right:26px;bottom:-5px;width:10px;height:10px;background:#fff;transform:rotate(45deg)}' +
    '.ffc-panel{position:absolute;right:0;bottom:82px;width:384px;height:min(620px,calc(100vh - 110px));background:#fff;border-radius:20px;box-shadow:0 12px 48px rgba(10,20,50,.26);display:none;flex-direction:column;overflow:hidden;border:1px solid #e4e8f1}' +
    '.ffc.open .ffc-panel{display:flex}.ffc.open .ffc-tip{display:none}.ffc.anim .ffc-panel{animation:ffcin .22s}' +
    '@keyframes ffcin{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}' +
    '.ffc-head{display:flex;align-items:center;gap:11px;padding:14px 14px 13px 16px;border-bottom:1px solid #eceff5}' +
    '.ffc-ico{flex:none;width:36px;height:36px;border-radius:50%;background:var(--c);display:flex;align-items:center;justify-content:center}' +
    '.ffc-ht{flex:1;min-width:0}.ffc-ht b{display:block;font-size:15px}.ffc-ht span{display:block;font-size:11.5px;color:#6b7385;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
    '.ffc-hb{border:0;background:none;width:32px;height:32px;border-radius:8px;cursor:pointer;color:#6b7385;display:flex;align-items:center;justify-content:center;padding:0}.ffc-hb:hover{background:#f1f3f8}' +
    '.ffc-body{flex:1;overflow-y:auto;padding:16px 14px 8px;display:flex;flex-direction:column;gap:10px;scroll-behavior:smooth;overscroll-behavior:contain}' +
    '.ffc-m{max-width:88%;padding:10px 14px;border-radius:16px;line-height:1.55;word-break:keep-all;overflow-wrap:anywhere}' +
    '.ffc-b{background:#f1f3f8;border-top-left-radius:5px;align-self:flex-start}' +
    '.ffc-u{background:var(--c);color:#fff;border-top-right-radius:5px;align-self:flex-end}' +
    '.ffc-chips{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 2px}' +
    '.ffc-chip{border:1px solid #d5dbe9;background:#fff;color:#1f2430;border-radius:999px;padding:8px 13px;font:inherit;font-size:13px;cursor:pointer}' +
    '.ffc-chip:hover{border-color:var(--c);color:var(--c);background:var(--c2)}.ffc-chip.on{opacity:.45;pointer-events:none}' +
    '.ffc-list{display:flex;flex-direction:column;gap:8px}' +
    '.ffc-item{display:flex;align-items:center;gap:10px;padding:12px 14px;border:1px solid #dfe4ef;border-radius:14px;background:#fff;text-decoration:none;color:inherit}' +
    '.ffc-item:hover{border-color:var(--c);box-shadow:0 2px 10px rgba(18,49,139,.12)}' +
    '.ffc-it{flex:1;min-width:0}.ffc-nm{display:block;font-size:19px;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#111}' +
    '.ffc-sub{display:block;font-size:12px;color:#7b8396;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}' +
    '.ffc-role{display:inline-block;font-size:11px;font-weight:700;color:var(--c);background:var(--c2);border-radius:6px;padding:1px 6px;margin-right:5px}' +
    '.ffc-ar{flex:none;color:#9aa3b8}' +
    '.ffc-dots{display:inline-flex;gap:4px;padding:4px 0}.ffc-dots i{width:6px;height:6px;border-radius:50%;background:#9aa3b8;animation:ffcd 1s infinite}.ffc-dots i:nth-child(2){animation-delay:.15s}.ffc-dots i:nth-child(3){animation-delay:.3s}' +
    '@keyframes ffcd{0%,60%,100%{opacity:.3}30%{opacity:1}}' +
    '.ffc-foot{padding:8px 14px 11px}' +
    '.ffc-form{display:flex;align-items:center;gap:8px;background:#f1f3f8;border-radius:999px;padding:5px 5px 5px 16px}' +
    '.ffc-form input{flex:1;min-width:0;border:0;background:none;outline:0;font:inherit;font-size:16px;padding:7px 0;color:#1f2430}' +
    '.ffc-send{flex:none;width:36px;height:36px;border-radius:50%;border:0;background:var(--c);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}' +
    '.ffc-send:disabled{opacity:.35;cursor:default}' +
    '.ffc-note{font-size:11px;color:#8a92a5;text-align:center;margin-top:7px}' +
    '@media(max-width:600px){.ffc{right:14px}.ffc-btn{height:60px;padding:0 18px 0 10px}.ffc-bi{width:38px;height:38px}.ffc-bt b{font-size:16px}.ffc-panel{position:fixed;left:0;right:0;bottom:0;width:auto;height:min(82vh,680px);border-radius:20px 20px 0 0;border:0}.ffc-tip{display:none}}' +
    '@media print{.ffc{display:none}}';

  var ICO_BUBBLE = '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16h-1A2.5 2.5 0 0 1 4 13.5v-8Z" fill="#fff"/><text x="12" y="12.6" text-anchor="middle" font-size="7.2" font-weight="800" fill="#12318B" font-family="Segoe UI,Arial,sans-serif">Aa</text></svg>';
  var ICO_BUBBLE_N = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16h-1A2.5 2.5 0 0 1 4 13.5v-8Z" fill="#12318B"/><text x="12" y="12.6" text-anchor="middle" font-size="7.2" font-weight="800" fill="#fff" font-family="Segoe UI,Arial,sans-serif">Aa</text></svg>';
  var ICO_BUBBLE_S =ICO_BUBBLE.replace('width="28" height="28"', 'width="20" height="20"');
  var ICO_X = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  var ICO_RESET = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12a8 8 0 1 0 2.6-5.9L4 8.5"/><path d="M4 4v4.5h4.5"/></svg>';
  var ICO_SEND = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg>';
  var ICO_AR = '<svg class="ffc-ar" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';

  function build() {
    var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    root = document.createElement('div'); root.className = 'ffc';
    root.innerHTML =
      '<div class="ffc-panel" role="dialog" aria-label="폰트 추천 챗봇">' +
        '<div class="ffc-head"><span class="ffc-ico">' + ICO_BUBBLE_S + '</span>' +
        '<div class="ffc-ht"><b>AI 추천폰트</b><span>질문 3개면 딱 맞는 무료 폰트를 골라 드려요</span></div>' +
        '<button class="ffc-hb" type="button" data-a="reset" title="처음부터" aria-label="처음부터">' + ICO_RESET + '</button>' +
        '<button class="ffc-hb" type="button" data-a="close" aria-label="닫기">' + ICO_X + '</button></div>' +
        '<div class="ffc-body" aria-live="polite"></div>' +
        '<div class="ffc-foot"><form class="ffc-form"><input type="text" maxlength="80" placeholder="예: 브이로그 감성 자막 폰트" autocomplete="off" aria-label="메시지">' +
        '<button class="ffc-send" type="submit" aria-label="보내기" disabled>' + ICO_SEND + '</button></form>' +
        '<div class="ffc-note">추천은 참고용이에요. 사용 범위는 상세 페이지의 라이선스에서 확인해 주세요.</div></div></div>' +
      '<button class="ffc-btn" type="button" aria-label="AI 추천폰트 챗봇 열기"><span class="ffc-bi">' + ICO_BUBBLE_N + '</span>' +
        '<span class="ffc-bt"><small>폰트 고르기 어려울 땐</small><b>AI 추천폰트</b></span></button>';
    document.body.appendChild(root);
    panel = root.querySelector('.ffc-panel'); body = root.querySelector('.ffc-body');
    input = root.querySelector('input'); launcher = root.querySelector('.ffc-btn');
    var send = root.querySelector('.ffc-send');
    launcher.addEventListener('click', function () { setOpen(!S.open, true); });
    root.addEventListener('click', function (e) {
      var a = e.target.closest('[data-a]');
      if (a) { if (a.dataset.a === 'close') setOpen(false); else if (a.dataset.a === 'reset') restart(); return; }
      var c = e.target.closest('.ffc-chip');
      if (c) { c.parentNode.querySelectorAll('.ffc-chip').forEach(function (x) { x.classList.remove('on'); }); c.classList.add('on'); onChip(c.dataset.k, c.dataset.v, c.textContent); return; }
      if (e.target.closest('.ffc-tip')) setOpen(true, true);
      var it = e.target.closest('.ffc-item');
      if (it) { ga('chatbot_pick', {font_id: it.dataset.id}); save(); }
    });
    input.addEventListener('input', function () { send.disabled = !input.value.trim(); });
    root.querySelector('form').addEventListener('submit', function (e) {
      e.preventDefault();
      var t = input.value.trim(); if (!t) return;
      input.value = ''; send.disabled = true; onText(t);
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) setOpen(false); });
  }

  function setOpen(v, anim) {
    S.open = v; save();
    root.classList.toggle('anim', !!anim);
    root.classList.toggle('open', v);
    if (v) {
      ga('chatbot_open');
      boot().then(function () { if (!S.msgs.length) greet(); scrollEnd(true); if (anim && window.innerWidth > 600) input.focus(); });
      scrollEnd(true);
    }
  }
  function scrollEnd(now) {
    var go = function () { body.scrollTop = body.scrollHeight; };
    if (now) { body.style.scrollBehavior = 'auto'; go(); body.style.scrollBehavior = ''; } else go();
    setTimeout(go, 60);
  }

  // ── 말풍선 그리기 ──────────────────────────────────────────────
  function bubble(m) {   // m: {r:'b'|'u', t, chips:[[k,v,label]], list:[ids], roles:[..]}
    var h = '';
    if (m.t) h += '<div class="ffc-m ' + (m.r === 'u' ? 'ffc-u' : 'ffc-b') + '">' + esc(m.t).replace(/\n/g, '<br>') + '</div>';
    if (m.list && F) h += '<div class="ffc-list">' + m.list.map(function (id, i) { return itemHtml(id, m.roles && m.roles[i]); }).join('') + '</div>';
    if (m.chips && m.chips.length) h += '<div class="ffc-chips">' + m.chips.map(function (c) {
      return '<button type="button" class="ffc-chip" data-k="' + esc(c[0]) + '" data-v="' + esc(c[1]) + '">' + esc(c[2]) + '</button>';
    }).join('') + '</div>';
    return h;
  }
  function render() {
    body.innerHTML = S.msgs.map(bubble).join('');
    // 마지막 말풍선의 단추만 살려 둔다(지난 질문 단추는 눌린 뒤라 흐리게)
    var all = body.querySelectorAll('.ffc-chips');
    for (var i = 0; i < all.length - 1; i++) all[i].querySelectorAll('.ffc-chip').forEach(function (c) { c.classList.add('on'); });
  }
  function push(m, delay) {
    S.msgs.push(m); if (S.msgs.length > 60) S.msgs.splice(0, S.msgs.length - 60);
    save();
    if (m.r === 'u' || !delay) { body.insertAdjacentHTML('beforeend', bubble(m)); scrollEnd(); return Promise.resolve(); }
    var dots = document.createElement('div'); dots.className = 'ffc-m ffc-b'; dots.innerHTML = '<span class="ffc-dots"><i></i><i></i><i></i></span>';
    body.appendChild(dots); scrollEnd();
    return new Promise(function (ok) {
      setTimeout(function () { dots.remove(); body.insertAdjacentHTML('beforeend', bubble(m)); scrollEnd(); ok(); }, delay);
    });
  }
  function say(t, extra, delay) { var m = {r: 'b', t: t}; for (var k in (extra || {})) m[k] = extra[k]; return push(m, delay == null ? 380 : delay); }

  // ── 글꼴(리스트 이름을 그 폰트로) ─────────────────────────────
  var faces = {}, links = {};
  function nearest(ws, want) { ws = ws && ws.length ? ws : [400]; return ws.slice().sort(function (a, b) { return Math.abs(a - want) - Math.abs(b - want) || b - a; })[0]; }
  function nameStyle(id) {
    var f = F[id];
    if (f.css) {
      if (!links[f.css]) { var l = document.createElement('link'); l.rel = 'stylesheet'; l.href = f.css; document.head.appendChild(l); links[f.css] = 1; }
      return "font-family:'" + f.cf + "',sans-serif;font-weight:600";
    }
    var w = nearest(f.ws, 600), fam = 'ffc' + id + 'w' + w;
    if (!faces[fam]) {
      try {
        var ff = new FontFace(fam, 'url(/api/fonts/' + id + '/file/' + w + '.p.woff2) format("woff2")', {weight: String(w)});
        faces[fam] = ff.load().then(function (x) { document.fonts.add(x); }).catch(function () {});
      } catch (e) { faces[fam] = 1; }
    }
    return "font-family:'" + fam + "',sans-serif;font-weight:" + w;
  }
  function itemHtml(id, role) {
    var f = F[id]; if (!f) return '';
    return '<a class="ffc-item" href="/font/' + id + '" data-id="' + id + '"><span class="ffc-it">' +
      '<span class="ffc-nm" style="' + nameStyle(id) + '">' + esc(f.n) + '</span>' +
      '<span class="ffc-sub">' + (role ? '<span class="ffc-role">' + esc(role) + '</span>' : '') + esc(f.m) + ' · ' + esc(f.g) + ' · 굵기 ' + f.nw + '종</span></span>' + ICO_AR + '</a>';
  }

  // ── 데이터 ─────────────────────────────────────────────────────
  function boot() {
    if (D) { if (!S._rendered) { S._rendered = 1; render(); } return Promise.resolve(); }
    if (!loading) loading = fetch(DATA_URL).then(function (r) { return r.json(); }).then(function (d) { D = d; F = d.fonts; render(); }).catch(function () { loading = null; });
    return loading;
  }

  // 뽑기 규칙 — font-vending.html 의 poolFor·wpick·drawPage 를 그대로 옮김
  function popv(id) { var r = F[id].pr; return r == null ? 0 : 1 / (1 + r / 30); }
  function poolFor(key, mode) {
    var rows = (D.combos[key] || []).map(function (r) { return {id: String(r[0]), s: r[1], t: r[2], a: r[3], fit: r[4], mood: r[5]}; });
    var rank = function (c) { return F[c.id].pr == null ? 1e9 : F[c.id].pr; };
    if (mode === 'hot') {
      var hot = rows.filter(function (c) { return rank(c) < 100; });
      if (hot.length < 6) hot = rows.filter(function (c) { return rank(c) < 1e9; }).sort(function (a, b) { return rank(a) - rank(b); }).slice(0, 6);
      if (hot.length) rows = hot;
    } else if (mode === 'hidden') {
      var gem = rows.filter(function (c) { return rank(c) >= 250; });
      if (gem.length < 3) gem = rows.slice().sort(function (a, b) { return rank(b) - rank(a); }).slice(0, 6);
      rows = gem;
    }
    var add = POP_ADD[mode];
    rows.forEach(function (c) { var p = popv(c.id); c.s += add[0] * p; c.t += add[1] * p; c.a += add[2] * p; });
    return rows;
  }
  function wpick(list, key, T) {
    var m = -Infinity; list.forEach(function (c) { m = Math.max(m, key(c)); });
    var ws = list.map(function (c) { return Math.exp((key(c) - m) / T); });
    var sum = ws.reduce(function (a, b) { return a + b; }, 0), r = Math.random() * sum;
    for (var i = 0; i < list.length; i++) { r -= ws[i]; if (r <= 0) return list[i]; }
    return list[list.length - 1];
  }
  function differ(a, b) { return F[a.id].m !== F[b.id].m && F[a.id].fam !== F[b.id].fam; }
  function apart(a, b) { return Math.abs(F[a.id].w - F[b.id].w) > 0.06 || Math.abs(F[a.id].d - F[b.id].d) > 0.08; }
  function drawPage(rows, seen) {
    var reset = false, pool = rows.filter(function (c) { return !seen[c.id]; });
    if (pool.length < 3 && rows.length >= 3) { for (var k in seen) delete seen[k]; pool = rows.slice(); reset = true; }
    var page = [];
    if (!pool.length) return {page: page, reset: reset};
    var safe = wpick(pool, function (c) { return c.s; }, TEMP[0]); page.push(safe);
    var cs = pool.filter(function (c) { return c !== safe && differ(c, safe); });
    if (!cs.length) cs = pool.filter(function (c) { return c !== safe; });
    if (cs.length) {
      var strong = wpick(cs, function (c) { return c.t; }, TEMP[1]); page.push(strong);
      cs = pool.filter(function (c) { return page.indexOf(c) < 0 && differ(c, safe) && differ(c, strong); });
      if (!cs.length) cs = pool.filter(function (c) { return page.indexOf(c) < 0; });
      if (cs.length) {
        var adj = safe.fit <= 0 ? 20 : 0;
        var good = cs.filter(function (c) { return c.fit >= 0.75 * safe.fit - adj && c.mood >= 0.8 * safe.mood; });
        if (!good.length) good = cs;
        var groups = page.map(function (p) { return F[p.id].g; }), shapes = page.map(function (p) { return F[p.id].sh; });
        var wide = cs.filter(function (c) { return c.fit >= 0.7 * safe.fit - adj && c.mood >= 0.7 * safe.mood; });
        var steps = [wide.filter(function (c) { return groups.indexOf(F[c.id].g) < 0; }),
          good.filter(function (c) { return shapes.indexOf(F[c.id].sh) < 0 && apart(c, safe) && apart(c, strong); }),
          good.filter(function (c) { return apart(c, safe) && apart(c, strong); }), good];
        var step = steps.filter(function (s) { return s.length; })[0];
        page.push(wpick(step, function (c) { return c.a; }, TEMP[2]));
      }
    }
    page.forEach(function (c) { seen[c.id] = 1; });
    return {page: page, reset: reset};
  }

  // ── 대화 흐름 ──────────────────────────────────────────────────
  var Q = [
    ['use', '어디에 쓰실 건가요?', USES],
    ['mood', '보는 사람이 어떤 반응이면 좋겠어요?', MOODS],
    ['pop', '마지막이에요! 인기 있는 폰트가 좋아요, 아니면 남들이 잘 안 쓰는 숨은 보석이 좋아요?', MODES]];
  function chipsOf(k) { var q = Q.filter(function (x) { return x[0] === k; })[0]; return q[2].map(function (o) { return [k, o[0], o[1]]; }); }
  function labelOf(list, v) { return (list.filter(function (x) { return x[0] === v; })[0] || [v, v])[1]; }

  function greet() {
    say('안녕하세요! 폰트픽 폰트 추천이에요 👋\n질문 3개에 답하면 딱 맞는 무료 폰트를 골라 드려요. 바로 말로 물어보셔도 돼요.', {
      chips: [['go', 'start', '질문 3개로 추천받기']].concat(EXAMPLES.slice(0, 4).map(function (t) { return ['ex', t, t]; }))}, 200);
  }
  function restart() {
    S.msgs = []; S.sel = {}; S.seen = {}; S.grp = null; S.wt = null; S.step = 0; save();
    body.innerHTML = ''; boot().then(greet);
  }
  function ask(k) {
    var q = Q.filter(function (x) { return x[0] === k; })[0];
    return say(q[1], {chips: chipsOf(k)});
  }
  function nextAsk(optionalPop) {
    if (!S.sel.use) return ask('use');
    if (!S.sel.mood) return ask('mood');
    if (!S.sel.pop && !optionalPop) return ask('pop');
    return result(false);
  }
  function onChip(k, v, label) {
    boot().then(function () {
      if (k === 'go') { push({r: 'u', t: label}); S.sel = {}; S.seen = {}; S.grp = null; S.wt = null; nextAsk(false); return; }
      if (k === 'ex') { onText(v, true); return; }
      if (k === 'more') { push({r: 'u', t: label}); result(true); return; }
      if (k === 'restart') { push({r: 'u', t: label}); S.sel = {}; S.seen = {}; S.grp = null; S.wt = null; nextAsk(false); return; }
      if (k === 'grp') { push({r: 'u', t: label}); S.grp = v === '-' ? null : v; S.seen = {}; result(false); return; }
      push({r: 'u', t: label}); S.sel[k] = v; S.seen = {}; save();
      nextAsk(false);
    });
  }

  function has(t, arr) { for (var i = 0; i < arr.length; i++) if (t.indexOf(arr[i]) >= 0) return true; return false; }
  function first(t, dict) {   // 글에서 가장 앞에 나온 말의 키
    var best = null, pos = 1e9;
    for (var k in dict) dict[k].forEach(function (w) { var i = t.indexOf(w); if (i >= 0 && i < pos) { pos = i; best = k; } });
    return best;
  }
  function findNames(t) {
    var out = [];
    Object.keys(F).forEach(function (id) {
      var n = F[id].n.toLowerCase().replace(/\s/g, ''), core = n.replace(/체$/, '');
      if (core.length >= 2 && t.indexOf(core) >= 0) out.push(id);
    });
    return out.sort(function (a, b) { return F[b].n.length - F[a].n.length; }).slice(0, 4);
  }

  function onText(raw, fromChip) {
    boot().then(function () {
      push({r: 'u', t: raw});
      var t = raw.toLowerCase().replace(/\s+/g, '');
      if (has(t, K_RESET)) { S.sel = {}; S.seen = {}; S.grp = null; S.wt = null; save(); say('좋아요, 처음부터 해 볼게요!', null, 250).then(function () { nextAsk(false); }); return; }
      var names = findNames(t);
      // “명조 말고 고딕” — ‘말고’ 앞은 싫다는 뜻이라, 뒤에서 찾은 게 있으면 뒤 말만 쓴다
      var tt = t.indexOf('말고') >= 0 ? t.slice(t.lastIndexOf('말고') + 2) : t;
      var use = first(tt, K_USE), mood = first(tt, K_MOOD), pop = first(tt, K_POP), grp = first(tt, K_GRP);
      var bold = has(t, K_BOLD), thin = has(t, K_THIN), more = has(t, K_MORE);
      if (names.length && !use && !mood) {
        say('찾았어요! 이 폰트를 말씀하신 걸까요?', {list: names}).then(function () {
          say('비슷한 느낌을 더 보고 싶으면 쓰임이나 느낌을 말씀해 주세요.', {chips: chipsOf('use').slice(0, 4)}, 300);
        });
        return;
      }
      var got = use || mood || pop || grp || bold || thin;
      if (!got && more && S.sel.use && S.sel.mood) { result(true); return; }
      if (!got && !more) {
        if (has(t, K_THANKS)) { say('도움이 됐다니 기뻐요 😊 더 찾으시면 언제든 말씀해 주세요!', {chips: [['restart', 'x', '처음부터 다시']]}); return; }
        say('말씀을 정확히 못 알아들었어요 😅\n이렇게 물어보시면 잘 찾아요.\n“브이로그 감성 자막”, “굵은 썸네일 제목”, “명조 말고 고딕”', {
          chips: [['go', 'start', '질문 3개로 추천받기']].concat(EXAMPLES.slice(0, 2).map(function (x) { return ['ex', x, x]; }))});
        return;
      }
      if (use) S.sel.use = use;
      if (mood) S.sel.mood = mood;
      if (pop) S.sel.pop = pop;
      if (grp) S.grp = grp;
      if (bold) S.wt = 'bold'; else if (thin) S.wt = 'thin';
      S.seen = {}; save();
      // 쓰임·느낌 중 빠진 게 있으면 그것만 묻는다(인기는 말이 없으면 ‘상관없어요’로)
      if (!S.sel.use || !S.sel.mood) { say('알겠어요!', null, 200).then(function () { nextAsk(true); }); return; }
      if (!S.sel.pop) S.sel.pop = 'any';
      result(false);
    });
  }

  function result(more) {
    var s = S.sel;
    if (!(s.use && s.mood)) { nextAsk(true); return; }
    var mode = s.pop || 'any';
    var rows = poolFor(s.use + '|' + s.mood, mode), note = '';
    if (S.grp) {
      var g = rows.filter(function (c) { return F[c.id].g === S.grp; });
      if (g.length >= 3) rows = g; else { rows = poolFor(s.use + '|' + s.mood, 'any').filter(function (c) { return F[c.id].g === S.grp; }); if (rows.length < 3) { note = '‘' + S.grp + '’ 계열은 이 조합에 많지 않아서 다른 계열도 함께 골랐어요.'; S.grp = null; rows = poolFor(s.use + '|' + s.mood, mode); } }
    }
    if (S.wt && rows.length > 6) {
      var ws = rows.map(function (c) { return F[c.id].w; }).sort(function (a, b) { return a - b; }), med = ws[Math.floor(ws.length / 2)];
      var wr = rows.filter(function (c) { return S.wt === 'bold' ? F[c.id].w >= med : F[c.id].w <= med; });
      if (wr.length >= 3) rows = wr;
    }
    var res = drawPage(rows, S.seen);
    save();
    if (!res.page.length) {
      say('이 조합에 맞는 폰트가 아직 없어요. 인기 조건을 ‘상관없어요’로 바꿔 볼까요?', {chips: [['pop', 'any', '상관없어요'], ['restart', 'x', '처음부터 다시']]});
      return;
    }
    var bits = [labelOf(USES, s.use), labelOf(MOODS, s.mood), labelOf(MODES, mode)];
    if (S.grp) bits.push(S.grp); if (S.wt) bits.push(S.wt === 'bold' ? '굵게' : '얇게');
    var head = (more ? (res.reset ? '이 조건의 폰트를 다 봤어서 처음부터 다시 섞었어요.\n' : '') : '') + (more ? '다른 폰트도 골라 봤어요!' : '‘' + bits.join(' · ') + '’ 조건으로 골라 봤어요.');
    if (note) head = note + '\n' + head;
    var roles = ['무난한 선택', '느낌 확실', '색다른 선택'];
    say(head, {list: res.page.map(function (c) { return c.id; }), roles: roles.slice(0, res.page.length)}, 520).then(function () {
      var chips = [['more', 'x', '다른 폰트 더 보기']];
      if (!S.grp) chips.push(['grp', '고딕', '고딕으로'], ['grp', '손글씨', '손글씨로'], ['grp', '명조', '명조로']);
      chips.push(['restart', 'x', '처음부터']);
      say('눌러서 상세 페이지를 보세요. 채팅창은 그대로 있어요.\n“더 귀엽게”, “좀 더 굵게”처럼 말로 바꿔 달라고 하셔도 돼요.', {chips: chips}, 350);
    });
  }

  // ── 시작 ───────────────────────────────────────────────────────
  // 11/24 사용자님 "하단 광고가 올라올 때 챗봇이 따라 올라가니 우측 하단에 고정" — 앵커 광고 높이만큼 올리던 장치(lift)를 뺐다.
  function init() {
    build();
    if (S.open) { root.classList.add('open'); boot().then(function () { if (!S.msgs.length) greet(); else render(); scrollEnd(true); }); }
  }
  function ready(fn) { if (document.body) fn(); else document.addEventListener('DOMContentLoaded', fn); }
  ready(init);
})();
