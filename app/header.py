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
    ("findfont", "/find-font", "폰트 찾기", "submitMenuLink", "mSubmitMenuLink"),
]


def _nav_links(active: str, indent: str, mobile: bool) -> str:
    lines = []
    for key, href, label, id_d, id_m in NAV_ITEMS:
        cls = ' class="active"' if key == active else ""
        elid = id_m if mobile else id_d
        id_attr = f' id="{elid}"' if elid else ""
        onclick = ' onclick="navFindFont(event)"' if key == "findfont" else ""
        if mobile and key == "notice":
            onclick = ' onclick="closeMobileNav()"'
        elif mobile and key == "findfont":
            onclick = ' onclick="navFindFont(event);closeMobileNav()"'
        lines.append(f'{indent}<a href="{href}"{id_attr}{cls}{onclick}>{label}</a>')
    return "\n".join(lines)


def render_header(active: str = "") -> str:
    """active: 'about' | 'notice' | 'faq' | 'findfont' | '' (해당 없음, 예: 폰트 상세페이지)"""
    nav_desktop = _nav_links(active, "      ", mobile=False)
    nav_mobile = _nav_links(active, "    ", mobile=True)

    return f'''<header class="header">
  <div class="header-inner">
    <a href="/" class="logo" id="ffpLogoLink" aria-label="폰트픽 홈으로">폰트픽<span class="logo-dot"></span></a>
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
</header>'''


def inject_header(html: str, active: str = "") -> str:
    """html 안의 <!--FFP_HEADER--> 마커를 실제 헤더로 치환.
    마커가 없으면(예전 캐시된 파일 등) 원본을 그대로 반환 — 안전망."""
    return html.replace("<!--FFP_HEADER-->", render_header(active))
