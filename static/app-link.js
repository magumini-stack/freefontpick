/* 앱 배너 링크를 기기에 맞는 스토어로 바꾼다.
 *
 * 왜 필요한가
 * ----------
 * 예전 배너는 앱 세 개를 묶어 wisefont.co.kr/apps.html 로 보냈다. 모바일에서
 * 이게 손해였다. 세 앱 중 **구글 플레이에 올라간 것은 글씨사진관 하나뿐**이라
 * (움짤공방·폰트박스는 앱스토어만), 안드로이드 이용자는 눌러도 받을 수 없는
 * 앱을 두 개 보게 된다. 그래서 모바일에 보이는 배너는 글씨사진관 하나로
 * 좁히고, 링크도 그 기기에서 실제로 설치할 수 있는 곳으로 보낸다.
 *
 * 스토어 주소는 왜 여기 있나
 * ------------------------
 * 배너가 세 군데(홈·상세 사이드바·디자이너 모달)에 있어서, 마크업에 주소를
 * 세 번 적으면 앱이 늘거나 주소가 바뀔 때 반드시 한 곳이 남는다. 마크업에는
 * data-applink 만 적고 주소는 이 파일에만 둔다.
 *
 * 자바스크립트가 죽으면
 * -------------------
 * 마크업의 href 가 그대로 쓰인다. 그래서 기본 href 를 **플레이스토어**로
 * 둔다 — 웹 목록 페이지라 어느 브라우저에서든 열리고, 데스크톱에서는 '기기로
 * 설치'까지 된다. 아이폰에서 이 경우에 걸리면 안드로이드 목록을 보게 되는데,
 * 이 사이트는 어차피 JS 없이는 갤러리가 그려지지 않으므로 실질적인 경로가
 * 아니다.
 *
 * 애드센스
 * -------
 * 이 파일은 링크 주소만 바꾼다. 배너를 띄우거나 옮기거나 고정하지 않는다 —
 * 화면을 덮는 홍보물은 구글 모바일 인터스티셜 페널티 대상이고, 하단 고정은
 * 자동광고 앵커 광고와 자리를 다툰다(static/index.html 의 .fbx 주석 참고).
 * 배너는 지금처럼 본문 흐름 안에 그대로 둔다.
 */
(function () {
  'use strict';

  var STORES = {
    // 글씨사진관 — 사진에 글자를 얹는 앱. 셋 중 유일하게 양쪽 스토어에 있다.
    kphototext: {
      android: 'https://play.google.com/store/apps/details?id=com.wisefont.kphototext',
      ios: 'https://apps.apple.com/kr/app/id6443999511'
    }
  };

  function platform() {
    var ua = navigator.userAgent || '';
    // 아이패드는 최근 iPadOS 에서 맥 UA 를 쓴다. 터치가 되는 맥으로 가려낸다.
    if (/iPhone|iPad|iPod/i.test(ua)) return 'ios';
    if (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) return 'ios';
    if (/Android/i.test(ua)) return 'android';
    return '';
  }

  function apply() {
    var os = platform();
    if (!os) return;                       // 데스크톱은 마크업의 기본값을 쓴다
    var links = document.querySelectorAll('[data-applink]');
    for (var i = 0; i < links.length; i++) {
      var s = STORES[links[i].getAttribute('data-applink')];
      if (s && s[os]) links[i].href = s[os];
    }
  }

  /* 상세페이지는 배너를 모바일에서 다른 자리로 옮긴다(#appPromoSlot). 옮기는
     것은 같은 요소라 href 는 유지되지만, 나중에 그려지는 배너가 생길 수 있어
     DOM 이 준비된 뒤 한 번 더 훑는다. */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply);
  } else {
    apply();
  }
})();
