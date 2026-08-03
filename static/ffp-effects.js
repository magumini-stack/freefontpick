/* ══════════════════════════════════════════════════════════════════
   ffp-effects.js — 글자 효과 32종 단일 소스

   '디자인하기'(font.html)와 GIF 생성기가 같은 효과를 써야 한다.
   전에는 두 파일에 같은 배열이 각각 박혀 있어서, 효과를 하나 고치면
   다른 쪽이 조용히 옛 값으로 남았다. 이 파일이 유일한 출처다.

   여기 있는 것
   -----------
   FFP_EFFECTS        효과 32종
   FFP_GIF_RATING     효과별 GIF 적합도 0~3 (색이 많을수록 GIF가 무거워진다)
   ffpApplyShadow     그림자 5종 — 원래 네 곳에 복사돼 있던 if 사다리
   ffpAutoMatte       투명 GIF 가장자리에 미리 섞을 색
   ffpEnsureFontReady 폰트가 실제로 로드될 때까지 기다린다 (아래 주석 참고)
══════════════════════════════════════════════════════════════════ */

const FFP_EFFECTS = [
  {id:'none', name:'없음', color:'#111111', outline:null, outlineW:0, shadow:'none'},
  /* ── 클래식 ── */
  {id:'classic-white', name:'화이트', color:'#FFFFFF', outline:'#000000', outlineW:6, shadow:'soft'},
  {id:'classic-black', name:'블랙', color:'#000000', outline:'#FFFFFF', outlineW:6, shadow:'gray'},
  {id:'soft-shadow', name:'소프트', color:'#FFFFFF', outline:null, outlineW:0, shadow:'strong'},
  {id:'bold-outline', name:'굵은외곽선', color:'#FFFFFF', outline:'#000000', outlineW:12, shadow:'none'},
  {id:'double-line', name:'더블라인', color:'#111111', outline:'#FFFFFF', outlineW:10, shadow:'soft'},
  /* ── 컬러 ── */
  {id:'golden', name:'골드', color:'#FFD700', outline:'#7A5C00', outlineW:5, shadow:'soft'},
  {id:'silver', name:'실버', color:'#E5E7EB', outline:'#6B7280', outlineW:5, shadow:'soft'},
  {id:'sky-blue', name:'스카이', color:'#7DD3FC', outline:'#FFFFFF', outlineW:6, shadow:'soft'},
  {id:'rose-pink', name:'로즈핑크', color:'#EC4899', outline:'#FFFFFF', outlineW:6, shadow:'soft'},
  {id:'mint', name:'민트', color:'#5EEAD4', outline:'#0F766E', outlineW:5, shadow:'soft'},
  {id:'lavender', name:'라벤더', color:'#C4B5FD', outline:'#6D28D9', outlineW:5, shadow:'soft'},
  {id:'lemon', name:'레몬', color:'#FDE047', outline:'#A16207', outlineW:5, shadow:'none'},
  {id:'cherry', name:'체리', color:'#DC2626', outline:'#FFFFFF', outlineW:6, shadow:'soft'},
  {id:'forest', name:'포레스트', color:'#16A34A', outline:'#FFFFFF', outlineW:6, shadow:'soft'},
  {id:'midnight', name:'미드나잇', color:'#1E3A8A', outline:'#93C5FD', outlineW:5, shadow:'gray'},
  /* ── 네온 ── */
  {id:'neon-blue', name:'네온블루', color:'#06B6D4', outline:'#1D4ED8', outlineW:4, shadow:'glow'},
  {id:'neon-pink', name:'네온핑크', color:'#FF1493', outline:'#7C3AED', outlineW:4, shadow:'glow'},
  {id:'neon-green', name:'네온그린', color:'#4ADE80', outline:'#15803D', outlineW:4, shadow:'glow'},
  {id:'neon-purple', name:'네온퍼플', color:'#A855F7', outline:'#6D28D9', outlineW:4, shadow:'glow'},
  {id:'neon-orange', name:'네온오렌지', color:'#FB923C', outline:'#C2410C', outlineW:4, shadow:'glow'},
  /* ── 무드 ── */
  {id:'frost', name:'프로스트', color:'#BBE6FF', outline:'#FFFFFF', outlineW:4, shadow:'blur'},
  {id:'comic', name:'코믹', color:'#FBBF24', outline:'#000000', outlineW:12, shadow:'none'},
  {id:'retro', name:'레트로', color:'#F59E0B', outline:'#78350F', outlineW:8, shadow:'gray'},
  {id:'vintage', name:'빈티지', color:'#D4A574', outline:'#5C3D1E', outlineW:5, shadow:'gray'},
  {id:'candy', name:'캔디', color:'#F9A8D4', outline:'#DB2777', outlineW:6, shadow:'none'},
  /* ── 그라데이션 ── */
  {id:'sunset', name:'선셋', color:'#F97316', outline:'#FFFFFF', outlineW:6, shadow:'soft', gradient:['#F97316','#EC4899']},
  {id:'ocean', name:'오션', color:'#06B6D4', outline:'#FFFFFF', outlineW:6, shadow:'soft', gradient:['#06B6D4','#3B82F6','#7C3AED']},
  {id:'rainbow', name:'레인보우', color:'#EF4444', outline:'#FFFFFF', outlineW:6, shadow:'soft', gradient:['#EF4444','#F97316','#FBBF24','#10B981','#06B6D4','#7C3AED','#EC4899']},
  {id:'gold-grad', name:'골드빔', color:'#FCD34D', outline:'#92400E', outlineW:5, shadow:'soft', gradient:['#FEF3C7','#FCD34D','#D97706']},
  {id:'purple-magenta', name:'퍼플마젠타', color:'#A855F7', outline:'#FFFFFF', outlineW:6, shadow:'soft', gradient:['#A855F7','#EC4899']},
  {id:'fire', name:'파이어', color:'#EF4444', outline:'#7F1D1D', outlineW:5, shadow:'glow', gradient:['#FBBF24','#F97316','#DC2626']},
];

