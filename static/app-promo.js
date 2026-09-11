/* 앱 팝업 — '글자로 노는 앱' 광고를 한 장 띄우고, 닫으면 하던 일을 잇는다.
 *
 * 쓰는 곳
 * -------
 *   상세페이지  무료 다운로드를 누르면 → 닫으면 다운로드      (static/font.html)
 *   GIF 생성기  들어올 때 / 저장을 누르면 → 닫으면 저장        (static/gif.html)
 *
 *     FFPAppPromo.show({ next: '닫고 다운로드하기', onClose: fn })
 *
 * 옷은 홈 갤러리 첫 칸의 앱 카드(.apps-card)와 같다 — 와이즈폰트 앱 페이지의
 * 본(bone) 바탕 · 먹색 · 빨강 하나. 문구도 그 페이지에서 가져왔다.
 *
 * 닫는 길
 * ------
 * 아래 버튼, ×, 바깥 클릭, Esc — 어느 쪽이든 onClose 를 딱 한 번 부른다.
 *
 * onClose 는 닫는 입력 **그 안에서** 동기로 부른다. 새 창 열기(window.open)는
 * 사람이 누른 그 순간에만 허용되고, 타이머나 await 뒤로 넘기면 팝업 차단에
 * 걸린다. 단 Esc 는 표준상 '사람이 누른 입력'이 아니라서 Esc 로 닫으면 새 창이
 * 막힌다. 새 창을 여는 쪽은 막혔을 때 같은 탭으로 넘어가는 대비를 둬야 한다
 * (font.html 의 다운로드 버튼이 그렇게 한다).
 *
 * '앱 보러 가기'는 새 탭으로 앱 소개를 열고 팝업은 그대로 둔다. 같은 클릭으로
 * 다운로드 창까지 열면 두 번째 창이 팝업 차단에 걸린다. 돌아와서 닫으면 된다.
 *
 * 아이콘(/apps/*.webp)을 바꾸면 파일 이름도 바꿀 것. 카페24 앞단이 이미지를
 * 오래 붙들고 있어서 같은 이름으로 덮으면 옛 그림이 계속 나간다.
 *
 * 이름은 전부 apx- 로 시작한다
 * ---------------------------
 * 이 CSS 는 팝업을 처음 띄울 때 페이지에 주입되어 그대로 남는다. 그래서 이름이
 * 페이지 것과 겹치면 페이지 요소까지 옷이 바뀐다. 처음에 fp- 로 지었다가
 * 상세페이지의 폰트 조합 시트가 이미 .fp-x(닫기 버튼)를 쓰고 있는 것을 시험
 * 중에 발견했다 — 다운로드를 한 번 누르면 그 버튼이 엉뚱한 자리로 튈 뻔했다.
 * 새 이름을 붙일 때는 저장소에서 먼저 찾아볼 것.
 */
