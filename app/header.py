"""공유 헤더 — 사이트 전체가 이 파일 하나로만 헤더를 만든다.

헤더를 고칠 일이 있으면 이 파일과 static/header.css 두 곳만 고치면
index.html / about.html / faq.html / font.html / find-font 전 페이지에
동시에, 완전히 동일하게 반영된다. 페이지마다 헤더 마크업을 복사해서
관리하던 예전 방식(각자 조금씩 어긋나던 근본 원인)을 없애기 위함.

각 페이지의 static/*.html 파일에는 헤더가 있던 자리에
<!--FFP_HEADER--> 마커만 남아있고, 요청이 들어올 때 이 모듈의
render_header()가 만든 실제 HTML로 서버가 치환해서 응답한다.
"""

# (내부 key, 링크, 표시 텍스트, 데스크톱용 id, 모바일용 id) — 순서가 곧 메뉴 노출 순서
# id는 index.html의 해시 라우팅(JS)이 #notice / find-font 뷰 전환 시
# 활성(active) 표시를 동적으로 토글하기 위해 특정 id를 필요로 해서 부여함.
# 다른 페이지(about/faq/font)에는 해당 JS가 없어 id가 있어도 그냥 무시됨 — 안전.
NAV_ITEMS = [
    ("about", "/about", "소개", None, None),
    ("notice", "/#notice", "공지사항", "noticeMenuLink", "mNoticeMenuLink"),
    ("faq", "/faq.html", "자주 묻는 질문", None, None),
    # '폰트 찾기'는 index.html 안의 뷰다. 홈에서는 해시 라우팅으로 화면만 바꾸고,
    # 다른 페이지에서는 평범한 링크로 /find-font 를 연다 (_nav_links 참고).
    ("findfont", "/find-font", "폰트 찾기", "findFontMenuLink", "mFindFontMenuLink"),
    # 매거진은 '폰트 조합 찾기' 바로 왼쪽에 둔다.
    ("magazine", "/magazine", "매거진", None, None),
    # 폰트 조합 찾기. 폰트 찾기 다음에 두는 이유 — 둘 다 '고르는' 일이라
    # 나란히 있어야 하나를 고르고 나서 다음으로 넘어가는 흐름이 읽힌다.
    ("fontpair", "/font-pair", "폰트 조합 찾기", None, None),
    # gif 라우터가 inject_header(html, "gif")로 넘기는 키와 같아야 활성 표시가 붙는다.
    #
    # 2026-08: 템플릿 목록(/gif/templates) 대신 편집기(/gif)로 바로 보낸다.
    # 예전에는 "빈 편집기부터 만나면 뭘 만들 수 있는 곳인지 알기 어렵다"는 이유로
    # 목록을 거치게 했는데, 편집기에 텍스트·사진·영상 세 모드가 생기면서 전제가
    # 바뀌었다 — 이제 편집기 자체가 '무엇을 만들 수 있는지'를 보여준다.
    # 템플릿 목록은 편집기 안의 'GIF 템플릿 전체보기' 카드로 계속 갈 수 있다.
    ("gif", "/gif", "GIF 생성기", None, None),
]

# 메뉴 클릭 핸들러.
#
# navFindFont / closeMobileNav 는 index.html 에만 정의돼 있다.
# font · about · faq · policy · privacy · use 6개 페이지에는 없어서, 그냥
# 호출하면 그 페이지들에서 오류가 나고 브라우저에 따라 링크 이동까지 막혀
# 죽은 메뉴가 된다 (공지사항 모바일 메뉴에 이미 있던 문제다).
# typeof 검사로 감싸 함수가 있을 때만 부른다 — 홈에서는 뷰 전환, 다른
# 페이지에서는 평범한 링크 이동으로 양쪽 모두 동작한다.
_JS_FIND = "if(typeof navFindFont==='function')navFindFont(event)"
_JS_CLOSE = "if(typeof closeMobileNav==='function')closeMobileNav()"


