/* 정본: projects\폰트픽\리뉴얼_시안\themes\d.js — 여기를 직접 고치지 말고 그쪽에서 고쳐 publish.py 로 옮긴다 */
/* 시안 D 움직임 (apple-design 스킬, 2026-10-30)
   ① 스크롤하면 머리글에 가장자리 그림자(html.d-edge).
   ② '쓰는 자리' 칩 막대를 마우스로 끌기 — 손을 따라 1:1, 놓으면 그 속도로 계속 미끄러져(관성 예측),
      끝에서는 고무줄처럼 버티다 스프링으로 돌아온다. 움직이는 중에도 다시 잡을 수 있다.
   터치는 브라우저 기본 스크롤이 이미 그렇게 움직이므로 손대지 않는다. */
(function(){
  var reduce = false;
  try { reduce = matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  /* ① 가장자리 그림자 */
  var root = document.documentElement;
  function edge(){ root.classList.toggle('d-edge', scrollY > 4); }
  addEventListener('scroll', edge, {passive:true}); edge();

  /* 터치에서도 :active 가 바로 켜지게 */
  document.addEventListener('touchstart', function(){}, {passive:true});

  /* ② 칩 막대 */
  var el = document.querySelector('.use-bar-scroll');
  if (!el) return;

  function project(v, d){ d = d || 0.998; return (v / 1000) * d / (1 - d); }          /* 놓은 속도 → 멈출 자리 */
  function rubber(over, dim, c){ c = c || 0.55; return (over * dim * c) / (dim + c * Math.abs(over)); }

  var pos = el.scrollLeft, vel = 0, target = null, raf = 0;
  var dragging = false, moved = false, startX = 0, startPos = 0, hist = [];

  function maxPos(){ return el.scrollWidth - el.clientWidth; }
  function apply(p){                                    /* 범위 안은 scrollLeft, 밖은 고무줄 transform */
    var m = maxPos(), over = p < 0 ? p : (p > m ? p - m : 0);
    el.scrollLeft = Math.max(0, Math.min(m, p));
    el.style.transform = over ? 'translateX(' + (-rubber(over, el.clientWidth)) + 'px)' : '';
  }
  /* 임계 감쇠 스프링(감쇠 1.0, 반응 0.4초) — 현재 자리·현재 속도에서 출발하므로 도중에 잡아도 튀지 않는다 */
  function step(t0){
    var last = t0;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(function tick(now){
      var dt = Math.min(0.032, (now - last) / 1000); last = now;
      var w = 2 * Math.PI / 0.4, k = w * w, c = 2 * w;
      var acc = -k * (pos - target) - c * vel;
      vel += acc * dt; pos += vel * dt;
      apply(pos);
      if (Math.abs(pos - target) < 0.3 && Math.abs(vel) < 5) { pos = target; apply(pos); target = null; return; }
      raf = requestAnimationFrame(tick);
    });
  }

  el.addEventListener('pointerdown', function(e){
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    if (target === null) pos = el.scrollLeft;            /* 쉬고 있으면 지금 자리, 움직이던 중이면 그 자리에서 그대로 잡는다 */
    cancelAnimationFrame(raf); target = null; vel = 0;
    dragging = true; moved = false; startX = e.clientX; startPos = pos; hist = [[e.timeStamp, e.clientX]];
  });
  addEventListener('pointermove', function(e){
    if (!dragging) return;
    var dx = e.clientX - startX;
    if (!moved && Math.abs(dx) < 8) return;             /* 8px 넘게 움직여야 끌기로 본다 — 그 전은 그냥 누름 */
    if (!moved) { moved = true; el.classList.add('d-drag'); try { el.setPointerCapture(e.pointerId); } catch (_) {} }
    pos = startPos - dx; apply(pos);
    hist.push([e.timeStamp, e.clientX]); if (hist.length > 5) hist.shift();
  });
  addEventListener('pointerup', function(e){
    if (!dragging) return;
    dragging = false; el.classList.remove('d-drag');
    if (!moved) return;
    var a = hist[0], b = hist[hist.length - 1], dt = (b[0] - a[0]) || 16;
    vel = -(b[1] - a[1]) / dt * 1000;                    /* px/s, 스크롤 방향 */
    if (reduce) vel = 0;
    target = Math.max(0, Math.min(maxPos(), pos + project(vel)));
    step(performance.now());
  });
  /* 끌고 난 뒤의 클릭은 칩 이동으로 치지 않는다 */
  el.addEventListener('click', function(e){ if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);
  el.addEventListener('dragstart', function(e){ e.preventDefault(); });
})();