(function (global) {
  'use strict';

  var APPS_URL = 'https://www.wisefont.co.kr/apps.html';
  var APPS = [
    ['geulssi', '글씨사진관', '멋진 사진에 감성 글 쓰기'],
    ['umzzal',  '움짤공방',  '문구만 넣으면 움직이는 글자'],
    ['fontbox', '폰트박스',  '한글 폰트 208종을 아이폰 글꼴로']
  ];

  var CSS = [
    '.apx{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;',
    '  padding:20px;background:rgba(13,13,13,.55);opacity:0;transition:opacity .18s ease;',
    '  --apx-bg:#f0efeb;--apx-ink:#0d0d0d;--apx-sub:#6f6a64;--apx-red:#ff3511;--apx-line:#dbd6ce;--apx-card:#fff}',
    /* 어두운 화면에서는 바탕만 가라앉히고 빨강은 한 단계 밝힌다 — 홈 앱 카드와 같은 값 */
    ':root[data-theme="dark"] .apx{--apx-bg:#1d1c1a;--apx-ink:#f0efeb;--apx-sub:#a39d95;',
    '  --apx-red:#ff5a3c;--apx-line:rgba(255,255,255,.1);--apx-card:#262522}',
    '@media(prefers-color-scheme:dark){:root:not([data-theme="light"]):not([data-theme="dark"]) .apx{',
    '  --apx-bg:#1d1c1a;--apx-ink:#f0efeb;--apx-sub:#a39d95;--apx-red:#ff5a3c;--apx-line:rgba(255,255,255,.1);--apx-card:#262522}}',
    '.apx.in{opacity:1}',
    '.apx-box{position:relative;width:100%;max-width:380px;max-height:calc(100vh - 40px);overflow:auto;',
    '  box-sizing:border-box;padding:26px 24px 20px;border-radius:18px;background:var(--apx-bg);color:var(--apx-ink);',
    '  box-shadow:0 24px 60px rgba(0,0,0,.28);transform:translateY(10px) scale(.98);transition:transform .2s ease;',
    '  font-family:inherit;text-align:left;outline:none}',
    '.apx.in .apx-box{transform:none}',
    '.apx-x{position:absolute;top:10px;right:10px;width:36px;height:36px;padding:0;border:none;border-radius:50%;',
    '  background:none;color:var(--apx-sub);font:inherit;font-size:22px;line-height:1;cursor:pointer}',
    '.apx-x:hover{background:rgba(127,127,127,.14);color:var(--apx-ink)}',
    '.apx-kick{display:flex;align-items:center;gap:8px;font-size:10.5px;font-weight:700;letter-spacing:.14em;color:var(--apx-sub)}',
    '.apx-kick::before{content:"";width:16px;height:1.5px;background:var(--apx-red)}',
    '.apx-title{margin:12px 0 0;font-size:24px;font-weight:800;letter-spacing:-.04em;line-height:1.28;word-break:keep-all}',
    '.apx-title em{font-style:normal;color:var(--apx-red)}',
    '.apx-lead{margin:8px 0 0;font-size:13px;line-height:1.5;color:var(--apx-sub);word-break:keep-all}',
    '.apx-apps{display:grid;gap:8px;margin:18px 0 0;padding:0;list-style:none}',
    '.apx-apps li{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:12px;background:var(--apx-card)}',
    '.apx-apps img{flex:0 0 auto;display:block;width:42px;height:42px;border-radius:10px;',
    '  border:1px solid var(--apx-line);background:#fff}',
    '.apx-apps b{display:block;font-size:14px;font-weight:800;letter-spacing:-.02em}',
    '.apx-apps span{display:block;margin-top:2px;font-size:12px;color:var(--apx-sub);word-break:keep-all}',
    '.apx-cta{display:flex;align-items:center;justify-content:center;gap:6px;height:46px;margin-top:18px;',
    '  border-radius:999px;background:var(--apx-ink);color:var(--apx-bg);font-size:14.5px;font-weight:800;text-decoration:none}',
    /* 닫는 버튼을 작게 숨기지 않는다 — 닫기 어렵게 만든 광고는 사람도 구글도 싫어한다 */
    '.apx-next{display:block;width:100%;height:42px;margin-top:8px;border:1px solid var(--apx-line);border-radius:999px;',
    '  background:none;color:var(--apx-ink);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer}',
    '.apx-next:hover{background:rgba(127,127,127,.08)}',
    '.apx-x:focus-visible,.apx-cta:focus-visible,.apx-next:focus-visible{outline:2px solid var(--apx-red);outline-offset:2px}',
    '@media(prefers-reduced-motion:reduce){.apx,.apx-box{transition:none}}'
  ].join('\n');

  var styled = false;
  var isOpen = false;

  function injectCSS() {
    if (styled) return;
    styled = true;
    var st = document.createElement('style');
    st.id = 'apxStyle';
    st.textContent = CSS;
    document.head.appendChild(st);
  }

  function build(nextLabel) {
    var root = document.createElement('div');
    root.className = 'apx';
    var apps = APPS.map(function (a) {
      return '<li><img src="/apps/' + a[0] + '.webp" alt="" width="42" height="42" decoding="async">' +
             '<div><b>' + a[1] + '</b><span>' + a[2] + '</span></div></li>';
    }).join('');
    root.innerHTML =
      '<div class="apx-box" role="dialog" aria-modal="true" aria-labelledby="apxTitle" tabindex="-1">' +
        '<button type="button" class="apx-x" aria-label="광고 닫기">&times;</button>' +
        '<div class="apx-kick">WISEFONT APPS</div>' +
        '<h2 class="apx-title" id="apxTitle">글자로 노는 앱,<br><em>지금 받으세요.</em></h2>' +
        '<p class="apx-lead">와이즈폰트가 직접 만든 앱 3종 · 모두 무료</p>' +
        '<ul class="apx-apps">' + apps + '</ul>' +
        '<a class="apx-cta" href="' + APPS_URL + '" target="_blank" rel="noopener">앱 보러 가기 →</a>' +
        '<button type="button" class="apx-next"></button>' +
      '</div>';
    root.querySelector('.apx-next').textContent = nextLabel;   // 부르는 쪽 문구 — 텍스트로만 넣는다
    return root;
  }

  function show(opts) {
    opts = opts || {};
    if (isOpen) return false;          // 두 번 눌러도 한 장만
    if (!document.body) return false;
    injectCSS();
    isOpen = true;

    var root = build(opts.next || '닫기');
    var box = root.querySelector('.apx-box');
    var prevFocus = document.activeElement;
    var html = document.documentElement;
    var prevOverflow = html.style.overflow;
    var done = false;

    function close() {
      if (done) return;
      done = true;
      isOpen = false;
      document.removeEventListener('keydown', onKey, true);
      html.style.overflow = prevOverflow;
      if (root.parentNode) root.parentNode.removeChild(root);
      try { if (prevFocus && prevFocus.focus) prevFocus.focus({ preventScroll: true }); } catch (e) {}
      /* 닫는 입력 안에서 동기로 부른다 — 위 머리말 '닫는 길' 참고 */
      if (typeof opts.onClose === 'function') opts.onClose();
    }

    function onKey(e) {
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key !== 'Tab') return;
      /* 포커스를 팝업 안에 가둔다 — 뒤의 페이지로 새면 화면 읽기 프로그램이 길을 잃는다 */
      var f = [].slice.call(box.querySelectorAll('button, a[href]'));
      if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === box)) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }

    root.querySelector('.apx-x').addEventListener('click', close);
    root.querySelector('.apx-next').addEventListener('click', close);
    root.addEventListener('click', function (e) { if (e.target === root) close(); });
    document.addEventListener('keydown', onKey, true);

    document.body.appendChild(root);
    html.style.overflow = 'hidden';
    /* 하려던 일을 잇는 버튼에 포커스 — 엔터를 치면 광고가 아니라 원래 하던 일로 간다 */
    try { root.querySelector('.apx-next').focus({ preventScroll: true }); } catch (e) {}
    requestAnimationFrame(function () { root.classList.add('in'); });
    return true;
  }

  global.FFPAppPromo = { show: show };
})(window);