def _nav_links(active: str, indent: str, mobile: bool) -> str:
    lines = []
    for key, href, label, id_d, id_m in NAV_ITEMS:
        # 클래스는 여러 개가 붙을 수 있으므로 목록으로 모아 한 번에 쓴다.
        # 예전처럼 'active' 하나만 문자열로 박아두면 다른 표식을 붙일 때
        # class 속성이 두 개 생겨 뒤엣것이 무시된다.
        classes = []
        if key == active:
            classes.append("active")
        if key == "gif":
            # GIF 생성기는 메뉴에서 유일하게 '만드는' 기능이다.
            # 나머지 항목(소개·공지·FAQ)은 읽는 페이지라, 같은 무게로 두면 묻힌다.
            # 실제 강조는 header.css의 .nav-gif가 담당한다.
            classes.append("nav-gif")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        elid = id_m if mobile else id_d
        id_attr = f' id="{elid}"' if elid else ""
        # GIF 생성기와 조합 찾기는 새 창으로 연다. 둘 다 화면에서 뭔가를
        # 맞춰 가는 자리라, 보던 페이지를 덮으면 뒤로 가기로 돌아왔을 때
        # 맞춰 두었던 것이 사라진다.
        # rel은 보안·성능 때문에 함께 둔다 — 새 창이 window.opener로 원래 탭을
        # 건드리지 못하게 막고, 브라우저가 두 탭을 다른 프로세스로 띄우게 한다.
        target = (' target="_blank" rel="noopener noreferrer"'
                  if key in ("gif", "fontpair") else "")
        onclick = f' onclick="{_JS_FIND}"' if key == "findfont" else ""
        if mobile and key == "notice":
            onclick = f' onclick="{_JS_CLOSE}"'
        elif mobile and key == "findfont":
            onclick = f' onclick="{_JS_FIND};{_JS_CLOSE}"'
        lines.append(f'{indent}<a href="{href}"{id_attr}{cls}{target}{onclick}>{label}</a>')
    return "\n".join(lines)


# 구글 애널리틱스(GA4) + 구글 애즈 태그.
#
# 예전에는 index.html과 font.html에만 스니펫을 복사해 넣어서, /gif · /gif/templates ·
# /use/{slug} · /about · /faq · /wisefont 는 조회수가 통째로 안 잡혔다. 페이지를
# 새로 만들 때마다 사람이 기억해서 붙여야 하는 구조라 반드시 또 빠진다.
# 헤더와 같은 이유로 여기 한 곳에만 둔다 — 헤더가 들어가는 페이지는 자동으로 측정된다.
#
# 어드민(admin.html / admin-gif.html)에는 <!--FFP_HEADER--> 마커가 없어서
# 그대로 제외된다. 운영자 트래픽이 통계에 섞이지 않는 게 맞다.
GA_MEASUREMENT_ID = "G-WK73M3QQVP"   # 애널리틱스
ADS_CONVERSION_ID = "AW-18302402783"  # 구글 애즈