const FFP_EFFECT_BY_ID = FFP_EFFECTS.reduce((m,e)=>{ m[e.id]=e; return m; }, {});

/* GIF 적합도 — 3 안전 / 2 보통 / 1 주의 / 0 비권장.
   GIF는 프레임당 색이 256개(투명 배경은 64개)뿐이라, 그라데이션과 글로우처럼
   중간색이 많이 필요한 효과는 띠(banding)가 생기고 파일도 커진다. */
const FFP_GIF_RATING = {
  'none':3,'classic-black':3,'bold-outline':3,'lemon':3,'midnight':3,'comic':3,'retro':3,'vintage':3,'candy':3,
  'classic-white':2,'soft-shadow':2,'double-line':2,'golden':2,'silver':2,'sky-blue':2,
  'rose-pink':2,'mint':2,'lavender':2,'cherry':2,'forest':2,
  'neon-blue':1,'neon-pink':1,'neon-green':1,'neon-purple':1,'neon-orange':1,
  'sunset':1,'ocean':1,'gold-grad':1,'purple-magenta':1,'fire':1,
  'rainbow':0,'frost':0,
};

/* 등급 누락 감지 — 33번째 효과를 추가하고 등급을 안 넣으면 조용히 ★★로
   표시된다. 그러면 "왜 이 효과만 GIF가 3MB지"를 한참 뒤에 발견한다.
   개발 중에만 콘솔로 알린다. */
(function(){
  const missing = FFP_EFFECTS.filter(e => FFP_GIF_RATING[e.id] === undefined).map(e => e.id);
  if(missing.length) console.warn('[ffp-effects] GIF 등급이 없는 효과:', missing.join(', '));
})();

/* 그림자 5종.
   glowColor를 인자로 받는 이유 — 네온 계열은 글자색을 그대로 번지게 한다.
   그런데 '디자인하기'는 사용자가 글자색을 바꿀 수 있어서 eff.color가 아니라
   실제 칠하는 색을 넘겨야 한다. 함수 안에서 eff로 유도하면 색을 바꿔도
   번짐만 원래 색으로 남는다. */
function ffpApplyShadow(ctx, eff, glowColor){
  ctx.shadowColor='transparent'; ctx.shadowBlur=0; ctx.shadowOffsetX=0; ctx.shadowOffsetY=0;
  if(eff.shadow==='soft'){   ctx.shadowColor='rgba(0,0,0,.35)'; ctx.shadowBlur=10; ctx.shadowOffsetY=6; }
  if(eff.shadow==='strong'){ ctx.shadowColor='rgba(0,0,0,.55)'; ctx.shadowBlur=4;  ctx.shadowOffsetY=10; }
  if(eff.shadow==='gray'){   ctx.shadowColor='rgba(120,120,120,.5)'; ctx.shadowBlur=8; ctx.shadowOffsetY=4; }
  if(eff.shadow==='glow'){   ctx.shadowColor=glowColor; ctx.shadowBlur=28; }
  if(eff.shadow==='blur'){   ctx.shadowColor='rgba(150,200,255,.6)'; ctx.shadowBlur=14; }
}

/* 매트 색 — 투명 GIF는 알파가 1비트(있다/없다)뿐이라 반투명 가장자리를
   표현하지 못한다. 그래서 미리 어떤 색과 섞어둘지 정해야 하는데,
   올릴 배경을 모르니 "글자 테두리에 실제로 있는 색"을 쓴다. */
function ffpAutoMatte(eff){
  if(!eff) return '#000000';
  if(eff.outline && eff.outlineW>0) return eff.outline;
  if(eff.gradient && eff.gradient.length) return eff.gradient[Math.floor(eff.gradient.length/2)];
  return eff.color;
}

