/* ══════════════════════════════════════════════════════════════════
   gif-render.js — GIF 생성기의 유일한 렌더러

   공개 편집기(/gif), 어드민 제작툴(/admin/gif), 갤러리 썸네일(/gif/templates)이
   전부 이 파일 하나를 쓴다. 미리보기와 내려받은 파일이 다르게 나오는 사고는
   렌더러가 두 벌일 때 생긴다. 늘리지 말 것.

   ffp-effects.js 를 먼저 불러와야 한다.

   원본과 달라진 점
   ---------------
   1. 모듈 전역(ctx/W/H/S/오프스크린)을 인스턴스로 감쌌다.
      갤러리는 캔버스를 수십 개 동시에 띄우는데, 오프스크린이 공유되면
      '골드 스윕'이 서로의 그림을 덮어쓴다.
   2. 폰트가 PC 폰트명이 아니라 사이트 폰트 {id, weight}다.
   3. 글자 크기를 비율에 맞춰 환산한다. 800×450에서 정한 78px을
      다른 비율로 옮길 때 좁아지는 쪽 배율을 쓴다 (sizePx 주석 참고).
══════════════════════════════════════════════════════════════════ */
(function(global){
'use strict';

/* 화면 비율 4종. 폭·높이 모두 짝수 — H.264가 홀수 해상도를 거부한다. */
const RATIOS = {
  '16:9': {w:800, h:450, label:'16:9', desc:'블로그·유튜브 썸네일'},
  '1:1':  {w:650, h:650, label:'1:1',  desc:'인스타 피드·카톡'},
  '4:5':  {w:560, h:700, label:'4:5',  desc:'인스타 세로'},
  '9:16': {w:450, h:800, label:'9:16', desc:'릴스·스토리·쇼츠'},
};

const ANIMS = [
  /* 멈춤은 '움직이지 않는 것'을 고르는 칸이다. 사진·영상 위에 자막을 가만히
     얹거나, 질감·외곽선을 그대로 보여주고 싶을 때 쓴다. 목록 맨 앞에 둔다. */
  {id:'none',           name:'멈춤',        cat:'basic'},
  {id:'typewriter',     name:'타이핑',      cat:'basic'},
  {id:'pop',            name:'글자 팝',     cat:'basic'},
  {id:'wordSwap',       name:'단어 교체',   cat:'basic'},
  {id:'slideUp',        name:'슬라이드 업', cat:'basic'},
  {id:'highlight',      name:'하이라이트',  cat:'basic'},
  {id:'zoomIn',         name:'줌 인',       cat:'basic'},
  {id:'wipe',           name:'마스크 와이프', cat:'basic'},
  {id:'bounceDrop',     name:'바운스 드롭', cat:'basic'},
  {id:'neonFlicker',    name:'네온 점멸',   cat:'basic'},
  {id:'flip',           name:'글자 회전',   cat:'basic'},
  {id:'cinematicTrack', name:'시네마틱',    cat:'cinematic'},
  {id:'shineSweep',     name:'골드 스윕',   cat:'cinematic'},
  {id:'slamImpact',     name:'슬램 임팩트', cat:'dynamic'},
  {id:'spinIn',         name:'스핀 인',     cat:'dynamic'},
  {id:'elasticStretch', name:'고무줄',      cat:'dynamic'},
  {id:'shuffleIn',      name:'셔플',        cat:'dynamic'},
  {id:'kickUp',         name:'킥업',        cat:'dynamic'},
  {id:'rollIn',         name:'롤인',        cat:'dynamic'},
];
const ANIM_BY_ID = ANIMS.reduce((m,a)=>{ m[a.id]=a; return m; }, {});

/* 애니메이션별 권장 길이·프레임레이트.
   시네마틱은 다단계 구성이라 길어야 하고, 느린 모션이라 15fps로 충분하다.
   역동 계열은 빠른 동작이라 fps가 낮으면 뚝뚝 끊겨 보인다. */
const ANIM_DEFAULTS = {
  /* 멈춤은 길이·프레임레이트가 뜻이 없다 — 그래도 슬라이더가 범위를 벗어난
     값을 들고 있으면 눈금이 끝에 붙어 고장난 것처럼 보이므로, 각 슬라이더의
     최솟값(1.0s · 8fps · 0.3s)을 넣어둔다. */
  none:          {total:1.0, fps:8,  inDur:0.3},
  cinematicTrack:{total:4.5, fps:15, inDur:2.0},
  shineSweep:    {total:4.0, fps:15, inDur:1.4},
  slamImpact:    {total:2.2, fps:24, inDur:0.9},
  spinIn:        {total:2.4, fps:24, inDur:1.2},
  elasticStretch:{total:2.6, fps:24, inDur:1.4},
  shuffleIn:     {total:2.4, fps:24, inDur:1.2},
  kickUp:        {total:2.2, fps:24, inDur:1.0},
  rollIn:        {total:2.6, fps:24, inDur:1.3},
  _default:      {total:2.5, fps:20, inDur:1.5},
};
function animDefaults(id){ return ANIM_DEFAULTS[id] || ANIM_DEFAULTS._default; }

const HL_PRESETS = ['#FDE047','#FDBA74','#F9A8D4','#2563EB','#00E5C0','#22C55E','#FFFFFF'];

/* 프레임 상한. 4.5s × 24fps = 108장까지 갈 수 있는데, 구형 아이폰은
   그쯤에서 탭이 죽는다. 넘으면 fps를 낮춰 맞춘다. */
const MAX_FRAMES = 90;

/* 사진 GIF 상한.
   8장 × (1.2s + 0.4s) = 12.8초다. 여기에 사진 모드 기본 10fps를 곱하면
   128프레임 — MAX_FRAMES(90)를 넘어 frameCount()가 잘라내고 실제 fps가
   7fps로 떨어진다. 슬라이드쇼는 그 정도로도 볼 만하지만, 더 늘리면
   장당 시간이 눈에 띄게 뚝뚝 끊긴다. 그래서 8장에서 끊는다. */
const MAX_PHOTOS = 8;

/* 사진 모드 기본값. 글자 애니메이션(20~24fps)보다 훨씬 낮게 잡는다 —
   사진은 한 장을 1초 넘게 보여주므로 프레임을 촘촘히 쓸 이유가 없고,
   프레임 하나하나가 통째로 다시 저장되는 사진 GIF에서는 fps가 곧 용량이다. */
const PHOTO_DEFAULTS = {slideDur:1.2, xfadeDur:0.4, fps:10, dim:0};

/* 영상 GIF.
   상한 10초는 제품 결정이지만, 그 길이가 실제로 어떤 결과인지 알고 써야 한다:
   프레임 상한이 90장이라 10초를 채우면 9fps까지 떨어져 뚝뚝 끊기고, 복잡한
   영상이면 25MB·2분이 나온다. 그래서 기본은 4초로 시작한다 — 같은 90프레임을
   4초에 쓰면 22fps로 부드럽다. 늘리는 건 사용자가 결과를 보며 정하면 된다. */
const VIDEO_MAX_SEC = 10;
const VIDEO_DEFAULT_SEC = 4;
const VIDEO_DEFAULTS = {fps:15};

/* 이징 */
const E = {
  outCubic:t=>1-Math.pow(1-t,3),
  outQuint:t=>1-Math.pow(1-t,5),
  outExpo:t=>t>=1?1:1-Math.pow(2,-10*t),
  outBack:t=>{const c=1.70158,s=c+1;return 1+s*Math.pow(t-1,3)+c*Math.pow(t-1,2);},
  inCubic:t=>t*t*t,
  outElastic:t=>{ if(t===0||t===1) return t; const p=.34;
    return Math.pow(2,-10*t)*Math.sin((t-p/4)*(2*Math.PI)/p)+1; },
  outBack2:t=>{const c=3.2,s=c+1;return 1+s*Math.pow(t-1,3)+c*Math.pow(t-1,2);},
  outBounce:t=>{const n=7.5625,d=2.75;
    if(t<1/d)return n*t*t;
    if(t<2/d)return n*(t-=1.5/d)*t+.75;
    if(t<2.5/d)return n*(t-=2.25/d)*t+.9375;
    return n*(t-=2.625/d)*t+.984375;},
};
const cl = v => v<0?0:v>1?1:v;

/* ══════════════════════════════════════════════════════════════════
   글자색 · 외곽선

   GIF 생성기에는 그림자도 네온도 없다.
   -----------------------------------
   투명 GIF의 알파는 1비트다 — 있거나 없거나. 그림자와 네온은 본질이
   '점점 옅어지는 번짐'이라 여기에 담기지 않는다. 화면에서는 멀쩡하다가
   내려받으면 글자 주변이 톱니처럼 뭉개져 나갔다. 색과 외곽선만 남기면
   경계가 또렷해서 1비트 알파로도 손실이 없다.

   (font.html의 '디자인하기'는 PNG로 저장하므로 그림자 효과 32종을
    그대로 쓴다. ffp-effects.js는 건드리지 않는다.)
══════════════════════════════════════════════════════════════════ */

/* 글자색·외곽선 공용 색 견본 */
const INK_SWATCHES = [
  '#000000', '#FFFFFF', '#4B5563', '#DC2626', '#EA580C', '#F59E0B',
  '#FDE047', '#16A34A', '#5EEAD4', '#0EA5E9', '#1E3A8A', '#7C3AED',
  '#EC4899', '#F9A8D4', '#D4A574', '#78350F',
];

/* 여러 색(그라데이션) 프리셋 — 왼쪽에서 오른쪽으로 흐른다 */
const INK_GRADIENTS = [
  {id:'rainbow', name:'무지개', colors:['#EF4444','#F59E0B','#FDE047','#22C55E','#0EA5E9','#7C3AED']},
  {id:'gold',    name:'골드',   colors:['#FEF3C7','#FCD34D','#D97706']},
  {id:'silver',  name:'실버',   colors:['#F8FAFC','#CBD5E1','#64748B']},
  {id:'sunset',  name:'노을',   colors:['#FDE047','#FB923C','#DC2626']},
  {id:'ocean',   name:'바다',   colors:['#67E8F9','#0EA5E9','#1E3A8A']},
  {id:'candy',   name:'사탕',   colors:['#F9A8D4','#C084FC','#818CF8']},
  {id:'mint',    name:'민트',   colors:['#A7F3D0','#5EEAD4','#0F766E']},
  {id:'berry',   name:'베리',   colors:['#FBCFE8','#EC4899','#831843']},
];

/* 옛 효과 id → 색·외곽선.
   템플릿 50종의 config에는 아직 effect:'classic-black' 같은 값이 들어 있다.
   그림자만 떼고 색과 외곽선을 그대로 옮긴다. */
function inkFromEffectId(id){
  const e = (typeof FFP_EFFECT_BY_ID !== 'undefined' && FFP_EFFECT_BY_ID[id]) || null;
  if(!e) return {color:'#111111', gradient:null, outline:null, outlineW:0};
  return {
    color: e.color || '#111111',
    gradient: e.gradient ? e.gradient.slice() : null,
    outline: e.outline || null,
    outlineW: e.outline ? (e.outlineW || 0) : 0,
  };
}

/* 상대 밝기 0~1. 형광 바 위의 글자가 읽히는지 판단할 때 쓴다. */
function lumOf(hex){
  const h = String(hex||'').replace('#','');
  if(h.length < 6) return 0;
  const [r,g,b] = [0,2,4].map(i => parseInt(h.slice(i,i+2),16));
  return (0.2126*r + 0.7152*g + 0.0722*b) / 255;
}

/* GIF 적합도 — 색이 많을수록 팔레트를 많이 먹고 용량이 커진다.
   3점이 가장 안정적. 예전에는 효과별로 손으로 매겨둔 표를 썼는데,
   이제 실제로 쓰는 색 개수에서 바로 뽑는다. */
function inkRating(ink){
  if(!ink || !ink.gradient) return 3;
  return ink.gradient.length >= 5 ? 1 : 2;
}

/* ── 기본 상태 ────────────────────────────────────────────────── */
function defaultState(){
  return {
    text: '지금 아니면 늦어요',
    fontId: null,          // 사이트 폰트 id
    fontWeight: 700,
    fontStack: "'Nanum Gothic',sans-serif",   // ffpEffectiveStack 결과
    size: 64,              // baseW×baseH 캔버스에서 정한 크기
    baseW: 800,            // size를 정할 때의 캔버스 폭
    baseH: 450,            // 〃 높이
    lh: 1.3,
    posY: 0.5,
    color: '#FFFFFF',      // 글자색
    gradient: null,        // ['#a','#b',…] — 있으면 색 대신 이걸로 채운다
    outline: '#000000',    // null이면 외곽선 없음
    outlineW: 12,
    anim: 'typewriter',
    total: 2.5,
    fps: 20,
    inDur: 1.5,
    hl: '#FDE047',
    hlOn: false,
    matteAuto: true,
    matte: '#000000',
    photo: null,           // ImageBitmap
    photoX: 0, photoY: 0, dim: 35,
    bgColor: null,         // 단색 배경. null이면 투명 (사진이 있으면 사진이 이긴다)
    ratio: '16:9',

    /* ── 사진 GIF 모드 ──
       'text'  : 지금까지의 글자 애니메이션. photo는 '배경 1장'일 뿐이다.
       'photo' : photos[]를 순서대로 넘기는 슬라이드쇼. 글자는 얹을 수도 뺄 수도 있다.
       두 모드의 상태를 한 덩어리에 두는 이유 — 렌더러는 하나뿐이고
       (파일 머리 주석 참고) 모드를 오가도 폰트·색·비율을 그대로 이어가야 한다. */
    mode: 'text',
    photos: [],            // ImageBitmap[] — 사진 모드에서만 쓴다
    slideDur: PHOTO_DEFAULTS.slideDur,   // 한 장을 그대로 보여주는 시간(초)
    xfadeDur: PHOTO_DEFAULTS.xfadeDur,   // 다음 장으로 겹쳐 넘어가는 시간(초)
    /* 글자를 얹을지는 모드마다 따로 기억한다. 하나로 묶으면 사진에서 끈 것이
       영상 탭까지 따라가서, 영상 탭에 들어갔더니 문구 칸이 사라져 있다. */
    photoTextOn: true,
    videoTextOn: true,
    /* dim과 따로 둔다. 배경 사진의 dim(35%)은 '글자를 읽히게 하려고' 어둡게
       하는 값이고, 사진 GIF는 사진 자체가 내용이라 기본이 0이다. 하나로 묶으면
       한쪽에서 조절한 값이 다른 쪽 결과를 조용히 바꾼다. */
    slideDim: PHOTO_DEFAULTS.dim,
    /* 사진 GIF 용량·시간 실측 결과. UI가 프레임 한 장을 인코딩해 넣는다.
       {bytes, ms, key} — key가 지금 상태와 다르면 낡은 값이라 쓰지 않는다.
       photosRev는 사진 목록이 바뀔 때마다 UI가 올리는 번호다 (장수만 봐서는
       순서 바꾸기·같은 장수로 교체를 알아챌 수 없다). */
    photoSample: null,
    photosRev: 0,
    bgPhotoRev: 0,         // 배경 사진(글자 모드)이 바뀔 때 UI가 올린다

    /* ── 영상 GIF 모드 ──
       프레임을 미리 뽑아 쌓아두지 않는다. 90프레임을 800×450 비트맵으로 들고
       있으면 130MB다 — 폰에서 탭이 죽는다. 대신 미리보기는 video 요소를 그냥
       재생해서 그리고, 내보낼 때만 prepareFrame()으로 한 장씩 찾아간다. */
    video: null,           // HTMLVideoElement — 편집기가 만들어 넣는다
    videoDur: 0,           // 원본 전체 길이(초)
    trimStart: 0,
    trimEnd: VIDEO_DEFAULT_SEC,
    videoRev: 0,
  };
}

/* 잘라낸 구간의 길이. 상한을 넘기지 않게 여기서 한 번 더 조인다 —
   UI가 막더라도 상태를 직접 건드리는 경로(임시저장 복원 등)가 있다. */
function trimSpan(S){
  const span = (S.trimEnd || 0) - (S.trimStart || 0);
  return Math.max(0.2, Math.min(VIDEO_MAX_SEC, span));
}

/* 사진 모드의 전체 길이. 마지막 장은 첫 장으로 되돌아가며 겹쳐지므로
   장마다 (보여주기 + 넘어가기)가 똑같이 한 번씩 들어간다. 그래야 GIF가
   반복 재생될 때 이음매가 보이지 않는다. */
function slideshowTotal(S){
  const n = (S.photos && S.photos.length) || 0;
  if(!n) return 2.5;
  return n * (Math.max(0.2, S.slideDur) + Math.max(0, S.xfadeDur));
}

/* ══════════════════════════════════════════════════════════════════
   렌더러 인스턴스
══════════════════════════════════════════════════════════════════ */
/* opts.scale — 캔버스를 실제보다 작게 그린다 (갤러리 썸네일용).
   좌표 계산은 전부 원래 크기(W×H) 그대로 두고 컨텍스트만 축소하므로,
   같은 코드가 카드에서도 내보내기에서도 똑같은 그림을 만든다.
   해상도를 줄이지 않고 CSS로만 줄이면 썸네일 수십 장이 800×450을
   매 프레임 그리게 되어 노트북이 뜨거워진다. */
function createRenderer(canvas, initial, opts){
  const ctx = canvas.getContext('2d', {willReadFrequently:true});
  const S = Object.assign(defaultState(), initial||{});
  const scale = (opts && opts.scale) || 1;
  let W = 800, H = 450;
  let _off = null;               // 오프스크린 — 인스턴스마다 하나

  function applyRatio(){
    const r = RATIOS[S.ratio] || RATIOS['16:9'];
    W = r.w; H = r.h;
    const cw = Math.round(W*scale), ch = Math.round(H*scale);
    if(canvas.width !== cw)  canvas.width = cw;
    if(canvas.height !== ch) canvas.height = ch;
  }
  applyRatio();

  /* 비율을 바꿔도 글자가 캔버스 안에 남아야 한다.
     좁아지는 쪽에 맞춘다 — 16:9(800×450)에서 정한 크기를 높이만 보고
     9:16(450×800)에 옮기면 1.78배가 되는데 폭은 오히려 반으로 줄어
     글자가 화면 밖으로 나간다. 둘 중 작은 배율을 쓰면 문구가 차지하는
     '폭의 비율'이 그대로 유지된다. */
  function sizePx(){
    return S.size * Math.min(W / (S.baseW || 800), H / (S.baseH || 450));
  }

  /* 그리기에 쓰는 색 묶음. 예전 effect() 자리를 그대로 대신한다. */
  function effect(){
    return {
      color: S.color || '#111111',
      gradient: (S.gradient && S.gradient.length > 1) ? S.gradient : null,
      outline: S.outline || null,
      outlineW: S.outline ? (S.outlineW || 0) : 0,
    };
  }

  function offCanvas(){
    if(!_off) _off = document.createElement('canvas');
    const cw = Math.round(W*scale), ch = Math.round(H*scale);
    if(_off.width!==cw || _off.height!==ch){ _off.width=cw; _off.height=ch; }
    /* 본 캔버스와 같은 배율을 걸어 좌표계를 맞춘다.
       크기 변경 시 transform이 초기화되므로 매번 다시 건다. */
    _off.getContext('2d').setTransform(scale,0,0,scale,0,0);
    return _off;
  }

  function setFont(c){ (c||ctx).font = `${sizePx()}px ${S.fontStack}`; }

  /* ── 글자 배치 ── */
  function layout(){
    setFont();
    const sz = sizePx();
    const lines = String(S.text ?? '').split('\n').slice(0,2).map(x=>x.trim()).filter(Boolean);
    const lh = sz*S.lh, totalH = lh*lines.length;
    const startY = H*S.posY - totalH/2 + lh*0.5;
    return lines.map((line, li)=>{
      const chars=[...line], ws=chars.map(c=>ctx.measureText(c).width);
      const lw = ws.reduce((a,b)=>a+b, 0);
      let x = (W-lw)/2;
      const items = chars.map((ch,i)=>{ const o={ch,x,w:ws[i],y:startY+li*lh}; x+=ws[i]; return o; });
      return {items, width:lw, y:startY+li*lh, x0:(W-lw)/2};
    });
  }

  /* 글자 하나 — 외곽선 먼저, 채우기 나중 */
  function paintChar(o, L, opt, c){
    c = c || ctx;
    const eff = effect(), a = opt.alpha ?? 1;
    if(a <= .003) return;
    c.save();
    c.globalAlpha = a;
    const cx = o.x + o.w/2, cy = o.y;
    c.translate(cx + (opt.dx||0), cy + (opt.dy||0));
    if(opt.rot) c.rotate(opt.rot);
    if(opt.sx!==undefined || opt.sy!==undefined) c.scale(opt.sx ?? 1, opt.sy ?? 1);
    else if(opt.scale) c.scale(opt.scale, opt.scale);
    c.translate(-cx, -cy);
    c.textBaseline = 'middle';
    setFont(c);

    let fill = opt.forceColor || eff.color;
    if(eff.gradient && !opt.forceColor){
      const g = c.createLinearGradient(L.x0, 0, L.x0+L.width, 0);
      eff.gradient.forEach((cc,i)=>g.addColorStop(i/(eff.gradient.length-1), cc));
      fill = g;
    }
    /* 그림자는 쓰지 않는다. 앞 글자에서 남은 설정이 넘어오지 않게 확실히 끈다. */
    c.shadowColor = 'transparent'; c.shadowBlur = 0;
    c.shadowOffsetX = 0; c.shadowOffsetY = 0;

    if(eff.outline && eff.outlineW>0 && !opt.forceColor){
      c.lineJoin='round'; c.strokeStyle=eff.outline; c.lineWidth=eff.outlineW;
      c.strokeText(o.ch, o.x, o.y);
    }
    c.fillStyle = fill;
    c.fillText(o.ch, o.x, o.y);
    c.restore();
  }

  function drawHLBar(L, ratio){
    if(!S.hlOn) return;
    const sz = sizePx();
    ctx.save();
    ctx.fillStyle = S.hl;
    ctx.fillRect(L.x0-10, L.y-sz*0.55, (L.width+20)*cl(ratio), sz*0.95);
    ctx.restore();
  }

  /* ══════════════════════════════════════════════════════════
     애니메이션 18종 — t ∈ [0,1]
  ══════════════════════════════════════════════════════════ */
  function renderText(t){
    const lines = layout();
    if(!lines.length){
      ctx.save();
      ctx.globalAlpha=.45; ctx.fillStyle='#888';
      ctx.font='16px sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText('문구를 입력해주세요', W/2, H/2);
      ctx.textAlign='start';
      ctx.restore();
      return;
    }
    const sz = sizePx();
    const eff = effect();
    const TOTAL = S.total;
    const inRatio = S.inDur / TOTAL;
    const tIn = cl(t / inRatio);
    const all = lines.flatMap(l=>l.items);
    const n = all.length || 1;
    const A = S.anim;
    const lineOf = o => lines.find(l=>l.items.includes(o));

    if(A!=='highlight' && S.hlOn) lines.forEach(L=>drawHLBar(L,1));

    /* 멈춤 — 등장이 다 끝난 상태를 그대로 그린다.
       이 if/else 사슬에는 마지막 else가 없어서, 분기를 안 만들면
       아무것도 안 그려진 빈 화면이 된다. */
    if(A==='none'){
      all.forEach(o=>paintChar(o, lineOf(o), {}));
    }

    else if(A==='typewriter'){
      const shown = Math.floor(tIn*n + 1e-6);
      all.forEach((o,i)=>{ if(i<shown) paintChar(o, lineOf(o), {}); });
      const blink = Math.floor(t*TOTAL*3) % 2 === 0;
      if(blink && shown<=n){
        const o = all[Math.min(shown, n-1)];
        if(o){
          ctx.save(); ctx.fillStyle = eff.color;
          ctx.fillRect((shown>=n ? o.x+o.w : o.x)+3, o.y-sz*.42, Math.max(4, sz*.06), sz*.84);
          ctx.restore();
        }
      }
    }

    else if(A==='pop'){
      const stag=.55, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        paintChar(o, lineOf(o), {alpha:cl(p*1.6), scale:E.outBack(p)});
      });
    }

    else if(A==='wordSwap'){
      const words = String(S.text||'').replace(/\n/g,' ').split(/[\s\/]+/).filter(Boolean);
      if(!words.length){
        lines.forEach(L=>L.items.forEach(o=>paintChar(o,L,{})));
        return;
      }
      const seg = 1/words.length, idx = Math.min(words.length-1, Math.floor(t/seg));
      const local = (t-idx*seg)/seg, w = words[idx];
      setFont();
      const tw = ctx.measureText(w).width;
      const L = {x0:(W-tw)/2, width:tw, y:H*S.posY};
      const a = cl(local*6)*cl((1-local)*6);
      const sc = .88 + .12*E.outExpo(cl(local*3));
      let x = (W-tw)/2;
      [...w].forEach(ch=>{
        const cw = ctx.measureText(ch).width;
        paintChar({ch, x, w:cw, y:H*S.posY}, L, {alpha:a, scale:sc});
        x += cw;
      });
    }

    else if(A==='slideUp'){
      const stag=.5, unit=1-stag;
      lines.forEach((L,li)=>{
        L.items.forEach((o,i)=>{
          const gi = li*.3 + (L.items.length===1?0:(i/(L.items.length-1)))*.7;
          const p = cl((tIn-gi*stag)/unit);
          if(p<=0) return;
          const e = E.outQuint(p);
          paintChar(o, L, {alpha:e, dy:(1-e)*sz*.9});
        });
      });
    }

    else if(A==='highlight'){
      const bar = S.hlOn ? S.hl : '#FDE047';
      /* 글자가 형광 바 위에 얹히므로 색이 바와 너무 비슷하면 통째로 사라진다.
         예전에는 그래서 무조건 #1A1A1A로 덮어썼는데, 그러면 어떤 효과를 골라도
         글자색과 외곽선이 함께 무시됐다(고른 검정도 실제로는 안 쓰였다).
         이제는 바와 대비가 모자랄 때만 바 밝기에 맞춰 바꾼다 — 그 밖에는
         고른 효과를 그대로 쓴다. forceColor는 외곽선까지 끄므로,
         정말 필요할 때만 걸어야 한다. */
      const dim   = Math.abs(lumOf(bar) - lumOf(eff.color)) < 0.35;
      const force = dim ? (lumOf(bar) > 0.5 ? '#1A1A1A' : '#FFFFFF') : null;
      lines.forEach((L,li)=>{
        const d=li*.2, p=cl((tIn-d)/(1-.2));
        if(p<=0) return;
        const barP = E.outCubic(cl(p/.55));
        ctx.save(); ctx.fillStyle = bar;
        ctx.fillRect(L.x0-10, L.y-sz*.55, (L.width+20)*barP, sz*.95);
        ctx.restore();
        const txtP = cl((p-.35)/.5);
        if(txtP>0) L.items.forEach(o=>{
          const rev = cl((barP*(L.width+20) - (o.x-L.x0+10)) / Math.max(o.w,1));
          paintChar(o, L, {alpha:Math.min(txtP,rev), forceColor:force});
        });
      });
    }

    else if(A==='zoomIn'){
      const p = E.outQuint(tIn), sc = 1.8 - .8*p;
      ctx.save();
      ctx.globalAlpha = cl(tIn*2.5);
      ctx.translate(W/2, H*S.posY); ctx.scale(sc,sc); ctx.translate(-W/2, -H*S.posY);
      all.forEach(o=>paintChar(o, lineOf(o), {}));
      ctx.restore();
    }

    else if(A==='wipe'){
      const p = E.outCubic(tIn);
      lines.forEach(L=>{
        ctx.save();
        ctx.beginPath();
        ctx.rect(L.x0-20, L.y-sz, (L.width+40)*p, sz*2);
        ctx.clip();
        L.items.forEach(o=>paintChar(o,L,{}));
        ctx.restore();
      });
    }

    else if(A==='bounceDrop'){
      const stag=.5, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        const e = E.outBounce(p);
        paintChar(o, lineOf(o), {alpha:cl(p*4), dy:-(1-e)*H*.5});
      });
    }

    else if(A==='neonFlicker'){
      /* 깜빡임 3회 후 안정 */
      let on = true;
      if(tIn<1){
        const f = tIn*7;
        on = (f<1)?false : (f<1.6)?true : (f<2.1)?false : (f<3)?true : (f<3.4)?false : true;
      }
      const a = on ? 1 : 0.12;
      all.forEach(o=>paintChar(o, lineOf(o), {alpha:a}));
    }

    /* ── 시네마틱 ① 트래킹 인 ──
       영화 타이틀 기법. 자간이 넓게 벌어진 상태에서 좁혀지며 선명해지고,
       정착 후 위아래 룰이 그어진 뒤 아주 느리게 드리프트한다. */
    else if(A==='cinematicTrack'){
      const P1 = S.inDur/TOTAL;
      const P2 = Math.min(P1+0.14, 0.95);
      const p1 = cl(t/P1);
      const e  = E.outExpo(p1);
      const extra = (1-e) * sz * 0.60;
      const drift = t>P2 ? (t-P2)/(1-P2) * 0.025 : 0;
      const gScale = 1.07 - 0.07*e + drift;
      const alpha  = cl(p1*1.25);

      ctx.save();
      ctx.translate(W/2, H*S.posY);
      ctx.scale(gScale, gScale);
      ctx.translate(-W/2, -H*S.posY);

      lines.forEach(L=>{
        const totalW = L.width + extra*Math.max(0, L.items.length-1);
        const x0 = (W-totalW)/2;
        let x = x0;
        const VL = {x0, width:totalW, y:L.y};
        L.items.forEach(o=>{
          paintChar({ch:o.ch, x, w:o.w, y:o.y}, VL, {alpha});
          x += o.w + extra;
        });
      });

      if(t>P1){
        const rp = E.outCubic(cl((t-P1)/(P2-P1)));
        const first = lines[0], last = lines[lines.length-1];
        const rw = Math.min(W*0.42, 300) * rp;
        const th = Math.max(1.5, sz*0.028);
        ctx.save();
        ctx.globalAlpha = alpha*0.8;
        ctx.fillStyle = eff.gradient ? eff.gradient[0] : eff.color;
        ctx.fillRect(W/2-rw/2, first.y - sz*0.92, rw, th);
        ctx.fillRect(W/2-rw/2, last.y  + sz*0.72, rw, th);
        ctx.restore();
      }
      ctx.restore();
    }

    /* ── 시네마틱 ② 골드 스윕 ──
       가로 슬릿이 열리며 글자가 드러나고, 정착 후 사선 광택이 한 번 지나간다. */
    else if(A==='shineSweep'){
      const T1=0.16, T2=0.36, T3=0.62, T4=0.86;
      const off = offCanvas(), octx = off.getContext('2d');
      octx.clearRect(0,0,W,H);

      const sc = 1.05 - 0.05*E.outCubic(cl(t/T3));
      octx.save();
      octx.translate(W/2, H*S.posY);
      octx.scale(sc, sc);
      octx.translate(-W/2, -H*S.posY);
      lines.forEach(L=>L.items.forEach(o=>paintChar(o, L, {alpha:cl((t-T1)/(T2-T1))*1.4}, octx)));
      octx.restore();

      /* 광택은 글자 픽셀 위에만 얹는다 (source-atop) */
      if(t>T3 && t<=T4+0.06){
        const sp = cl((t-T3)/(T4-T3));
        const band = W*0.30;
        const cx = -band + (W+band*2)*E.outCubic(sp);
        const g = octx.createLinearGradient(cx-band/2, 0, cx+band/2, H);
        g.addColorStop(0,   'rgba(255,255,255,0)');
        g.addColorStop(0.5, 'rgba(255,255,255,.85)');
        g.addColorStop(1,   'rgba(255,255,255,0)');
        octx.save();
        octx.globalCompositeOperation='source-atop';
        octx.fillStyle=g;
        octx.fillRect(0,0,W,H);
        octx.restore();
      }

      /* 슬릿 높이는 실제 줄 배치에서 계산한다.
         고정값을 쓰면 2줄 + 넓은 줄간격에서 글자가 잘린다. */
      const padV = (eff.outlineW||0) + 10;
      const topY = lines[0].y - sz*0.72 - padV;
      const botY = lines[lines.length-1].y + sz*0.72 + padV;
      const fullH = Math.max(4, botY - topY);
      const cyy = (topY + botY) / 2;
      const bandH = (t<T2)
        ? Math.max(2, 2 + (fullH-2)*E.outCubic(cl((t-T1)/(T2-T1))))
        : fullH;
      const bandW = (t<T1) ? W*E.outCubic(cl(t/T1)) : W;

      ctx.save();
      ctx.beginPath();
      ctx.rect((W-bandW)/2, cyy-bandH/2, bandW, bandH);
      ctx.clip();
      /* 목적지 크기를 논리 좌표로 명시한다 — off는 실제 픽셀 크기라
         인자 두 개짜리 drawImage를 쓰면 축소 렌더에서 크기가 어긋난다 */
      ctx.drawImage(off, 0, 0, W, H);
      ctx.restore();

      if(t<T2){
        ctx.save();
        ctx.globalAlpha = 1-cl((t-T1)/(T2-T1));
        ctx.fillStyle = eff.gradient ? eff.gradient[0] : eff.color;
        ctx.fillRect((W-bandW)/2, cyy-1, bandW, 2);
        ctx.restore();
      }
    }

    /* ⚡ 슬램 임팩트 — 거대한 글자가 내리꽂히고 화면이 흔들린다 */
    else if(A==='slamImpact'){
      const stag=.45, unit=1-stag;
      let shakeX=0, shakeY=0;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag;
        const since = tIn - (d+unit*0.55);
        if(since>=0 && since<0.12){
          const decay = 1 - since/0.12;
          shakeX += Math.sin(since*180)*sz*0.10*decay;
          shakeY += Math.cos(since*150)*sz*0.07*decay;
        }
      });
      ctx.save();
      ctx.translate(shakeX, shakeY);
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag;
        const p=cl((tIn-d)/unit);
        if(p<=0) return;
        const e = E.outQuint(p);
        paintChar(o, lineOf(o), {alpha:cl(p*3), scale:2.6-1.6*e, dy:-(1-E.inCubic(p))*sz*0.5});
      });
      ctx.restore();
    }

    /* ⚡ 스핀 인 — 회전하며 날아와 정지 */
    else if(A==='spinIn'){
      const stag=.5, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        const e = E.outQuint(p), dir = (i%2===0)?1:-1;
        paintChar(o, lineOf(o), {
          alpha:cl(p*2.5), rot:(1-e)*Math.PI*1.15*dir,
          scale:0.25+0.75*e, dy:(1-e)*sz*0.35*dir,
        });
      });
    }

    /* ⚡ 고무줄 — 납작하게 눌렸다가 탄성으로 튀어오름 */
    else if(A==='elasticStretch'){
      const stag=.42, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        const over = E.outElastic(p) - 1;
        paintChar(o, lineOf(o), {
          alpha:cl(p*4),
          sx:Math.max(.05, 1+over*0.55),
          sy:Math.max(.05, 1-over*0.45),
        });
      });
    }

    /* ⚡ 셔플 — 흩어진 글자가 제자리를 찾아 들어감 */
    else if(A==='shuffleIn'){
      const stag=.4, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        const e = E.outQuint(p);
        /* 인덱스 기반 의사난수 — 매번 같은 자리에서 출발해야 GIF가 재현된다 */
        const r1 = Math.sin(i*12.9898)*43758.5453;
        const r2 = Math.sin(i*78.233)*43758.5453;
        const ox = ((r1-Math.floor(r1))-0.5)*W*0.7;
        const oy = ((r2-Math.floor(r2))-0.5)*H*0.6;
        paintChar(o, lineOf(o), {
          alpha:cl(p*2), dx:(1-e)*ox, dy:(1-e)*oy,
          rot:(1-e)*((r1-Math.floor(r1))-0.5)*1.6, scale:0.4+0.6*e,
        });
      });
    }

    /* ⚡ 킥업 — 아래에서 차올라 살짝 넘어갔다 제자리 */
    else if(A==='kickUp'){
      const stag=.5, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        const e = E.outBack2(p);
        paintChar(o, lineOf(o), {
          alpha:cl(p*3), dy:(1-e)*sz*1.4, rot:(1-e)*0.42,
          scale:0.7+0.3*Math.min(e,1.2),
        });
      });
    }

    /* ⚡ 롤인 — 왼쪽에서 굴러 들어와 멈춤 */
    else if(A==='rollIn'){
      const stag=.5, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        const dist = (1-E.outQuint(p))*W*0.55;
        paintChar(o, lineOf(o), {
          alpha:cl(p*2.5), dx:-dist,
          rot:-dist/(sz*0.5),            // 이동거리에 비례해 구른다
        });
      });
    }

    else if(A==='flip'){
      const stag=.5, unit=1-stag;
      all.forEach((o,i)=>{
        const d=(n===1)?0:(i/(n-1))*stag, p=cl((tIn-d)/unit);
        if(p<=0) return;
        paintChar(o, lineOf(o), {alpha:cl(p*3), sx:E.outCubic(p), sy:1});
      });
    }
  }

  /* ── 배경 ──
     투명 배경은 캔버스를 비워두고 CSS 체커보드가 뒤에서 비치게 한다.
     캔버스에 직접 체커를 그리면 (1) 미리보기와 내보낸 파일이 달라지고
     (2) 색이 고정이라 밝은 테마에서 어두운 격자가 튄다. */

  /* 사진 한 장을 cover 크롭으로 채운다. 켄번스(확대)를 넣지 않는다:
     배경이 움직이면 GIF가 매 프레임을 통째로 다시 저장해 용량이 몇 배가 된다. */
  function drawPhotoCover(im, alpha){
    if(!im) return;
    const sc = Math.max(W/im.width, H/im.height);
    const dw = im.width*sc, dh = im.height*sc;
    const dx = (W-dw)/2 + (S.photoX/100)*(dw-W)/2;
    const dy = (H-dh)/2 + (S.photoY/100)*(dh-H)/2;
    const a = (alpha === undefined) ? 1 : alpha;
    if(a >= 1){ ctx.drawImage(im, dx, dy, dw, dh); return; }
    ctx.save();
    ctx.globalAlpha = a;
    ctx.drawImage(im, dx, dy, dw, dh);
    ctx.restore();
  }

  /* 어둡게(dim)는 사진을 다 깔고 난 뒤 한 번만 덮는다.
     장마다 덮으면 크로스페이드 구간에서 두 번 겹쳐 그 순간만 확 어두워진다. */
  function drawDim(amount){
    if(!(amount > 0)) return;
    ctx.save();
    ctx.fillStyle = `rgba(0,0,0,${amount/100})`;
    ctx.fillRect(0,0,W,H);
    ctx.restore();
  }

  function drawPhoto(){
    drawPhotoCover(S.photo, 1);
    drawDim(S.dim);
  }

  /* 슬라이드쇼 — t는 전체 타임라인의 0..1 진행도다(render 주석 참고).
     장마다 같은 길이의 구간을 갖고, 구간 뒷부분에서 다음 장이 겹쳐 올라온다.
     마지막 장의 다음은 첫 장이라 반복 재생에서 이음매가 없다. */
  function drawSlideshow(t){
    const ph = S.photos || [];
    const n = ph.length;
    if(!n) return;

    const pos = cl(t) * n;                       // 0..n
    const i = Math.min(n-1, Math.floor(pos));
    const local = pos - i;                       // 이 장 구간 안에서의 0..1

    /* 구간 중 '그대로 보여주는' 비율. 나머지가 넘어가는 구간이다. */
    const seg = Math.max(0.2, S.slideDur) + Math.max(0, S.xfadeDur);
    const hold = Math.max(0.2, S.slideDur) / seg;

    drawPhotoCover(ph[i], 1);
    if(n > 1 && S.xfadeDur > 0 && local > hold){
      drawPhotoCover(ph[(i+1)%n], cl((local - hold) / (1 - hold)));
    }
    drawDim(S.slideDim);
  }

  function photoModeActive(){
    return S.mode === 'photo' && (S.photos||[]).length > 0;
  }
  function videoModeActive(){
    return S.mode === 'video' && !!S.video;
  }
  /* 지금 모드에서 글자를 그리는가. 글자 모드는 글자가 본체라 항상 참이다. */
  function textEnabled(){
    if(S.mode === 'photo') return !!S.photoTextOn;
    if(S.mode === 'video') return !!S.videoTextOn;
    return true;
  }

  /* 영상 한 프레임 — 지금 video 요소에 떠 있는 그림을 그대로 그린다.
     여기서 seek을 걸지 않는다: render는 동기 함수인데 seek은 비동기라
     기다릴 수 없고, 미리보기에서는 영상이 재생되며 알아서 넘어간다.
     내보낼 때의 정확한 위치 맞추기는 prepareFrame()이 맡는다. */
  function drawVideoFrame(){
    const v = S.video;
    if(!v || !v.videoWidth) return;
    const sc = Math.max(W/v.videoWidth, H/v.videoHeight);
    const dw = v.videoWidth*sc, dh = v.videoHeight*sc;
    const dx = (W-dw)/2 + (S.photoX/100)*(dw-W)/2;
    const dy = (H-dh)/2 + (S.photoY/100)*(dh-H)/2;
    try{ ctx.drawImage(v, dx, dy, dw, dh); }catch(e){ /* 아직 첫 프레임이 없으면 건너뛴다 */ }
    drawDim(S.slideDim);
  }

  /* 내보내기가 프레임을 그리기 직전에 부른다. 영상만 실제로 할 일이 있다.
     t는 0..1 진행도 — 잘라낸 구간 안의 위치로 환산해 그 지점으로 찾아간다.
     seek 한 번이 40~90ms라 90프레임이면 4초쯤 든다 (인코딩이 훨씬 오래 걸린다). */
  async function prepareFrame(t){
    if(!videoModeActive()) return;
    const v = S.video;
    const target = S.trimStart + cl(t) * trimSpan(S);
    /* 끝 프레임에서 duration을 넘기면 seeked가 오지 않고 멈춘다 */
    const safe = Math.max(0, Math.min((S.videoDur || v.duration || 0) - 0.02, target));
    if(Math.abs(v.currentTime - safe) < 0.001) return;
    await new Promise(resolve => {
      let done = false;
      const fin = ()=>{ if(done) return; done = true; v.removeEventListener('seeked', fin); resolve(); };
      v.addEventListener('seeked', fin);
      /* seek이 오지 않는 경우(코덱·구간 문제)에도 내보내기가 멈추면 안 된다.
         그 프레임은 직전 그림으로 나가지만, 통째로 실패하는 것보다 낫다. */
      setTimeout(fin, 400);
      v.currentTime = safe;
    });
  }

  /* 실측값이 지금 화면과 같은 조건에서 나온 것인지 가리는 열쇠.
     한 프레임의 그림을 바꾸는 것만 넣는다 — 프레임 수(fps·장당 시간)는
     넣지 않는다. 용량이 프레임 수에 정비례하므로 곱하기만 하면 되고,
     슬라이더를 움직일 때마다 다시 인코딩하면 편집이 버벅인다. */
  function sampleKey(){
    return [
      S.mode,
      (S.photos||[]).length, S.photosRev|0, S.ratio, S.slideDim,
      S.videoRev|0, (S.trimStart||0).toFixed(2),
      /* 글자 모드의 배경 사진 — 그림을 바꾸는 값은 사진 자체(bgPhotoRev),
         잘려나가는 위치(X·Y), 어둡게(dim), 그리고 사진이 없을 때의 단색 배경이다. */
      S.photo ? `bg${S.bgPhotoRev|0},${S.photoX},${S.photoY},${S.dim}` : (S.bgColor || 'nobg'),
      textEnabled() ? [S.text, S.fontStack, S.fontWeight, S.size, S.lh, S.posY,
                  S.color, S.gradient&&S.gradient.join(''), S.outline, S.outlineW,
                  S.anim, S.hlOn?S.hl:''].join(',') : 'notext',
    ].join('~');
  }

  /* 한 프레임. 미리보기와 내보내기가 완전히 같은 그림을 만든다.
     t는 초가 아니라 전체 타임라인의 진행도(0..1)다 — 내보내기가 i/총프레임을
     넘긴다. 초가 필요하면 t*S.total로 환산한다. */
  function render(t){
    applyRatio();
    try{
      ctx.setTransform(scale,0,0,scale,0,0);
      ctx.globalAlpha = 1;
      ctx.clearRect(0,0,W,H);
      const tn = cl(Number.isFinite(t) ? t : 0);
      if(S.mode === 'video'){
        if(videoModeActive()) drawVideoFrame();
        else if(S.bgColor){ ctx.fillStyle = S.bgColor; ctx.fillRect(0,0,W,H); }
        if(textEnabled()) renderText(tn);
      }else if(S.mode === 'photo'){
        if(photoModeActive()) drawSlideshow(tn);
        else if(S.bgColor){ ctx.fillStyle = S.bgColor; ctx.fillRect(0,0,W,H); }
        if(textEnabled()) renderText(tn);
      }else{
        if(S.photo) drawPhoto();
        else if(S.bgColor){ ctx.fillStyle = S.bgColor; ctx.fillRect(0,0,W,H); }
        renderText(tn);
      }
    }catch(err){
      /* 프레임 하나가 실패해도 루프는 멈추지 않는다 */
      try{ ctx.setTransform(scale,0,0,scale,0,0); ctx.globalAlpha=1; }catch(e){}
      if(!render._warned){ render._warned = true; console.error('[gif-render]', err); }
    }
  }

  /* ── 상태 조작 ── */
  function setState(patch){
    Object.assign(S, patch||{});
    /* 사진 모드의 전체 길이는 사용자가 정하는 값이 아니라
       (장수 × 장당 시간)의 결과다. 손으로 넣은 total은 무시한다. */
    if(S.mode === 'photo') S.total = slideshowTotal(S);
    if(S.mode === 'video') S.total = trimSpan(S);
    applyRatio();
    return api;
  }

  /* 모드 전환. 폰트·색·비율은 그대로 두고 시간 설정만 그 모드에 맞게 바꾼다.
     사진 모드는 장수에서 길이가 나오고, 글자 모드는 애니메이션에서 나온다. */
  function setMode(mode){
    const prev = S.mode;
    S.mode = (mode === 'photo' || mode === 'video') ? mode : 'text';
    if(S.mode === 'video'){
      /* 다른 모드에서 넘어오면 fps를 영상 기본값으로 잡는다. 사진 모드의
         10fps를 그대로 들고 오면 영상이 이유 없이 끊겨 보인다.
         영상 모드 안에서 이미 조절한 값은 건드리지 않는다. */
      if(prev !== 'video') S.fps = VIDEO_DEFAULTS.fps;
      S.total = trimSpan(S);
      S.inDur = Math.min(S.inDur, Math.max(0.4, S.total * 0.3));
      applyRatio();
      return api;
    }
    if(S.mode === 'photo'){
      /* 글자 모드의 20~24fps를 그대로 들고 오면 8장짜리가 300프레임이 된다. */
      if(S.fps > 15) S.fps = PHOTO_DEFAULTS.fps;
      S.total = slideshowTotal(S);
      /* 사진 위 글자는 등장만 하고 머문다. 전체 길이가 길어졌으니
         등장 시간이 그대로면 첫 장이 끝나기도 전에 다 나와버린다. */
      S.inDur = Math.min(S.inDur, Math.max(0.6, S.total * 0.25));
    }else{
      const d = animDefaults(S.anim);
      S.total = d.total; S.fps = d.fps; S.inDur = d.inDur;
    }
    applyRatio();
    return api;
  }

  /* 애니메이션을 바꾸면 권장 길이·fps를 함께 적용한다.
     시네마틱을 2.5초로 돌리면 광택이 시작되기도 전에 끝난다.
     단 사진 모드에서는 길이·fps가 사진 쪽 설정이라 건드리지 않는다. */
  function setAnim(id){
    S.anim = id;
    const d = animDefaults(id);
    if(S.mode === 'photo'){
      S.inDur = Math.min(d.inDur, Math.max(0.6, S.total * 0.25));
      return api;
    }
    S.total = d.total; S.fps = d.fps; S.inDur = d.inDur;
    return api;
  }

  function frameCount(){
    /* 멈춤은 모든 프레임이 똑같다 — 장수를 늘려도 같은 그림을 더 저장할 뿐이라
       용량만 그만큼 커진다. 글자 모드에서는 GIF가 요구하는 최소 장수로 고정한다.
       사진·영상 모드는 배경이 계속 바뀌므로 손대지 않는다. */
    if(S.anim === 'none' && S.mode === 'text') return 2;
    let n = Math.round(S.total * S.fps);
    return Math.max(2, Math.min(MAX_FRAMES, n));
  }

  /* 예상 용량.
     계수 6은 템플릿 8종을 실제로 인코딩해 맞춘 값이다 — 프레임·면적으로
     정규화했을 때 4.6~8.2KB로 흩어져서, 가운데인 6을 쓰고 폭을 넓게 잡는다.
     하나의 숫자로 "480KB"라고 적으면 실제가 1.4MB로 나왔을 때 사용자가
     바로 알아채므로, 반드시 범위로 보여줄 것. */
  function estimate(){
    const n = frameCount();
    const px = W*H/(800*450);
    const rating = inkRating(effect());
    const colorFactor = [1.9, 1.45, 1.15, 1.0][rating] ?? 1.2;
    const photoish = !!S.photo || photoModeActive();

    /* 사진이 깔린 GIF는 추정하지 않고 실측값을 쓴다.
       프레임당 크기가 사진에 따라 50KB~309KB로 6배까지 벌어져서, 어떤 상수를
       넣어도 절반은 틀린다. 대신 용량이 프레임 수에 정확히 비례하므로
       (실측: 4·8·16프레임에서 프레임당 50.5KB로 완전히 일정)
       한 장을 실제로 인코딩해 재고 프레임 수만 곱한다.

       글자 모드의 '배경 사진 한 장'도 같은 처지다 — 옛 추정식
       (110 + (n-1)×22)은 뒷 프레임이 싸다는 전제인데, 이 인코더는 프레임마다
       팔레트를 새로 뜨고 화면을 통째로 다시 쓴다. 그래서 실제의 절반쯤으로
       나왔다. 사진 모드와 같은 방식으로 재게 한다. */
    const sample = S.photoSample;
    if((photoish || videoModeActive()) && sample && sample.key === sampleKey()){
      const gifKB = Math.round(sample.bytes * n / 1024);
      /* 한 장을 따로 잴 때보다 연속으로 돌릴 때가 프레임당 두 배쯤 느리다.
         실측 비율 16프레임 2.12배 · 32프레임 1.83배 — 가운데인 2를 쓴다.
         이 값은 '30초 넘으면 경고' 판단에만 쓰이므로, 모자라게 잡아
         경고를 놓치는 것보다 넉넉히 잡는 편이 낫다. */
      const encodeMs = Math.round(sample.ms * n * 2);
      return {
        frames:n, w:W, h:H, gifKB,
        mp4KB: Math.round(S.total * 900 * px),
        /* 실측이라 폭을 좁게 잡는다. 남은 오차는 장마다 그림이 달라서 생기는
           것뿐이다 (표본은 한 장) — 사진 A/B로 잰 편차가 ±10% 안쪽이었다.
           영상은 프레임마다 그림이 다 달라서 표본 한 장의 대표성이 떨어지므로
           폭을 더 넓게 준다. */
        gifKBLow: Math.round(gifKB * (videoModeActive() ? 0.75 : 0.9)),
        gifKBHigh: Math.round(gifKB * (videoModeActive() ? 1.4 : 1.15)),
        heavy: gifKB > 2000,
        measured: true, encodeMs, slow: encodeMs > 30000,
      };
    }

    const gifKB = photoish
      ? Math.round((110 + (n-1)*22) * px * colorFactor)
      : Math.round(n * 6 * px * colorFactor);
    const mp4KB = Math.round(S.total * (photoish?900:450) * px);
    return {
      frames:n, w:W, h:H, gifKB, mp4KB,
      gifKBLow: Math.round(gifKB*0.75), gifKBHigh: Math.round(gifKB*1.4),
      heavy: gifKB*1.4 > 2000,
      measured: false, encodeMs: 0, slow: false,
    };
  }

  /* 매트(경계 보정) 색 — 외곽선이 있으면 그 색, 없으면 글자색.
     ffpAutoMatte 대신 여기서 정하는 이유: 그림자가 사라져 규칙이 단순해졌다. */
  function autoMatte(){
    const e = effect();
    if(e.outline && e.outlineW > 0) return e.outline;
    if(e.gradient) return e.gradient[Math.floor(e.gradient.length/2)];
    return e.color;
  }
  function currentMatte(){ return S.matteAuto ? autoMatte() : S.matte; }

  /* 배경이 불투명한가. 불투명하면 GIF에 투명 처리도 매트도 필요 없다.
     사진 모드는 사진이 화면을 꽉 채우므로(cover) 사진이 한 장이라도 있으면 불투명이다. */
  function isOpaque(){
    if(S.mode === 'photo') return photoModeActive() || !!S.bgColor;
    if(S.mode === 'video') return videoModeActive() || !!S.bgColor;
    return !!(S.photo || S.bgColor);
  }

  /* 내보내기가 팔레트 크기를 정할 때 쓴다 — 사진이 깔리면 64색으로는
     하늘·피부 같은 완만한 그러데이션이 띠로 뭉개진다. */
  function needsRichPalette(){ return !!S.photo || photoModeActive() || videoModeActive(); }

  /* 폰트가 실제로 준비될 때까지 기다린다.
     내보내기 직전에 반드시 부를 것 — 안 그러면 50프레임이 통째로
     대체 폰트로 저장된다. */
  async function ensureFont(font){
    if(font){
      S.fontId = font.id;
      S.fontStack = ffpEffectiveStack(font, S.fontWeight);
    }
    if(!font || !S.fontId) return false;
    return ffpEnsureFontReady(font, S.fontWeight, sizePx());
  }

  /* ── 템플릿 직렬화 ── */
  function snapshot(){
    return {
      sampleText: S.text,
      canvas: {w:W, h:H, ratio:S.ratio},
      font: {id:S.fontId, weight:S.fontWeight, size:S.size, baseW:S.baseW, baseH:S.baseH, lineHeight:S.lh},
      /* 색은 이름표(effect:'classic-black')가 아니라 값으로 저장한다.
         이름표로 두면 나중에 프리셋 표를 손볼 때 이미 저장된 템플릿의
         색이 조용히 따라 바뀐다. */
      ink: {color:S.color, gradient:S.gradient, outline:S.outline, outlineW:S.outlineW},
      /* 길이·fps는 글자 모드 값으로만 저장한다.
         사진·영상 모드의 값(사진 10fps·4초 등)은 그 모드의 사진 장수와 자른
         구간에서 나온 것이라 글자 GIF에는 뜻이 없다. 그대로 저장하면 임시저장을
         복원할 때 글자 GIF가 10fps·4초로 시작해 애니메이션이 뚝뚝 끊긴다.
         (실제로 그 증상이 나왔다 — 사진 모드에서 저장된 draft가 글자 모드로 복원됐다.) */
      animation: S.mode === 'text'
        ? {type:S.anim, inDuration:S.inDur, total:S.total, fps:S.fps}
        : (d => ({type:S.anim, inDuration:d.inDur, total:d.total, fps:d.fps}))(animDefaults(S.anim)),
      bg: S.photo ? 'photo' : (S.bgColor ? 'color' : null),
      bgColor: S.bgColor,
      photo: S.photo ? {x:S.photoX, y:S.photoY, dim:S.dim} : null,
      matteAuto: S.matteAuto,
      matte: currentMatte(),
      highlight: S.hlOn ? S.hl : null,
      layout: {posY:S.posY},
    };
  }

  /* 템플릿 적용. 사진은 config에 담기지 않으므로(용량) 위치값만 복원한다.
     모드는 바꾸지 않는다 — 사진·영상 위에 템플릿의 글자 꾸밈만 얹는다.
     그 모드에서 넘겨받으면 안 되는 것 세 가지는 건너뛴다:
       · 길이·fps  — 사진 장수와 자른 구간에서 나온 값이 이긴다
       · 배경      — 사진·영상이 곧 배경이다
       · 비율      — 올린 사진·영상에 맞춰둔 것을 템플릿이 되돌리면 안 된다 */
  function applyConfig(cfg){
    if(!cfg) return api;
    const textMode = S.mode === 'text';
    const f = cfg.font || {}, an = cfg.animation || {}, cv = cfg.canvas || {};
    if(cfg.sampleText !== undefined) S.text = cfg.sampleText;
    if(textMode && cv.ratio && RATIOS[cv.ratio]) S.ratio = cv.ratio;
    if(f.id !== undefined) S.fontId = f.id;
    if(f.weight) S.fontWeight = f.weight;
    if(f.size) S.size = f.size;
    S.baseW = f.baseW || cv.w || RATIOS[S.ratio].w;
    S.baseH = f.baseH || cv.h || RATIOS[S.ratio].h;
    if(f.lineHeight) S.lh = f.lineHeight;
    /* 색 — 새 형식(ink)이 있으면 그걸 쓰고, 없으면 옛 effect 이름표에서 옮긴다.
       템플릿 50종의 config에는 아직 effect:'classic-black' 같은 값만 들어 있다. */
    const ink = cfg.ink || (cfg.effect ? inkFromEffectId(cfg.effect) : null);
    if(ink){
      if(ink.color) S.color = ink.color;
      S.gradient = (ink.gradient && ink.gradient.length > 1) ? ink.gradient.slice() : null;
      S.outline  = ink.outline || null;
      S.outlineW = S.outline ? (ink.outlineW ?? 6) : 0;
    }
    if(an.type) S.anim = an.type;
    if(an.inDuration) S.inDur = an.inDuration;
    if(textMode){
      if(an.total) S.total = an.total;
      if(an.fps) S.fps = an.fps;
      S.bgColor = cfg.bg === 'color' ? (cfg.bgColor || '#1E3A8A') : null;
      if(cfg.photo){ S.photoX = cfg.photo.x ?? 0; S.photoY = cfg.photo.y ?? 0; S.dim = cfg.photo.dim ?? 35; }
    }else{
      /* 사진·영상 위에서는 등장 시간이 전체 길이를 넘지 않게만 조인다.
         템플릿의 1.5초는 2.5초짜리 글자 GIF 기준이라, 3초 영상에는 맞지만
         사진 8장(12.8초)에서는 첫 장이 끝나기도 전에 다 나와버린다. */
      S.inDur = Math.min(S.inDur, Math.max(0.4, S.total * 0.3));
      S.total = S.mode === 'photo' ? slideshowTotal(S) : trimSpan(S);
    }
    S.matteAuto = cfg.matteAuto !== false;
    if(cfg.matte) S.matte = cfg.matte;
    S.hlOn = !!cfg.highlight;
    if(cfg.highlight) S.hl = cfg.highlight;
    if(cfg.layout && cfg.layout.posY !== undefined) S.posY = cfg.layout.posY;
    applyRatio();
    return api;
  }

  const api = {
    state: S,
    canvas,
    scale,
    get width(){ return W; },
    get height(){ return H; },
    render, setState, setAnim, setMode, applyConfig, snapshot, prepareFrame,
    frameCount, estimate, ensureFont, currentMatte, isOpaque, needsRichPalette,
    sizePx, effect, autoMatte, sampleKey, textEnabled,
  };
  return api;
}

global.FFPGif = {
  RATIOS, ANIMS, ANIM_BY_ID, ANIM_DEFAULTS, animDefaults,
  HL_PRESETS, MAX_FRAMES, MAX_PHOTOS, PHOTO_DEFAULTS, slideshowTotal,
  VIDEO_MAX_SEC, VIDEO_DEFAULT_SEC, VIDEO_DEFAULTS, trimSpan,
  defaultState, createRenderer, easing:E, clamp:cl,
  INK_SWATCHES, INK_GRADIENTS, inkFromEffectId, inkRating,
};

})(window);