def _search_script() -> str:
    """헤더 검색창의 Enter 처리.

    입력창은 헤더가 만드는데 동작은 페이지마다 따로 붙이고 있었다. 그래서
    /use/{slug} · /wisefont/{slug} · /gif · /gif/templates 에서는 검색창이
    보이기만 하고 아무 반응이 없었다. 헤더가 만든 것은 헤더가 책임진다 —
    새 페이지를 만들 때마다 사람이 기억해서 붙여야 하는 구조는 반드시 또 빠진다.

    경로는 반드시 절대경로여야 한다. 예전 about/faq는 'index.html#search/'를
    썼는데, 그건 /about.html에서만 우연히 맞고 /use/thumbnail 같은 하위 경로에서는
    /use/index.html 로 풀려 깨진다.
    """
    return '''<script>
(function(){
  var el = document.getElementById('globalSearch');
  if(!el) return;
  el.addEventListener('keydown', function(e){
    if(e.key !== 'Enter') return;
    // 홈은 페이지 안에서 바로 걸러내는 자체 구현(applySearch)이 있다.
    // 그쪽이 있으면 넘긴다 — 여기서 또 이동시키면 화면이 두 번 움직인다.
    if(typeof window.applySearch === 'function') return;
    var q = (el.value || '').trim();
    if(!q) return;
    e.preventDefault();
    location.href = '/#search/' + encodeURIComponent(q);
  });
})();

/* 야간·주간 전환도 헤더가 책임진다.

   헤더가 onclick="toggleTheme()" 버튼을 내보내는데 함수는 페이지마다
   복사해 두고 있었다. 그래서 새로 만든 /font-pair 와 /use 에서는 눌러도
   아무 일이 없었다 — 검색창 Enter 가 겪은 것과 똑같은 일이 또 났다.

   이미 함수를 가진 페이지는 이 뒤에 자기 것을 다시 정의하므로 그쪽이
   이긴다. 하는 일이 같아서 어느 쪽이 이기든 결과는 같다. */
(function(){
  function icons(){
    var root = document.documentElement;
    var isDark = root.getAttribute('data-theme') === 'dark'
      || (!root.hasAttribute('data-theme')
          && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var moon = document.getElementById('mThemeIconMoon');
    var sun  = document.getElementById('mThemeIconSun');
    var lab  = document.getElementById('mThemeLabel');
    if(moon) moon.style.display = isDark ? 'none' : '';
    if(sun)  sun.style.display  = isDark ? '' : 'none';
    if(lab)  lab.textContent    = isDark ? '주간모드' : '야간모드';
  }
  window.ffpApplyThemeIcons = icons;
  window.toggleTheme = function(){
    var root = document.documentElement;
    var cur = root.getAttribute('data-theme')
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var next = cur === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try{ localStorage.setItem('ffp-theme', next); }catch(e){}
    icons();
  };
  /* 공유 헤더의 '폰트 찾기'가 부르는 함수. SPA가 아닌 페이지에서는 링크를
     그대로 따라가면 된다 — 없으면 onclick 에서 예외가 난다. */
  window.navFindFont = window.navFindFont || function(){};
  icons();
  if(window.matchMedia){
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    if(mq.addEventListener) mq.addEventListener('change', icons);
  }
})();
</script>
'''


def _analytics() -> str:
    return f'''<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={ADS_CONVERSION_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{ADS_CONVERSION_ID}');
  gtag('config', '{GA_MEASUREMENT_ID}');
</script>
'''


def render_header(active: str = "") -> str:
    """active: 'about' | 'notice' | 'faq' | 'findfont' | 'gif' | '' (해당 없음)

    '폰트 찾기'(/find-font)는 index.html 안의 뷰라 홈에서는 해시 라우팅으로
    전환되고, 다른 페이지에서는 평범한 링크 이동으로 열린다."""
    nav_desktop = _nav_links(active, "      ", mobile=False)
    nav_mobile = _nav_links(active, "    ", mobile=True)

    return f'''{_analytics()}<header class="header">
  <div class="header-inner">
    <a href="/" class="logo" id="ffpLogoLink" aria-label="폰트픽 홈으로"><img class="logo-mark" src="/favicon.svg" width="24" height="24" alt="" aria-hidden="true">폰트픽</a>
    <nav>
{nav_desktop}
    </nav>
    <div class="search-wrap" id="searchWrap">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="7"/><line x1="21" y1="21" x2="15.5" y2="15.5"/></svg>
      <input type="text" id="globalSearch" placeholder="폰트명 또는 분위기/용도로 추천" aria-label="폰트 검색 및 추천">
    </div>
    <div class="header-right">
      <button type="button" class="theme-toggle" onclick="toggleTheme()" aria-label="야간모드 전환">
        <svg class="ti-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="19" height="19" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></svg>
        <svg class="ti-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="19" height="19" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M19.07 4.93l-1.41 1.41M6.34 17.66l-1.41 1.41M19.07 19.07l-1.41-1.41M6.34 6.34 4.93 4.93"/></svg>
      </button>
      <a class="btn-subscribe" href="https://tdtd.io" target="_blank" rel="noopener noreferrer">타닥타닥 구독</a>
      <button type="button" class="hamburger-btn" onclick="var n=document.getElementById('mnav');n.hidden=!n.hidden;n.classList.toggle('open')" aria-label="메뉴 열기">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" width="22" height="22"><line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/></svg>
      </button>
    </div>
  </div>
  <nav class="mobile-nav" id="mnav" hidden>
{nav_mobile}
    <a href="https://tdtd.io" target="_blank" rel="noopener noreferrer">타닥타닥 구독</a>
    <button type="button" onclick="toggleTheme()" style="width:100%;text-align:left;border:none;background:transparent;font-family:inherit;font-size:inherit;color:inherit;padding:inherit;cursor:pointer">
      <svg class="ti-moon" id="mThemeIconMoon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="19" height="19" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></svg><svg class="ti-sun" id="mThemeIconSun" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="19" height="19" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M19.07 4.93l-1.41 1.41M6.34 17.66l-1.41 1.41M19.07 19.07l-1.41-1.41M6.34 6.34 4.93 4.93"/></svg> <span id="mThemeLabel">야간모드</span>
    </button>
  </nav>
</header>
{_pair_band(active)}{_search_script()}'''


