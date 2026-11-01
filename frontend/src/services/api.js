// API client for the LabelSafe backend (FastAPI, proxied at /api by Vite in development).

const API_BASE = '/api/v1';

export const getStoredToken = () => localStorage.getItem('labelsafe_access_token');
export const setStoredToken = (token) => localStorage.setItem('labelsafe_access_token', token);
export const removeStoredToken = () => {
  localStorage.removeItem('labelsafe_access_token');
  localStorage.removeItem('labelsafe_refresh_token');
  localStorage.removeItem('labelsafe_user');
};

export const getStoredUser = () => {
  const u = localStorage.getItem('labelsafe_user');
  try {
    return u ? JSON.parse(u) : null;
  } catch {
    return null;
  }
};

export const setStoredUser = (user) => {
  localStorage.setItem('labelsafe_user', JSON.stringify(user));
};

// One refresh attempt per expired access token; concurrent 401s share it.
let refreshing = null;
async function refreshTokens() {
  const refreshToken = localStorage.getItem('labelsafe_refresh_token');
  if (!refreshToken) return false;
  refreshing ??= fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
    .then(async (res) => {
      if (!res.ok) return false;
      const tokens = await res.json();
      setStoredToken(tokens.access_token);
      localStorage.setItem('labelsafe_refresh_token', tokens.refresh_token);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function apiRequest(endpoint, options = {}, retried = false) {
  const token = getStoredToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });

  if (response.status === 401 && token && !retried && !endpoint.startsWith('/auth/')) {
    if (await refreshTokens()) return apiRequest(endpoint, options, true);
    removeStoredToken(); // the session is over; the next screen shows signed-out
  }

  if (response.status === 204) {
    return null;
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    // FastAPI returns `detail` as a string, a list of validation errors, or an object.
    let errorMsg = 'Request failed';
    if (typeof data.detail === 'string') {
      errorMsg = data.detail;
    } else if (Array.isArray(data.detail)) {
      errorMsg = data.detail
        .map((d) => `${d.loc ? d.loc.slice(-1)[0] + ': ' : ''}${(d.msg || JSON.stringify(d)).replace(/^Value error, /, '')}`)
        .join('; ');
    } else if (data.detail && typeof data.detail === 'object') {
      errorMsg = JSON.stringify(data.detail);
    }
    const err = new Error(errorMsg);
    err.status = response.status;
    err.data = data;
    throw err;
  }

  return data;
}

const post = (endpoint, body) => apiRequest(endpoint, { method: 'POST', body: JSON.stringify(body) });

export const authApi = {
  login: (credentials) => post('/auth/login', credentials),
  register: (payload) => post('/auth/register', payload),
  me: () => apiRequest('/auth/me'),
  logout: () => apiRequest('/auth/logout', { method: 'POST' }),
};

export const safetyApi = {
  analyze: (payload) => post('/safety/analyze', payload),
  // Each finding explained from its own FDA label passages (RAG); same payload as analyze.
  explainFindings: (payload) => post('/safety/explain-findings', payload),
};

export const chatApi = {
  send: (payload) => post('/chat/message', payload),
};

export const profileApi = {
  get: () => apiRequest('/users/me/profile'),
  put: (profile) => apiRequest('/users/me/profile', { method: 'PUT', body: JSON.stringify(profile) }),
  remove: () => apiRequest('/users/me/profile', { method: 'DELETE' }),
};

const title = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());

// A medication search hit ({ concept, has_rules }) as a SearchPicker item.
export const medicationItem = (hit) => ({
  ...hit,
  key: hit.concept.rxcui,
  label: title(hit.concept.canonical_name),
  detail: hit.concept.synonyms.slice(0, 2).join(', ') || undefined,
});

export const medicationsApi = {
  search: (q, limit = 8) => apiRequest(`/medications/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  suggest: (q) => medicationsApi.search(q, 8).then((hits) => hits.map(medicationItem)),
};

// Stored profile records as SearchPicker items, and back.
export const conditionItem = (c) => ({
  key: (c.icd10_code || c.condition_name).toLowerCase(),
  label: c.condition_name,
  code: c.icd10_code,
});
export const allergyItem = (a) => ({ key: a.substance_name.toLowerCase(), label: a.substance_name, unii: a.unii });

// Saved medication names back to catalogue items; names the catalogue no longer has are skipped.
export const resolveMedications = (names) =>
  Promise.all(
    names.map((name) =>
      medicationsApi
        .search(name, 5)
        .then((hits) => hits.find((h) => h.concept.canonical_name.toLowerCase() === name.toLowerCase()))
        .catch(() => undefined),
    ),
  ).then((hits) => hits.filter(Boolean).map(medicationItem));

// Foods, conditions (ICD-10-CM) and allergens: GET /vocab/{kind}/search -> { label, value, code?, unii?, has_rules }.
const vocab = (kind) => (q) =>
  apiRequest(`/vocab/${kind}/search?q=${encodeURIComponent(q)}&limit=8`).then((hits) =>
    hits.map((h) => ({ ...h, key: (h.code || h.label).toLowerCase() })),
  );

export const vocabApi = {
  foods: vocab('foods'),
  conditions: vocab('conditions'),
  allergens: vocab('allergens'),
};

export const statsApi = {
  get: () => apiRequest('/stats'),
};

export const evidenceApi = {
  subgraph: (findingId) => apiRequest(`/evidence/subgraph/${encodeURIComponent(findingId)}`),
};
