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
    ("about", "/about.html", "폰트픽 소개", None, None),
    ("notice", "/#notice", "공지사항", "noticeMenuLink", "mNoticeMenuLink"),
    ("faq", "/faq.html", "자주 묻는 질문", None, None),
    # gif 라우터가 inject_header(html, "gif")로 넘기는 키와 같아야 활성 표시가 붙는다.
    #
    # 2026-08: 템플릿 목록(/gif/templates) 대신 편집기(/gif)로 바로 보낸다.
    # 예전에는 "빈 편집기부터 만나면 뭘 만들 수 있는 곳인지 알기 어렵다"는 이유로
    # 목록을 거치게 했는데, 편집기에 텍스트·사진·영상 세 모드가 생기면서 전제가
    # 바뀌었다 — 이제 편집기 자체가 '무엇을 만들 수 있는지'를 보여준다.
    # 템플릿 목록은 편집기 안의 'GIF 템플릿 전체보기' 카드로 계속 갈 수 있다.
    ("gif", "/gif", "GIF 생성기", None, None),
]


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
        onclick = ' onclick="navFindFont(event)"' if key == "findfont" else ""
        if mobile and key == "notice":
            onclick = ' onclick="closeMobileNav()"'
        elif mobile and key == "findfont":
            onclick = ' onclick="navFindFont(event);closeMobileNav()"'
        lines.append(f'{indent}<a href="{href}"{id_attr}{cls}{onclick}>{label}</a>')
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
    """active: 'about' | 'notice' | 'faq' | 'gif' | '' (해당 없음, 예: 폰트 상세페이지)

    '폰트 찾기'(/find-font)는 메뉴에서 뺐지만 페이지와 라우트는 그대로다 —
    공지사항 본문과 검색 결과에서 계속 링크된다."""
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
{_search_script()}'''


def inject_header(html: str, active: str = "") -> str:
    """html 안의 <!--FFP_HEADER--> 마커를 실제 헤더로 치환.
    마커가 없으면(예전 캐시된 파일 등) 원본을 그대로 반환 — 안전망."""
    return html.replace("<!--FFP_HEADER-->", render_header(active))
