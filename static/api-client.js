/* ════════════════════════════════════════════════════════════
   FreeFontPick API 클라이언트
   백엔드 API를 호출해서 기존 *Store 인터페이스를 제공.
   index.html / admin.html이 거의 그대로 동작하도록 호환성 유지.
════════════════════════════════════════════════════════════ */

const API_BASE = '/api';

/* 공통 fetch 헬퍼 — 쿠키 세션 포함, JSON 자동 처리 */
async function apiFetch(path, options = {}) {
  const init = {
    credentials: 'same-origin',
    ...options,
    headers: {
      'Accept': 'application/json',
      ...(options.body && !(options.body instanceof FormData) ? {'Content-Type': 'application/json'} : {}),
      ...(options.headers || {}),
    },
  };
  if (init.body && typeof init.body !== 'string' && !(init.body instanceof FormData)) {
    init.body = JSON.stringify(init.body);
  }
  const res = await fetch(API_BASE + path, init);
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const message = (data && data.detail) || `요청 실패 (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/* ════════════════════════════════════════
   FontStore — 폰트 CRUD
   기존 인터페이스: getAll, add, update, remove, move(id,±1), moveTo(id,idx), setOrder(ids), resetToDefault
════════════════════════════════════════ */
const FontStore = {
  async getAll() {
    const fonts = await apiFetch('/fonts');
    // 서버 응답을 기존 프론트엔드가 기대하는 형태로 변환
    return fonts.map(f => ({
      id: f.id,
      name: f.name,
      maker: f.maker,
      weights: f.weights,
      url: f.url,
      stack: f.stack,
      tags: f.tags || [],
      isEnglish: f.is_english,
      primaryWeight: f.primary_weight || 400,
      hasFile: f.has_file,
      hasPairing: !!f.has_pairing,
      sort_order: f.sort_order,
      meta: f.meta || {},
      like_count: f.like_count || 0,
    }));
  },

  async add(payload) {
    const body = {
      name: payload.name,
      maker: payload.maker,
      weights: payload.weights || '1종',
      url: payload.url || '',
      stack: payload.stack || "'Nanum Gothic',sans-serif",
      is_english: !!payload.isEnglish,
      primary_weight: payload.primaryWeight || 400,
      tags: payload.tags || [],
      meta: payload.meta || {},
    };
    const created = await apiFetch('/fonts', {method: 'POST', body});
    return _fromServer(created);
  },

  async update(id, payload) {
    const body = {};
    if ('name' in payload) body.name = payload.name;
    if ('maker' in payload) body.maker = payload.maker;
    if ('weights' in payload) body.weights = payload.weights;
    if ('url' in payload) body.url = payload.url;
    if ('stack' in payload) body.stack = payload.stack;
    if ('isEnglish' in payload) body.is_english = !!payload.isEnglish;
    if ('primaryWeight' in payload) body.primary_weight = payload.primaryWeight;
    if ('tags' in payload) body.tags = payload.tags;
    if ('meta' in payload) body.meta = payload.meta;
    if ('sort_order' in payload) body.sort_order = payload.sort_order;
    const updated = await apiFetch(`/fonts/${id}`, {method: 'PATCH', body});
    return _fromServer(updated);
  },

  async remove(id) {
    await apiFetch(`/fonts/${id}`, {method: 'DELETE'});
    return true;
  },

  async setOrder(idsInOrder) {
    const items = idsInOrder.map((id, idx) => ({id, sort_order: (idx + 1) * 10}));
    const fonts = await apiFetch('/fonts/reorder', {method: 'POST', body: {items}});
    return fonts.map(_fromServer);
  },

  async move(id, delta) {
    const all = await this.getAll();
    const idx = all.findIndex(f => f.id === id);
    if (idx < 0) return all;
    const newIdx = Math.max(0, Math.min(all.length - 1, idx + delta));
    if (newIdx === idx) return all;
    const [item] = all.splice(idx, 1);
    all.splice(newIdx, 0, item);
    return await this.setOrder(all.map(f => f.id));
  },

  async moveTo(id, targetIdx) {
    const all = await this.getAll();
    const idx = all.findIndex(f => f.id === id);
    if (idx < 0) return all;
    const [item] = all.splice(idx, 1);
    all.splice(Math.max(0, Math.min(all.length, targetIdx)), 0, item);
    return await this.setOrder(all.map(f => f.id));
  },

  async resetToDefault() {
    // 백엔드는 시드 기반 — 클라이언트가 리셋할 일은 없음.
    // 호환 위해 no-op + 현재 목록 반환
    return await this.getAll();
  },
};

function _fromServer(f) {
  return {
    id: f.id,
    name: f.name,
    maker: f.maker,
    weights: f.weights,
    url: f.url,
    stack: f.stack,
    tags: f.tags || [],
    isEnglish: f.is_english,
    primaryWeight: f.primary_weight || 400,
    hasFile: f.has_file,
    hasPairing: !!f.has_pairing,
    sort_order: f.sort_order,
    meta: f.meta || {},
    like_count: f.like_count || 0,
  };
}

/* ════════════════════════════════════════
   TagStore — 카테고리 CRUD
   기존 인터페이스: getAll, add, rename, remove
   추가: move(name, ±1), moveTo(name, idx), setOrder(names[])
════════════════════════════════════════ */
const TagStore = {
  async getAll() {
    const tags = await apiFetch('/tags');
    return tags.map(t => t.name);
  },
  async _getRaw() {
    return await apiFetch('/tags');
  },
  async add(name) {
    return await apiFetch('/tags', {method: 'POST', body: {name}});
  },
  async rename(oldName, newName) {
    const tags = await this._getRaw();
    const tag = tags.find(t => t.name === oldName);
    if (!tag) throw new Error('카테고리를 찾을 수 없어요');
    return await apiFetch(`/tags/${tag.id}`, {method: 'PATCH', body: {name: newName}});
  },
  async remove(name) {
    const tags = await this._getRaw();
    const tag = tags.find(t => t.name === name);
    if (!tag) return;
    await apiFetch(`/tags/${tag.id}`, {method: 'DELETE'});
  },

  /** 카테고리 순서를 names 배열의 순서대로 재정렬 (각 카테고리에 sort_order 부여) */
  async setOrder(namesInOrder) {
    const tags = await this._getRaw();
    const nameToId = {};
    tags.forEach(t => { nameToId[t.name] = t.id; });
    // 각 카테고리에 새 sort_order 부여 (PATCH 병렬 호출)
    await Promise.all(namesInOrder.map((name, idx) => {
      const id = nameToId[name];
      if (!id) return null;
      return apiFetch(`/tags/${id}`, {
        method: 'PATCH',
        body: {sort_order: (idx + 1) * 10},
      });
    }));
    return await this.getAll();
  },

  async move(name, delta) {
    const all = await this.getAll();
    const idx = all.indexOf(name);
    if (idx < 0) return all;
    const newIdx = Math.max(0, Math.min(all.length - 1, idx + delta));
    if (newIdx === idx) return all;
    const [item] = all.splice(idx, 1);
    all.splice(newIdx, 0, item);
    return await this.setOrder(all);
  },

  async moveTo(name, targetIdx) {
    const all = await this.getAll();
    const idx = all.indexOf(name);
    if (idx < 0) return all;
    const [item] = all.splice(idx, 1);
    all.splice(Math.max(0, Math.min(all.length, targetIdx)), 0, item);
    return await this.setOrder(all);
  },
};

/* ════════════════════════════════════════
   SubmissionStore — 폰트 찾아주세요 게시판
   기존 인터페이스: getAll, getById, add(formData), update, remove, imageUrl(id)
════════════════════════════════════════ */
const SubmissionStore = {
  async getAll() {
    return await apiFetch('/submissions');
  },
  async getById(id) {
    return await apiFetch(`/submissions/${id}`);
  },
  /** payload: {nickname, content, imageFile?} — multipart로 전송 */
  async add(payload) {
    const fd = new FormData();
    fd.append('nickname', payload.nickname || '익명');
    fd.append('content', payload.content || '');
    if (payload.imageFile) fd.append('image', payload.imageFile);
    return await apiFetch('/submissions', {method: 'POST', body: fd});
  },
  async update(id, payload) {
    return await apiFetch(`/submissions/${id}`, {method: 'PATCH', body: payload});
  },
  async remove(id) {
    await apiFetch(`/submissions/${id}`, {method: 'DELETE'});
  },
  imageUrl(id) {
    return `${API_BASE}/submissions/${id}/image`;
  },
};

/* ════════════════════════════════════════
   NoticeStore — 공지사항 CRUD
   기존 인터페이스: getAll, getById, add, update, remove
════════════════════════════════════════ */
const NoticeStore = {
  async getAll() {
    return await apiFetch('/notices');
  },
  async getById(id) {
    return await apiFetch(`/notices/${id}`);
  },
  async add(payload) {
    return await apiFetch('/notices', {method: 'POST', body: payload});
  },
  async update(id, payload) {
    return await apiFetch(`/notices/${id}`, {method: 'PATCH', body: payload});
  },
  async remove(id) {
    await apiFetch(`/notices/${id}`, {method: 'DELETE'});
  },
};

/* ════════════════════════════════════════
   PairingStore — 폰트 페어링 CRUD (어드민)
   기존 페어링 API(GET /api/pairings)는 공개용으로 이미 있었고,
   여기서는 어드민 생성/수정/삭제 + 테마 목록만 추가.
════════════════════════════════════════ */
const PairingStore = {
  async getAll() {
    return await apiFetch('/pairings');
  },
  async getThemes() {
    return await apiFetch('/pairings/themes');
  },
  /** payload: {theme, title_font_id, body_font_id, sample_title, sample_body, description, title_weight, body_weight, sort_order} */
  async add(payload) {
    return await apiFetch('/pairings', {method: 'POST', body: payload});
  },
  async update(id, payload) {
    return await apiFetch(`/pairings/${id}`, {method: 'PATCH', body: payload});
  },
  async remove(id) {
    await apiFetch(`/pairings/${id}`, {method: 'DELETE'});
  },
};

/* ════════════════════════════════════════
   FontWeightStore — 폰트별 추가 굵기 등록 (어드민)
   대표 굵기(primaryWeight)는 FontStore.add/update의 primaryWeight로 관리하고,
   여기서는 대표 파일과 별도인 "추가 굵기" 파일들만 다룬다.
════════════════════════════════════════ */
const FontWeightStore = {
  /** 해당 폰트에 등록된 전체 굵기 목록 (대표 굵기 + 추가 굵기 + 레거시 매니페스트 병합 결과) */
  async list(fontId) {
    return await apiFetch(`/fonts/${fontId}/weights`);
  },
  /** weight: 100~900, label: 문자열(비우면 서버가 자동 라벨), file: woff2 File */
  async add(fontId, weight, label, file) {
    const fd = new FormData();
    fd.append('weight', String(weight));
    fd.append('label', label || '');
    fd.append('file', file);
    return await apiFetch(`/fonts/${fontId}/weights`, {method: 'POST', body: fd});
  },
  async remove(fontId, weight) {
    await apiFetch(`/fonts/${fontId}/weights/${weight}`, {method: 'DELETE'});
  },
};

/* ════════════════════════════════════════
   FontFileStore — 폰트 파일
   기존 인터페이스: saveFile, getFile, deleteFile, listIds
   백엔드 도입 후엔 파일이 서버에 저장됨. 클라이언트는 URL만 사용.
════════════════════════════════════════ */
const FontFileStore = {
  /** 어드민에서 파일 업로드 */
  async saveFile(fontId, file) {
    const fd = new FormData();
    fd.append('file', file);
    return await apiFetch(`/fonts/${fontId}/file`, {method: 'POST', body: fd});
  },

  /** 기존 호출부 호환: 이 함수는 더 이상 IndexedDB blob을 반환하지 않음.
   *  메인 페이지의 폰트 로드 로직이 직접 URL을 쓰도록 바뀌었으니
   *  null을 반환하여 "파일 없음" 경로를 따르게 함. */
  async getFile(fontId) {
    return null;
  },

  async deleteFile(fontId) {
    await apiFetch(`/fonts/${fontId}/file`, {method: 'DELETE'});
  },

  async listIds() {
    const fonts = await FontStore.getAll();
    return fonts.filter(f => f.hasFile).map(f => f.id);
  },

  /** 특정 폰트의 파일 URL — @font-face에서 사용 */
  fileUrl(fontId) {
    return `/api/fonts/${fontId}/file`;
  },
};

/* ════════════════════════════════════════
   LikeAPI — 좋아요 토글 (전역 카운트)
   - localStorage는 "내가 좋아요한 폰트" 표시용으로 유지
   - DB의 like_count가 진짜 카운트
════════════════════════════════════════ */
const LikeAPI = {
  async add(fontId) {
    return await apiFetch(`/fonts/${fontId}/like`, {method: 'POST'});
  },
  async remove(fontId) {
    return await apiFetch(`/fonts/${fontId}/like`, {method: 'DELETE'});
  },
};

/* ════════════════════════════════════════
   AuthAPI — 어드민 인증
════════════════════════════════════════ */
const AuthAPI = {
  async login(username, password) {
    return await apiFetch('/auth/login', {method: 'POST', body: {username, password}});
  },
  async logout() {
    await apiFetch('/auth/logout', {method: 'POST'});
  },
  async status() {
    return await apiFetch('/auth/status');
  },
  async changePassword(currentPassword, newPassword) {
    return await apiFetch('/auth/change-password', {
      method: 'POST',
      body: {current_password: currentPassword, new_password: newPassword},
    });
  },
};

/* ════════════════════════════════════════
   onDataChanged — 더 이상 BroadcastChannel 동기화 안 함
   백엔드가 진실의 원천이므로, 어드민 변경 후 메인 페이지는 다음 로드 시 자동 갱신.
   호환을 위해 빈 등록 함수만 둠.
════════════════════════════════════════ */
function onDataChanged(cb) {
  // no-op (구 코드 호환용)
}