def inject_header(html: str, active: str = "") -> str:
    """html 안의 <!--FFP_HEADER--> 마커를 실제 헤더로 치환.
    마커가 없으면(예전 캐시된 파일 등) 원본을 그대로 반환 — 안전망."""
    return html.replace("<!--FFP_HEADER-->", render_header(active))


# ── 폰트 조합 찾기 띠 ────────────────────────────────────────────
# 헤더 바로 아래에 붙어 따라다니다가, 닫으면 사라진다(브라우저가 기억한다).
#
# 예전에는 index.html 안에만 있었다. 용도 페이지에도 달면서 이리로 올렸다 —
# 복사해 두면 페이지가 늘 때마다 또 복사해야 하고, 그러다 한쪽만 고쳐진다.
# 검색창 Enter·야간모드가 이미 그렇게 어긋났었다(_search_script 주석 참고).
#
# 모양은 static/header.css 의 .pair-band* 가 맡는다.
def _pair_band(active: str) -> str:
    """헤더 바로 아래에 붙는 조합 찾기 띠.

    첫 줄의 스크립트가 띠 마크업보다 **먼저** 지나가는 것이 중요하다.
    닫아 둔 사람에게 그려 놓고 감추면 한 번 번쩍인다. CSS 가 이미
    html.pairband-off 를 알고 있으므로, 클래스를 먼저 붙여 두면 아래 요소는
    처음부터 감춰진 채로 만들어진다.
    """
    if active == "fontpair":
        return ""          # 지금 보고 있는 페이지를 광고할 이유가 없다
    return '''<script>
(function(){try{if(localStorage.getItem('ffp-pairband')==='off')
document.documentElement.classList.add('pairband-off');}catch(e){}})();
</script>
<!-- ── 폰트 조합 찾기 띠 ──
     헤더 바로 아래에 붙어 따라다니다가, 닫으면 사라진다(브라우저가 기억).
     화면을 덮는 팝업으로 두지 않은 이유: 홈은 폰트를 보러 오는 자리다.

     세 뷰(갤러리·공지·폰트찾기) 바깥에 둔다 — 뷰를 옮겨도 계속 붙어 있어야
     한다는 뜻이라, 어느 한 뷰 안에 넣으면 그 뷰를 벗어날 때 같이 사라진다. -->
<div class="pair-band" id="pairBand" role="region" aria-label="폰트 조합 찾기 안내">
  <div class="pair-band-in">
    <a href="/font-pair" target="_blank" rel="noopener noreferrer">
      <span class="pair-band-ico" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h3"/><path d="M14 20h7"/><path d="M6.9 15h6.9"/><path d="M10.2 6.3l5.8 13.7"/><path d="M5 20l6-16h2l7 16"/></svg></span>
      <span class="pair-band-txt">
        <span class="pair-band-t">폰트 조합 찾기</span>
        <span class="pair-band-d">타이틀 · 서브타이틀 · 본문에 어울리는 무료 폰트 세 가지</span>
      </span>
      <span class="pair-band-go"><b>조합 보기</b><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6l-6 6"/></svg></span>
    </a>
    <button type="button" class="pair-band-x" onclick="closePairBand()"
            title="닫기" aria-label="폰트 조합 찾기 안내 닫기">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6l-12 12"/><path d="M6 6l12 12"/></svg>
    </button>
  </div>
</div>
<script>
/* 띠는 헤더 아래에 고정돼 따라다닌다. 그런데 홈의 .tags-bar 와 .hub-rail 도
   같은 자리를 노리는 고정 요소라, 띠가 있는 동안에는 그 높이만큼 내려가야
   한다. 그 두 규칙이 calc(60px + var(--band-h)) 로 이 값을 더해 쓴다.
   띠가 없는 페이지에서는 아무도 안 읽으므로 값이 남아 있어도 무해하다. */
function bandHeight(){
  var b = document.getElementById('pairBand');
  if(!b || document.documentElement.classList.contains('pairband-off')) return 0;
  return Math.round(b.getBoundingClientRect().height);
}

function syncBandOffset(){
  document.documentElement.style.setProperty('--band-h', bandHeight() + 'px');
}

function closePairBand(){
  document.documentElement.classList.add('pairband-off');
  try{ localStorage.setItem('ffp-pairband', 'off'); }catch(e){}
  syncBandOffset();
}

syncBandOffset();

/* 띠 높이는 화면 폭 말고도 여러 이유로 바뀐다. 실제로 어긋났던 경우:
   Noto Sans KR 이 늦게 실리면서 글자 줄 높이가 커져 띠가 40px -> 45px 이 됐는데,
   resize 이벤트는 그때 울리지 않아 --band-h 가 40 에 머물렀다. 스크롤하면
   모양으로 찾기 바가 띠를 5px 파고들었다.

   그래서 '언제 바뀔지'를 헤아리지 않고 요소 크기를 직접 지켜본다. */
(function(){
  var band = document.getElementById('pairBand');
  if(band && window.ResizeObserver){
    new ResizeObserver(syncBandOffset).observe(band);
  } else {
    window.addEventListener('resize', syncBandOffset);   // 아주 옛 브라우저용
  }
  window.addEventListener('load', syncBandOffset);
  if(document.fonts && document.fonts.ready) document.fonts.ready.then(syncBandOffset);
})();
</script>
'''


