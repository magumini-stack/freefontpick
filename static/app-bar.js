/* 홈 하단에서 올라오는 앱 배너.
 *
 * 어떻게 도나
 * ----------
 * 화면 한 장 반쯤 내려가면 아래에서 올라오고, X 를 누르면 그 세션 동안 다시
 * 뜨지 않는다. 처음부터 떠 있지 않은 이유는, 들어오자마자 화면을 가리는
 * 홍보물이 구글의 모바일 인터스티셜 페널티 대상이기 때문이다. 스크롤 뒤에
 * 뜨는 얇은 띠는 그 대상이 아니다 — 구글이 예로 드는 '적당한 크기에 닫기
 * 쉬운 앱 설치 배너'가 이 모양이다.
 *
 * 광고에 자리를 양보한다
 * --------------------
 * 이 자리는 원래 자동광고의 앵커 광고가 쓰는 자리다. 예전에 하단 고정
 * 배너를 뒀다가 둘이 겹쳐서 본문 안으로 내렸던 적이 있다
 * (static/index.html 의 .fbx 주석). 광고를 가리는 것은 정책 위반이라,
 * 아래쪽에 고정된 광고가 보이면 이 배너는 스스로 물러난다. 광고가 사라지면
 * 다시 올라온다.
 *
 * 승인 대기 중인 지금은 광고 유닛이 하나도 없어서 늘 뜨지만, 승인 뒤
 * 앵커 광고가 붙으면 코드를 고치지 않아도 알아서 비켜난다.
 */
(function () {
  'use strict';

  var KEY = 'ffp-appbar-closed';
  var SHOW_AFTER = 1.4;          // 화면 몇 장을 내려가면 뜨는가
  var bar, link, closeBtn;
  var dismissed = false;

  function isDismissed() {
    try { return sessionStorage.getItem(KEY) === '1'; } catch (e) { return false; }
  }

  /* 화면 아래에 고정된 광고가 있는가. 자동광고는 삽입되는 마크업이 그때그때
     달라서 클래스 하나로 잡을 수 없다. '아래에 붙어 있고 화면에 보이는
     광고 요소'라는 성질로 찾는다. */
  function anchorAdShowing() {
    var sel = 'ins.adsbygoogle, .google-auto-placed, iframe[id*="google_ads"],' +
              ' #floatingAd:not(.hidden)';
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) {
      var e = els[i];
      var cs = window.getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      var r = e.getBoundingClientRect();
      if (r.height < 20) continue;
      // 스스로 고정이거나, 고정된 부모 안에 들어 있거나
      var fixed = cs.position === 'fixed';
      for (var p = e.parentElement; !fixed && p && p !== document.body; p = p.parentElement) {
        if (window.getComputedStyle(p).position === 'fixed') fixed = true;
      }
      if (fixed && r.bottom > window.innerHeight - 60) return true;
    }
    return false;
  }

  function update() {
    if (!bar || dismissed) return;
    var down = window.scrollY > window.innerHeight * SHOW_AFTER;
    bar.classList.toggle('show', down && !anchorAdShowing());
  }

  function close() {
    dismissed = true;
    bar.classList.remove('show');
    try { sessionStorage.setItem(KEY, '1'); } catch (e) {}
  }

  function init() {
    bar = document.getElementById('appBar');
    if (!bar) return;
    closeBtn = document.getElementById('appBarX');
    if (closeBtn) closeBtn.addEventListener('click', close);
    /* 배너를 눌러 스토어로 가면 돌아왔을 때 또 뜰 이유가 없다. */
    link = bar.querySelector('a');
    if (link) link.addEventListener('click', close);
    if (isDismissed()) { dismissed = true; return; }
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    /* 자동광고는 페이지가 뜬 뒤 늦게 들어온다. 잠깐 지켜본다. */
    var n = 0;
    var t = setInterval(function () { update(); if (++n > 20) clearInterval(t); }, 1000);
    update();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