/* ══════════════════════════════════════════════════════════════════
   폰트 로딩

   위험: @font-face 규칙을 <style>에 넣는 것만으로는 폰트가 준비되지 않는다.
   로드가 끝나기 전에 measureText를 부르면 브라우저는 조용히 대체 폰트의
   폭을 돌려준다. 화면 미리보기는 사용자가 계속 조작하며 다시 그려서
   저절로 고쳐지지만, GIF 내보내기 루프는 한 번에 50프레임을 돌기 때문에
   전부 엉뚱한 폰트로 저장된다.
   → 첫 렌더 전·내보내기 전·폰트나 굵기를 바꾼 뒤에 반드시 await 한다.
══════════════════════════════════════════════════════════════════ */

const FFP_WEIGHT_LABELS = {
  100:'Thin', 200:'ExtraLight', 300:'Light', 400:'Regular',
  500:'Medium', 600:'SemiBold', 700:'Bold', 800:'ExtraBold', 900:'Black',
};

function ffpFamilyFor(id, weight){
  const base = `FFP-${String(id).padStart(3,'0')}`;
  return weight ? `${base}-${weight}` : base;
}

const _ffpFaces = new Set();      // 이미 @font-face를 넣은 (id,weight)
const _ffpCssUrls = new Set();    // 이미 <link>를 넣은 웹폰트 CSS
const _ffpStyleEl = (() => {
  let el = document.getElementById('ffp-face-styles');
  if(!el){
    el = document.createElement('style');
    el.id = 'ffp-face-styles';
    document.head.appendChild(el);
  }
  return el;
})();

/* 폰트 하나를 등록하고 CSS에서 쓸 font-family 이름을 돌려준다.
   굵기마다 별도 family를 만드는 이유 — 사이트의 굵기는 같은 가족의
   variation이 아니라 서로 다른 파일이다. 한 family에 여러 weight를
   등록하면 캔버스가 어느 파일을 쓸지 브라우저마다 다르게 고른다. */
function ffpRegisterFace(font, weight){
  if(!font) return null;
  if(font.webfontFamily || font.webfont_family){
    const url = font.webfontCssUrl || font.webfont_css_url;
    if(url && !_ffpCssUrls.has(url)){
      _ffpCssUrls.add(url);
      const l = document.createElement('link');
      l.rel = 'stylesheet'; l.href = url;
      document.head.appendChild(l);
    }
    return font.webfontFamily || font.webfont_family;
  }
  const hasFile = font.hasFile !== undefined ? font.hasFile : font.has_file;
  if(!hasFile) return null;

  const w = weight || 0;
  const family = ffpFamilyFor(font.id, w);
  const key = `${font.id}:${w}`;
  if(!_ffpFaces.has(key)){
    _ffpFaces.add(key);
    const url = w ? `/api/fonts/${font.id}/file?weight=${w}` : `/api/fonts/${font.id}/file`;
    /* font-display:swap — 폰트가 오기 전에는 기본 글꼴로 보여준다.
       block으로 두면 목록의 문구 칸이 몇 초간 빈칸으로 보인다.
       캔버스는 ffpEnsureFontReady로 로드를 기다린 뒤에 그리므로,
       swap이라고 해서 대체 글꼴로 저장될 일은 없다. */
    _ffpStyleEl.appendChild(document.createTextNode(
      `@font-face{font-family:'${family}';src:url('${url}') format('woff2');`
      + `font-display:swap;font-weight:normal;font-style:normal}`
    ));
  }
  return family;
}

function ffpEffectiveStack(font, weight){
  const base = (font && (font.stack)) || "'Nanum Gothic',sans-serif";
  const family = ffpRegisterFace(font, weight);
  if(!family) return base;
  if(base.includes(`'${family}'`)) return base;
  return `'${family}',${base}`;
}

/* 폰트가 실제로 그려질 준비가 될 때까지 기다린다.
   document.fonts.load는 "이 크기의 이 family"를 지정해야 실제로 받는다.
   ready까지 함께 기다리는 이유는, load가 끝나도 폰트 목록 갱신이
   한 틱 늦는 브라우저가 있어서다. 실패해도 던지지 않는다 —
   폰트 하나 때문에 편집기가 멈추는 것보다 대체 폰트로라도 보이는 게 낫다. */
async function ffpEnsureFontReady(font, weight, sizePx){
  const family = ffpRegisterFace(font, weight);
  if(!family) return false;
  const spec = `${Math.max(8, Math.round(sizePx||64))}px '${family}'`;
  try{
    await document.fonts.load(spec, '가나다ABC');
    await document.fonts.ready;
    return document.fonts.check(spec, '가');
  }catch(e){
    return false;
  }
}
