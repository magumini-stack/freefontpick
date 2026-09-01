/* 폰트 로딩 공용 모듈 — @font-face 등록과 font-family 스택 계산을 한 곳에서 한다.
 *
 * 왜 파일로 뺐나
 * -------------
 * 이 함수들은 원래 font.html 안 IIFE 지역 스코프에 있었다. 조합 페이지(/font-pair)가
 * 같은 일을 해야 하는데, 복사해 두면 반드시 갈라진다 — 헤더를 app/header.py 한 곳으로
 * 모은 것과 같은 이유다(그 파일 주석: "페이지마다 헤더 마크업을 복사해서 관리하던
 * 예전 방식"이 각자 조금씩 어긋나던 근본 원인).
 *
 * 규칙 하나만 기억하면 된다 — 굵기는 CSS로 흉내내지 않는다.
 * 그 굵기의 파일이 서버에 있으면 그 파일이 직접 그리게 하고, 없을 때만 브라우저
 * 합성에 맡긴다. 이유는 아래 weightFamily 주석에 있다.
 */
(function (global) {
  'use strict';

  /* 모든 @font-face 규칙을 담을 단일 <style>. 페이지당 하나면 된다. */
  var styleEl = null;
  function sheet() {
    if (!styleEl) {
      styleEl = document.createElement('style');
      document.head.appendChild(styleEl);
    }
    return styleEl;
  }
  function addFace(family, url, weightDesc) {
    sheet().appendChild(document.createTextNode(
      "@font-face{font-family:'" + family + "';src:url('" + url +
      "') format('woff2');font-display:swap;font-weight:" +
      (weightDesc || 'normal') + ";font-style:normal}"
    ));
  }
  function pad3(id) { return String(id).padStart(3, '0'); }

  /* 폰트 파일 주소. 파일의 판(file_version)을 ?v= 로 붙인다.

     이게 없으면 서버가 매번 재검증 헤더로 내리고, 브라우저는 파일 전체를
     다시 받는다 — 한글 폰트 평균 476KB × 화면에 보이는 수만큼, 방문할 때마다.
     v가 붙으면 1년 immutable로 내려가고, 어드민이 파일을 바꾸면 v가 달라져
     주소가 바뀌므로 교체도 그대로 반영된다.

     v를 모르면(옛 응답 등) 그냥 빼고 부른다 — 예전 방식으로 안전하게 떨어진다. */
  /* preview=1 은 '이 폰트를 미리보기로만 쓴다'는 뜻이다. 서버가 이름과 짧은
     견본 문구를 그릴 만큼만 담은 가벼운 서브셋을 내려준다(원본의 10~36%).
     본체 폰트(상세페이지 주인공, 디자인 모달)에는 붙이지 않는다 — 거기서는
     사용자가 아무 글자나 칠 수 있으므로 전문이 필요하다. */
  function fileUrl(id, weight, ver, preview) {
    var u = '/api/fonts/' + id + '/file';
    var q = [];
    if (weight) q.push('weight=' + weight);
    if (ver) q.push('v=' + ver);
    if (preview) q.push('preview=1');
    return q.length ? u + '?' + q.join('&') : u;
  }
  function verOf(f) { return f && f.file_version || 0; }

  /* stack에서 FFP-### 를 걷어낸 나머지(대체 폰트 목록). 우리가 앞에 붙일 family와
     중복되면 브라우저가 엉뚱한 걸 먼저 찾는다. */
  function baseStack(f) {
    return (f && f.stack || "sans-serif")
      .replace(/'?FFP-\d{3}'?\s*,?\s*/, '');
  }

  // ── 웹폰트(CDN) ────────────────────────────────────────────────
  var W9 = [[100, 'Thin'], [200, 'ExtraLight'], [300, 'Light'], [400, 'Regular'],
            [500, 'Medium'], [600, 'SemiBold'], [700, 'Bold'], [800, 'ExtraBold'],
            [900, 'Black']];

  var WEIGHT_LABEL_KO = { 100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular',
                          500: 'Medium', 600: 'SemiBold', 700: 'Bold', 800: 'ExtraBold',
                          900: 'Black' };

  /* 이름으로 알아보는 웹폰트 배포 폰트. key는 공백 제거 + 소문자.
     어드민에 웹폰트 설정이 생기기 전부터 있던 표라, DB 설정이 이것보다 우선한다
     (resolveWebfont 참조). */
  var WEBFONT_MAP = {
    'notosanscjkkr': { css: '', family: "'Noto Sans KR'", weights: W9 },
    '노토산스': { css: '', family: "'Noto Sans KR'", weights: W9 },
    '나눔고딕': { css: 'https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700;800&display=swap', family: "'Nanum Gothic'", weights: [[400, 'Regular'], [700, 'Bold'], [800, 'ExtraBold']] },
    '나눔명조': { css: 'https://fonts.googleapis.com/css2?family=Nanum+Myeongjo:wght@400;700;800&display=swap', family: "'Nanum Myeongjo'", weights: [[400, 'Regular'], [700, 'Bold'], [800, 'ExtraBold']] },
    '프리텐다드': { css: 'https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css', family: "'Pretendard Variable'", weights: W9 },
    '수트': { css: 'https://cdn.jsdelivr.net/gh/sun-typeface/SUIT@2/fonts/variable/woff2/SUIT-Variable.css', family: "'SUIT Variable'", weights: W9 },
    '마루부리': { css: 'https://hangeul.pstatic.net/hangeul_static/css/maru-buri.css', family: "'MaruBuri'", weights: [[300, 'Light'], [400, 'Regular'], [600, 'SemiBold'], [700, 'Bold']] },
    '나눔스퀘어': { css: 'https://cdn.jsdelivr.net/gh/moonspam/NanumSquare@master/nanumsquare.css', family: "'NanumSquare'", weights: [[300, 'Light'], [400, 'Regular'], [700, 'Bold'], [800, 'ExtraBold']] },
    /* 영문 구글폰트 (다중 굵기) */
    'montserrat': { css: 'https://fonts.googleapis.com/css2?family=Montserrat:wght@100..900&display=swap', family: "'Montserrat'", weights: W9 },
    'opensans': { css: 'https://fonts.googleapis.com/css2?family=Open+Sans:wght@300..800&display=swap', family: "'Open Sans'", weights: [[300, 'Light'], [400, 'Regular'], [500, 'Medium'], [600, 'SemiBold'], [700, 'Bold'], [800, 'ExtraBold']] },
    'roboto': { css: 'https://fonts.googleapis.com/css2?family=Roboto:wght@100;300;400;500;700;900&display=swap', family: "'Roboto'", weights: [[100, 'Thin'], [300, 'Light'], [400, 'Regular'], [500, 'Medium'], [700, 'Bold'], [900, 'Black']] },
    'raleway': { css: 'https://fonts.googleapis.com/css2?family=Raleway:wght@100..900&display=swap', family: "'Raleway'", weights: W9 },
    'petrona': { css: 'https://fonts.googleapis.com/css2?family=Petrona:wght@100..900&display=swap', family: "'Petrona'", weights: W9 },
    'playfairdisplay': { css: 'https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400..900&display=swap', family: "'Playfair Display'", weights: [[400, 'Regular'], [500, 'Medium'], [600, 'SemiBold'], [700, 'Bold'], [800, 'ExtraBold'], [900, 'Black']] },
    'librebodoni': { css: 'https://fonts.googleapis.com/css2?family=Libre+Bodoni:wght@400..700&display=swap', family: "'Libre Bodoni'", weights: [[400, 'Regular'], [500, 'Medium'], [600, 'SemiBold'], [700, 'Bold']] },
    'dancingscript': { css: 'https://fonts.googleapis.com/css2?family=Dancing+Script:wght@400..700&display=swap', family: "'Dancing Script'", weights: [[400, 'Regular'], [500, 'Medium'], [600, 'SemiBold'], [700, 'Bold']] },
    'cinzeldecorative': { css: 'https://fonts.googleapis.com/css2?family=Cinzel+Decorative:wght@400;700;900&display=swap', family: "'Cinzel Decorative'", weights: [[400, 'Regular'], [700, 'Bold'], [900, 'Black']] },
    'bonanova': { css: 'https://fonts.googleapis.com/css2?family=Bona+Nova:wght@400;700&display=swap', family: "'Bona Nova'", weights: [[400, 'Regular'], [700, 'Bold']] }
  };

  function webfontOf(name) {
    var key = (name || '').replace(/\s+/g, '').toLowerCase();
    var wf = WEBFONT_MAP[key];
    if (wf && wf.css && !wf._loaded) {
      wf._loaded = true;
      var l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = wf.css;
      document.head.appendChild(l);
    }
    return wf || null;
  }

  /* 어드민이 등록한 DB 웹폰트가 하드코딩 표보다 우선한다.
     단, 어드민이 파일을 직접 올렸으면(file_source==='user') 그 파일이 이긴다 —
     파일을 올렸다는 행위 자체가 "이 파일을 쓰겠다"는 뜻이다. */
  var dbWebfontLoaded = {};
  function resolveWebfont(f) {
    if (f && f.webfont_family && f.file_source !== 'user') {
      if (f.webfont_css_url && !dbWebfontLoaded[f.webfont_family]) {
        dbWebfontLoaded[f.webfont_family] = true;
        var l = document.createElement('link');
        l.rel = 'stylesheet'; l.href = f.webfont_css_url;
        document.head.appendChild(l);
      }
      var ws = (f.webfont_weights && f.webfont_weights.length) ? f.webfont_weights : [400];
      return {
        family: "'" + f.webfont_family + "'",
        css: null,
        weights: ws.map(function (w) { return [w, WEIGHT_LABEL_KO[w] || String(w)]; })
      };
    }
    return webfontOf(f ? f.name : '');
  }

  // ── 로컬 파일 ──────────────────────────────────────────────────
  var loaded = {};

  /* 대표 파일 한 벌. 굵기 구분이 필요 없는 자리(폰트명·본문 등)가 쓴다. */
  function ensureFont(f, preview) {
    if (!f || !f.has_file || loaded[f.id]) return;
    loaded[f.id] = true;
    addFace('FFP-' + pad3(f.id), fileUrl(f.id, 0, verOf(f), preview));
  }

  /* 굵기마다 family 이름을 따로 준다 — FFP-222-300, FFP-222-500 …
     한 family 안에 font-weight 기술자만 다른 face를 여러 개 넣고 어느 파일을 쓸지
     브라우저에게 맡기면, 그 고르기가 폰트에 따라 어긋난다. 경복궁 수문장 본문체가
     그랬다 — 서버는 300/500/700에 서로 다른 파일을 정확히 내려주는데(md5로 확인)
     화면에서는 Light와 Medium이 같은 모양으로 나오고 Bold만 달랐다. 파일 안의
     굵기 값을 고쳐 올려도 그대로였다.
     이름을 갈라 두면 고를 여지 자체가 없어진다. */
  function weightFamily(id, weight) {
    return 'FFP-' + pad3(id) + '-' + weight;
  }

  function registerWeightFaces(id, list, primaryWeight, ver, preview) {
    list.forEach(function (w) {
      addFace(weightFamily(id, w.weight), fileUrl(id, w.weight, ver, preview));
    });
    /* 굵기 구분 없이 FFP-{id}를 쓰는 자리(stackOf)가 빈 family를 가리키지 않도록
       대표 굵기로 한 벌 더 등록한다. */
    var pw = primaryWeight;
    if (!pw) {
      for (var i = 0; i < list.length; i++) {
        if (!pw || Math.abs(list[i].weight - 400) < Math.abs(pw - 400)) pw = list[i].weight;
      }
    }
    if (pw) addFace('FFP-' + pad3(id), fileUrl(id, pw, ver, preview));
    loaded[id] = true;
  }

  /* 특정 굵기로 그려야 하는 자리(조합 카드·견본 슬롯)가 쓴다.
     반드시 {stack, weight} 두 개를 함께 받아 CSS에 그대로 적어야 한다.
     굵기를 부르는 쪽이 마음대로 정하면 어긋난다 — 그 굵기의 파일이 직접 그리는
     경우에는 CSS로 굵기를 또 요구하면 브라우저가 그 위에 가짜 볼드를 덧씌운다.

     네 가지 경우가 있고 각각 답이 다르다:
       ① CDN 웹폰트     — face마다 진짜 굵기 기술자가 있다 → 부른 굵기 그대로
       ② 파일 없음       — 시스템 대체 폰트 → 합성 말고는 방법이 없다 → 그대로
       ③ 그 굵기 파일 있음 — 파일이 직접 그린다 → weight는 400 (합성 금지)
       ④ 대표 파일뿐     — 1~999로 등록해 합성을 유도 → 부른 굵기 그대로 */
  var pairLoaded = {};
  function faceFor(f, weight) {
    if (!f) return { stack: "sans-serif", weight: weight };

    var wf = resolveWebfont(f);
    if (wf) {                                                   // ①
      return { stack: wf.family + ',' + (f.stack || "sans-serif"),
               weight: weight };
    }
    if (!f.has_file) {                                          // ②
      return { stack: f.stack || "sans-serif", weight: weight };
    }

    var avail = f.available_weights || [];
    if (avail.indexOf(weight) >= 0) {                           // ③
      var fam = weightFamily(f.id, weight);
      if (!pairLoaded[fam]) {
        pairLoaded[fam] = true;
        addFace(fam, fileUrl(f.id, weight, verOf(f)));
      }
      return { stack: "'" + fam + "'," + baseStack(f), weight: 400 };
    }
    var wide = 'FFPW-' + pad3(f.id);                            // ④
    if (!pairLoaded[wide]) {
      pairLoaded[wide] = true;
      addFace(wide, fileUrl(f.id, 0, verOf(f)), '1 999');
    }
    return { stack: "'" + wide + "'," + baseStack(f), weight: weight };
  }

  /* 굵기 구분 없이 그 폰트로 그리기만 하면 되는 자리의 font-family 스택.
     resolveWebfont와 우선순위가 같아야 한다 — 한쪽만 바꾸면 @font-face는 등록되는데
     font-family는 웹폰트를 가리키는 어긋남이 생긴다. */
  function stackOf(f) {
    if (f && f.webfont_family && f.file_source !== 'user') {
      return "'" + f.webfont_family + "'," + (f.stack || "sans-serif");
    }
    var base = f && f.stack || "sans-serif";
    if (!f || !f.has_file) return base;
    var fam = 'FFP-' + pad3(f.id);
    return base.indexOf(fam) >= 0 ? base : "'" + fam + "'," + base;
  }

  global.FFPFont = {
    fileUrl: fileUrl,
    W9: W9,
    WEIGHT_LABEL_KO: WEIGHT_LABEL_KO,
    webfontOf: webfontOf,
    resolveWebfont: resolveWebfont,
    ensureFont: ensureFont,
    faceFor: faceFor,
    stackOf: stackOf,
    weightFamily: weightFamily,
    registerWeightFaces: registerWeightFaces,
    baseStack: baseStack
  };
})(window);