# ── 404 페이지 ──────────────────────────────────────────────────
# 없는 폰트·허브를 홈으로 302 하던 자리를 대신한다.
#
# 예전 주석은 홈 리다이렉트가 soft 404 를 막는다고 적혀 있었는데 사실은
# 반대다. 검색엔진은 "없는 주소가 200 이나 3xx 로 응답하고 내용이 엉뚱함"을
# soft 404 로 판정한다. 홈으로 보내는 것이 바로 그 형태였고, 실제로
# Search Console 에 /use/* 가 soft 404 로 잡혔다. 상태 코드 404 를 제대로
# 주는 것이 색인에도, 사람이 보기에도 낫다.
from pathlib import Path as _Path

from fastapi.responses import HTMLResponse as _HTMLResponse

_NOT_FOUND_PATH = _Path(__file__).resolve().parent.parent / "static" / "404.html"


def not_found_page() -> _HTMLResponse:
    """브랜드 404 페이지를 상태 코드 404 와 함께 돌려준다."""
    try:
        html = inject_header(_NOT_FOUND_PATH.read_text(encoding="utf-8"), "")
    except Exception:
        # 파일이 없어도 404 자체는 정확히 내보낸다 — 상태 코드가 본질이다.
        html = "<!DOCTYPE html><html lang=ko><meta charset=utf-8>"                "<title>404 — 폰트픽</title><p>페이지를 찾을 수 없습니다. "                "<a href=\"/\">폰트픽 홈</a></p>"
    return _HTMLResponse(html, status_code=404)
