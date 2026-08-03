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
    effect: 'bold-outline',
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
    ratio: '16:9',
  };
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

  function effect(){ return FFP_EFFECT_BY_ID[S.effect] || FFP_EFFECTS[0]; }

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
    ffpApplyShadow(c, eff, eff.gradient ? eff.gradient[0] : eff.color);

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

    if(A==='typewriter'){
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
      lines.forEach((L,li)=>{
        const d=li*.2, p=cl((tIn-d)/(1-.2));
        if(p<=0) return;
        const barP = E.outCubic(cl(p/.55));
        ctx.save(); ctx.fillStyle = S.hlOn ? S.hl : '#FDE047';
        ctx.fillRect(L.x0-10, L.y-sz*.55, (L.width+20)*barP, sz*.95);
        ctx.restore();
        const txtP = cl((p-.35)/.5);
        if(txtP>0) L.items.forEach(o=>{
          const rev = cl((barP*(L.width+20) - (o.x-L.x0+10)) / Math.max(o.w,1));
          paintChar(o, L, {alpha:Math.min(txtP,rev), forceColor:'#1A1A1A'});
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
      const padV = (eff.outlineW||0) + (eff.shadow==='glow' ? 28 : 10);
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

  /* 사진 — cover 크롭. 켄번스(확대)를 넣지 않는다: 배경이 움직이면
     GIF가 매 프레임을 통째로 다시 저장해 용량이 몇 배가 된다. */
  function drawPhoto(){
    const im = S.photo;
    const scale = Math.max(W/im.width, H/im.height);
    const dw = im.width*scale, dh = im.height*scale;
    const dx = (W-dw)/2 + (S.photoX/100)*(dw-W)/2;
    const dy = (H-dh)/2 + (S.photoY/100)*(dh-H)/2;
    ctx.drawImage(im, dx, dy, dw, dh);
    if(S.dim>0){
      ctx.save();
      ctx.fillStyle = `rgba(0,0,0,${S.dim/100})`;
      ctx.fillRect(0,0,W,H);
      ctx.restore();
    }
  }

  /* 한 프레임. 미리보기와 내보내기가 완전히 같은 그림을 만든다. */
  function render(t){
    applyRatio();
    try{
      ctx.setTransform(scale,0,0,scale,0,0);
      ctx.globalAlpha = 1;
      ctx.clearRect(0,0,W,H);
      if(S.photo) drawPhoto();
      renderText(cl(Number.isFinite(t) ? t : 0));
    }catch(err){
      /* 프레임 하나가 실패해도 루프는 멈추지 않는다 */
      try{ ctx.setTransform(scale,0,0,scale,0,0); ctx.globalAlpha=1; }catch(e){}
      if(!render._warned){ render._warned = true; console.error('[gif-render]', err); }
    }
  }

  /* ── 상태 조작 ── */
  function setState(patch){
    Object.assign(S, patch||{});
    applyRatio();
    return api;
  }

  /* 애니메이션을 바꾸면 권장 길이·fps를 함께 적용한다.
     시네마틱을 2.5초로 돌리면 광택이 시작되기도 전에 끝난다. */
  function setAnim(id){
    S.anim = id;
    const d = animDefaults(id);
    S.total = d.total; S.fps = d.fps; S.inDur = d.inDur;
    return api;
  }

  function frameCount(){
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
    const rating = FFP_GIF_RATING[S.effect] ?? 2;
    const colorFactor = [1.9, 1.45, 1.15, 1.0][rating] ?? 1.2;
    const gifKB = S.photo
      ? Math.round((110 + (n-1)*22) * px * colorFactor)
      : Math.round(n * 6 * px * colorFactor);
    const mp4KB = Math.round(S.total * (S.photo?900:450) * px);
    return {
      frames:n, w:W, h:H, gifKB, mp4KB,
      gifKBLow: Math.round(gifKB*0.75), gifKBHigh: Math.round(gifKB*1.4),
      heavy: gifKB*1.4 > 2000,
    };
  }

  function currentMatte(){ return S.matteAuto ? ffpAutoMatte(effect()) : S.matte; }

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
      effect: S.effect,
      animation: {type:S.anim, inDuration:S.inDur, total:S.total, fps:S.fps},
      bg: S.photo ? 'photo' : null,
      photo: S.photo ? {x:S.photoX, y:S.photoY, dim:S.dim} : null,
      matteAuto: S.matteAuto,
      matte: currentMatte(),
      highlight: S.hlOn ? S.hl : null,
      layout: {posY:S.posY},
    };
  }

  /* 템플릿 적용. 사진은 config에 담기지 않으므로(용량) 위치값만 복원한다. */
  function applyConfig(cfg){
    if(!cfg) return api;
    const f = cfg.font || {}, an = cfg.animation || {}, cv = cfg.canvas || {};
    if(cfg.sampleText !== undefined) S.text = cfg.sampleText;
    if(cv.ratio && RATIOS[cv.ratio]) S.ratio = cv.ratio;
    if(f.id !== undefined) S.fontId = f.id;
    if(f.weight) S.fontWeight = f.weight;
    if(f.size) S.size = f.size;
    S.baseW = f.baseW || cv.w || RATIOS[S.ratio].w;
    S.baseH = f.baseH || cv.h || RATIOS[S.ratio].h;
    if(f.lineHeight) S.lh = f.lineHeight;
    if(cfg.effect && FFP_EFFECT_BY_ID[cfg.effect]) S.effect = cfg.effect;
    if(an.type) S.anim = an.type;
    if(an.inDuration) S.inDur = an.inDuration;
    if(an.total) S.total = an.total;
    if(an.fps) S.fps = an.fps;
    S.matteAuto = cfg.matteAuto !== false;
    if(cfg.matte) S.matte = cfg.matte;
    S.hlOn = !!cfg.highlight;
    if(cfg.highlight) S.hl = cfg.highlight;
    if(cfg.photo){ S.photoX = cfg.photo.x ?? 0; S.photoY = cfg.photo.y ?? 0; S.dim = cfg.photo.dim ?? 35; }
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
    render, setState, setAnim, applyConfig, snapshot,
    frameCount, estimate, ensureFont, currentMatte,
    sizePx, effect,
  };
  return api;
}

global.FFPGif = {
  RATIOS, ANIMS, ANIM_BY_ID, ANIM_DEFAULTS, animDefaults,
  HL_PRESETS, MAX_FRAMES, defaultState, createRenderer, easing:E, clamp:cl,
};

})(window);
