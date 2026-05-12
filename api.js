// VitalSync API Client
const API_BASE = window.VITALSYNC_API_URL || 'http://localhost:8000';

let _token = localStorage.getItem('vs_token');
let _user = JSON.parse(localStorage.getItem('vs_user') || 'null');

export const auth = {
  getToken: () => _token,
  getUser: () => _user,
  isLoggedIn: () => !!_token,

  setSession(token, user) {
    _token = token;
    _user = user;
    localStorage.setItem('vs_token', token);
    localStorage.setItem('vs_user', JSON.stringify(user));
  },

  clearSession() {
    _token = null;
    _user = null;
    localStorage.removeItem('vs_token');
    localStorage.removeItem('vs_user');
  }
};

async function request(method, path, body = null, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (_token) headers['Authorization'] = `Bearer ${_token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : null,
    ...opts,
  });

  if (res.status === 401) {
    auth.clearSession();
    window.location.hash = '#login';
    throw new Error('Session expired');
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

// Form-encoded login (OAuth2 requirement)
async function loginRequest(email, password) {
  const formData = new URLSearchParams();
  formData.append('username', email);
  formData.append('password', password);

  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formData,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'Login failed');
  return data;
}

// ── API Methods ───────────────────────────────────────────────────────────────

export const api = {
  // Auth
  login: (email, password) => loginRequest(email, password),
  register: (data) => request('POST', '/api/auth/register', data),

  // Patient
  getProfile: () => request('GET', '/api/patient/profile'),
  updateProfile: (data) => request('PUT', '/api/patient/profile', data),
  submitVitals: (data) => request('POST', '/api/patient/vitals', data),
  getLatestVitals: (limit = 50) => request('GET', `/api/patient/vitals/latest?limit=${limit}`),
  getVitalStats: (days = 7) => request('GET', `/api/patient/vitals/stats?days=${days}`),
  getHealthScore: () => request('GET', '/api/patient/health-score'),
  getCheckinQuestions: () => request('GET', '/api/patient/checkin/questions'),
  submitCheckin: (data) => request('POST', '/api/patient/checkin', data),
  getAlerts: (unreadOnly = false) => request('GET', `/api/patient/alerts?unread_only=${unreadOnly}`),
  acknowledgeAlert: (id) => request('PUT', `/api/patient/alerts/${id}/acknowledge`),
  getAiPrescription: (symptoms) => request('POST', '/api/patient/prescription/ai', { symptoms }),
  getFamily: () => request('GET', '/api/patient/family'),
  addFamilyMember: (data) => request('POST', '/api/patient/family', data),
  removeFamilyMember: (id) => request('DELETE', `/api/patient/family/${id}`),
  getRecords: () => request('GET', '/api/hospital/records/my'),

  // Hospital
  listHospitals: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return request('GET', `/api/hospital/list?${q}`);
  },
  getHospital: (id) => request('GET', `/api/hospital/${id}`),
  bookHospital: (data) => request('POST', '/api/hospital/book', data),
  estimateBudget: (data) => request('POST', '/api/hospital/budget-estimate', data),
  updateHospitalProfile: (data) => request('PUT', '/api/hospital/profile', data),
  getHospitalProfile: () => request('GET', '/api/hospital/profile/me'),
  getIncomingBookings: (status) => request('GET', `/api/hospital/bookings/incoming${status ? `?status=${status}` : ''}`),
  updateBookingStatus: (id, status) => request('PUT', `/api/hospital/bookings/${id}/status?status=${status}`),

  // Pharmacy
  searchMedicine: (name, city) => request('GET', `/api/pharmacy/medicine/search?name=${encodeURIComponent(name)}${city ? `&city=${city}` : ''}`),
  searchBlood: (bloodGroup, city) => request('GET', `/api/pharmacy/blood/search?blood_group=${bloodGroup}${city ? `&city=${city}` : ''}`),
  getAllBloodGroups: (city) => request('GET', `/api/pharmacy/blood/all-groups${city ? `?city=${city}` : ''}`),
  listPharmacies: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return request('GET', `/api/pharmacy/list?${q}`);
  },
  updatePharmacyProfile: (data) => request('PUT', '/api/pharmacy/profile', data),
  addMedicine: (data) => request('POST', '/api/pharmacy/medicine', data),
  getMyInventory: () => request('GET', '/api/pharmacy/medicine/my'),
  updateBloodInventory: (data) => request('POST', '/api/pharmacy/blood', data),
  getMyBloodInventory: () => request('GET', '/api/pharmacy/blood/my'),
};

// ── WebSocket Alert Stream ─────────────────────────────────────────────────────

let _ws = null;
const _listeners = new Set();

export function connectAlertStream(userId, onMessage) {
  if (_ws) _ws.close();

  const wsUrl = API_BASE.replace('http', 'ws') + `/ws/alerts/${userId}`;
  _ws = new WebSocket(wsUrl);

  _ws.onopen = () => {
    console.log('🔔 Alert stream connected');
    // Ping every 30s to keep alive
    setInterval(() => {
      if (_ws?.readyState === WebSocket.OPEN) {
        _ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  };

  _ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      onMessage(msg);
      _listeners.forEach(fn => fn(msg));
    } catch (e) {}
  };

  _ws.onclose = () => {
    console.log('Alert stream disconnected, reconnecting in 5s...');
    setTimeout(() => connectAlertStream(userId, onMessage), 5000);
  };

  _ws.onerror = (e) => console.error('WebSocket error:', e);
  return _ws;
}

export function addAlertListener(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

export function acknowledgeAlertWS(alertId) {
  if (_ws?.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify({ type: 'acknowledge_alert', alert_id: alertId }));
  }
}
