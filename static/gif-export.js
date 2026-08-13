/* ══════════════════════════════════════════════════════════════════
   gif-export.js — GIF / MP4 내보내기

   gif-render.js 의 렌더러 인스턴스를 받아 프레임을 돌려 파일로 만든다.
   gifenc(vendor/gifenc.js)는 미리 불러와 있어야 하고,
   mp4-muxer는 72KB라 MP4를 처음 누를 때만 받아온다.
══════════════════════════════════════════════════════════════════ */
(function(global){
'use strict';

/* ── 저장 ──────────────────────────────────────────────────────
   카카오톡·인스타 같은 인앱 브라우저에서는 <a download>가 아무 일도
   하지 않거나 페이지를 떠나버린다. 한국 모바일 트래픽의 상당수가
   여기로 들어오므로 세 단계로 내려간다:
     ① 공유 시트(navigator.share) → 「사진에 저장」
     ② PC면 그냥 다운로드
     ③ 둘 다 안 되면 이미지를 화면에 띄우고 길게 눌러 저장하게 한다
   ③은 '디자인하기'에서 이미 검증된 방식이다. */

function isMobile(){
  return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
      || matchMedia('(pointer:coarse)').matches;
}

function isInAppBrowser(){
  const ua = navigator.userAgent || '';
  return /KAKAOTALK|NAVER\(inapp|Instagram|FBAN|FBAV|Line\//i.test(ua);
}

function downloadBlob(blob, filename){
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 4000);
}

/* 저장 시도. 길게 눌러 저장해야 하는 경우 onLongPress(blobUrl)을 부른다. */
async function saveBlob(blob, filename, opts){
  opts = opts || {};
  const mime = blob.type || '';
  const file = new File([blob], filename, {type:mime});

  if(isMobile() && navigator.canShare && navigator.canShare({files:[file]})){
    try{
      await navigator.share({files:[file], title:'폰트픽 GIF'});
      return 'shared';
    }catch(err){
      if(err && err.name === 'AbortError') return 'cancelled';
    }
  }
  if(!isMobile()){
    downloadBlob(blob, filename);
    return 'downloaded';
  }
  /* 인앱 브라우저 — 이미지를 띄워 길게 누르게 한다. GIF만 가능하다(MP4는 영상). */
  if(opts.onLongPress && /image\//.test(mime)){
    opts.onLongPress(URL.createObjectURL(blob));
    return 'longpress';
  }
  downloadBlob(blob, filename);
  return 'downloaded';
}

function safeName(text, ext){
  const base = String(text||'').split('\n')[0].replace(/[^\w가-힣]/g,'').slice(0,14);
  return `폰트픽-${base || 'gif'}.${ext}`;
}

function hexRgb(h){
  const c = String(h||'#000').replace('#','');
  return [parseInt(c.substr(0,2),16)||0, parseInt(c.substr(2,2),16)||0, parseInt(c.substr(4,2),16)||0];
}

/* ── GIF ─────────────────────────────────────────────────────── */
async function exportGIF(renderer, onProgress){
  if(typeof GIFEncoder === 'undefined') throw new Error('GIF 인코더를 불러오지 못했어요. 새로고침 해주세요.');

  const S = renderer.state;
  const ctx = renderer.canvas.getContext('2d', {willReadFrequently:true});
  const W = renderer.width, H = renderer.height;
  const total = renderer.frameCount();
  const fps = total / S.total;                 // 프레임 상한에 걸렸을 수 있다
  const delay = Math.round(1000/fps);
  const gif = GIFEncoder();
  /* 배경이 불투명하면(사진·단색) 투명 처리도 매트도 필요 없다.
     팔레트는 사진만 넉넉히 준다 — 단색 배경은 색이 하나 늘 뿐이라 64색으로 충분하다. */
  const opaque = renderer.isOpaque ? renderer.isOpaque() : !!S.photo;
  const colors = (renderer.needsRichPalette ? renderer.needsRichPalette() : !!S.photo) ? 192 : 64;
  const [mr, mg, mb] = hexRgb(renderer.currentMatte());

  for(let i=0; i<total; i++){
    /* 영상 모드는 그리기 전에 그 시점으로 찾아가야 한다 (seek은 비동기라
       동기 함수인 render 안에서 처리할 수 없다). 사진·글자는 할 일이 없다. */
    if(renderer.prepareFrame) await renderer.prepareFrame(i/total);
    renderer.render(i/total);
    const img = ctx.getImageData(0,0,W,H), d = img.data;

    if(opaque){
      const palette = quantize(d, colors);
      const index = applyPalette(d, palette);
      gif.writeFrame(index, W, H, {palette, delay});
    }else{
      /* 투명 배경 — GIF의 알파는 1비트(있다/없다)뿐이다.
         남길 픽셀은 매트색과 미리 섞어 톱니를 완화하고, 버릴 픽셀은
         완전히 0으로 지운다.

         지우는 게 왜 중요한가
         --------------------
         soft/gray/glow 그림자는 알파 1~10짜리 꼬리를 넓게 남긴다. 화면에서는
         안 보이지만, 이걸 매트색과 섞어두면 (흰색, 알파 1) 같은 픽셀이 된다.
         applyPalette는 알파까지 포함해 '가장 가까운 팔레트 색'을 찾는데,
         이 픽셀은 투명(0,0,0,0)보다 불투명 흰색(255,255,255,255)에 더 가까워서
         결국 또렷한 흰 덩어리로 찍힌다 — 하이라이트 바 아래가 뭉개져 보이던 원인.
         버릴 픽셀은 RGB까지 0으로 만들어야 투명 팔레트 항목과 정확히 맞는다.

         기준값 128은 gifenc의 oneBitAlpha 기본 임계값과 같다. 팔레트를 만들 때와
         픽셀을 매핑할 때 기준이 다르면 경계에서 다시 어긋난다. */
      const ALPHA_CUT = 128;
      for(let j=0;j<d.length;j+=4){
        const a = d[j+3];
        if(a === 255) continue;
        if(a < ALPHA_CUT){ d[j] = d[j+1] = d[j+2] = d[j+3] = 0; continue; }
        const k = a/255;
        d[j]   = Math.round(d[j]  *k + mr*(1-k));
        d[j+1] = Math.round(d[j+1]*k + mg*(1-k));
        d[j+2] = Math.round(d[j+2]*k + mb*(1-k));
        d[j+3] = 255;              // 남기기로 했으면 완전 불투명으로
      }
      const palette = quantize(d, 64, {
        format:'rgba4444', oneBitAlpha:true, clearAlpha:true, clearAlphaThreshold:0,
      });
      const index = applyPalette(d, palette, 'rgba4444');
      const ti = palette.findIndex(p=>p.length===4 && p[3]===0);
      gif.writeFrame(index, W, H, {
        palette, delay,
        transparent: ti>=0, transparentIndex: ti<0?0:ti,
        dispose: 2,
      });
    }

    /* 3프레임마다 이벤트 루프를 놓아준다 — 안 그러면 브라우저가
       "응답 없음"으로 판단하고 iOS는 탭을 죽인다. */
    if(i % 3 === 0){
      if(onProgress) onProgress(i/total, `인코딩 ${i}/${total}`);
      await new Promise(r=>setTimeout(r,0));
    }
  }
  gif.finish();
  if(onProgress) onProgress(1, '마무리 중…');
  return new Blob([gif.bytes()], {type:'image/gif'});
}

/* ── 사진 GIF 용량·시간 실측 ───────────────────────────────────
   사진 GIF는 프레임마다 팔레트를 새로 뜨고 화면을 통째로 다시 쓴다.
   그래서 용량이 프레임 수에 정확히 비례하고, 고정 비용이 사실상 없다.
   실측: 같은 사진으로 4·8·16프레임을 뽑았더니 프레임당 크기가
   50.5KB / 50.5KB / 50.5KB 로 완전히 일정했다.

   문제는 그 '프레임당 크기'가 사진에 따라 50KB~309KB로 6배까지 벌어진다는 것이다.
   어떤 상수를 넣어도 절반은 틀리므로, 추정하지 않고 실제로 한 장을 인코딩해 잰다.
   한 장 값 × 프레임 수가 곧 정답이다.

   인코딩 시간도 같이 잰다 — 복잡한 사진은 프레임당 800ms까지 가서
   90프레임이면 1분 넘게 화면이 멈춘다. 누르기 전에 알려줘야 한다. */
async function measurePhotoFrame(renderer){
  if(typeof GIFEncoder === 'undefined') return null;
  const ctx = renderer.canvas.getContext('2d', {willReadFrequently:true});
  const W = renderer.width, H = renderer.height;
  const colors = (renderer.needsRichPalette && renderer.needsRichPalette()) ? 192 : 64;

  const t0 = performance.now();
  if(renderer.prepareFrame) await renderer.prepareFrame(0.5);
  renderer.render(0.5);                    // 전환 중이 아닌 '한 장이 그대로 보이는' 시점
  const d = ctx.getImageData(0, 0, W, H).data;
  const gif = GIFEncoder();
  const palette = quantize(d, colors);
  const index = applyPalette(d, palette);
  gif.writeFrame(index, W, H, {palette, delay:100});
  gif.finish();
  const ms = performance.now() - t0;

  /* 헤더+팔레트(1KB 남짓)가 얹혀 있지만 프레임 자체가 50KB 이상이라
     오차가 2%를 넘지 않는다. 빼려고 0프레임짜리를 또 인코딩할 값어치가 없다. */
  return {bytes: gif.bytes().length, ms};
}

/* ── MP4 ─────────────────────────────────────────────────────── */
let _mp4Loading = null;
function loadMp4Muxer(){
  if(typeof Mp4Muxer !== 'undefined') return Promise.resolve();
  if(_mp4Loading) return _mp4Loading;
  _mp4Loading = new Promise((resolve, reject)=>{
    const s = document.createElement('script');
    s.src = '/static/vendor/mp4-muxer.js';
    s.onload = resolve;
    s.onerror = ()=>reject(new Error('MP4 인코더를 불러오지 못했어요.'));
    document.head.appendChild(s);
  });
  return _mp4Loading;
}

function mp4Supported(){ return typeof VideoEncoder !== 'undefined'; }

const H264_CODECS = ['avc1.42002A','avc1.4D002A','avc1.640028','avc1.42001f'];
async function pickCodec(W, H, fps){
  for(const codec of H264_CODECS){
    try{
      const r = await VideoEncoder.isConfigSupported({codec, width:W, height:H, bitrate:5e6, framerate:fps});
      if(r.supported) return codec;
    }catch(e){}
  }
  return null;
}

async function exportMP4(renderer, onProgress){
  if(!mp4Supported()) throw new Error('이 브라우저는 MP4 저장을 지원하지 않아요.\n크롬·엣지·사파리 16.4 이상에서 열어주세요.');
  await loadMp4Muxer();

  const S = renderer.state;
  const ctx = renderer.canvas.getContext('2d', {willReadFrequently:true});
  /* H.264는 짝수 해상도를 요구한다 */
  const W = renderer.width % 2 ? renderer.width - 1 : renderer.width;
  const H = renderer.height % 2 ? renderer.height - 1 : renderer.height;
  const total = renderer.frameCount();
  const fps = Math.round(total / S.total);

  const codec = await pickCodec(W, H, fps);
  if(!codec) throw new Error('이 기기에서 H.264 인코딩을 지원하지 않아요.');

  const muxer = new Mp4Muxer.Muxer({
    target: new Mp4Muxer.ArrayBufferTarget(),
    video: {codec:'avc', width:W, height:H},
    fastStart: 'in-memory',
  });
  let encErr = null;
  const encoder = new VideoEncoder({
    output: (chunk, meta)=>muxer.addVideoChunk(chunk, meta),
    error: e=>{ encErr = e; },
  });
  encoder.configure({codec, width:W, height:H, bitrate:5e6, framerate:fps});

  for(let i=0;i<total;i++){
    /* 영상 모드는 그리기 전에 그 시점으로 찾아가야 한다 (seek은 비동기라
       동기 함수인 render 안에서 처리할 수 없다). 이걸 빼면 video 요소가
       한 프레임에 멈춘 채로 전 프레임이 인코딩돼 정지 화면이 나온다.
       GIF 쪽에는 있는데 MP4에만 빠져 있었다. */
    if(renderer.prepareFrame) await renderer.prepareFrame(i/total);
    renderer.render(i/total);
    /* MP4는 알파를 담지 못한다 — 투명 배경이면 글자 뒤에 검정을 깔아준다.
       destination-over라 이미 그린 글자는 건드리지 않는다. */
    const bgOpaque = renderer.isOpaque ? renderer.isOpaque() : !!S.photo;
    if(!bgOpaque){
      ctx.save();
      ctx.globalCompositeOperation = 'destination-over';
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, renderer.width, renderer.height);
      ctx.restore();
    }

    const frame = new VideoFrame(renderer.canvas, {
      timestamp: Math.round(i*1e6/fps), duration: Math.round(1e6/fps),
    });
    encoder.encode(frame, {keyFrame: i % fps === 0});
    frame.close();                                   // 닫지 않으면 메모리가 샌다

    while(encoder.encodeQueueSize > 4) await new Promise(r=>setTimeout(r,0));
    if(i % 3 === 0){
      if(onProgress) onProgress(i/total, `MP4 인코딩 ${i}/${total}`);
      await new Promise(r=>setTimeout(r,0));
    }
    if(encErr) throw encErr;
  }
  if(onProgress) onProgress(1, '마무리 중…');
  await encoder.flush();
  muxer.finalize();
  return new Blob([muxer.target.buffer], {type:'video/mp4'});
}

global.FFPExport = {
  exportGIF, exportMP4, measurePhotoFrame,
  saveBlob, downloadBlob, safeName,
  isMobile, isInAppBrowser, mp4Supported, loadMp4Muxer,
};

})(window);
