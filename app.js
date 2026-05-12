/**
 * VitalSync PWA — Main Application Logic
 * Handles navigation, API calls, charts, WebSocket alerts
 */
import { api, auth, connectAlertStream } from './utils/api.js';

// ── State ──────────────────────────────────────────────────────────────────────
let currentPage = 'auth';
let trendChart = null;
let deferredInstallPrompt = null;
let unreadAlerts = 0;
let bloodGroupData = {};

// ── PWA Install ────────────────────────────────────────────────────────────────
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstallPrompt = e;
  document.getElementById('install-btn').style.display = 'flex';
});

window.installPWA = async () => {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  const { outcome } = await deferredInstallPrompt.userChoice;
  if (outcome === 'accepted') showToast('App installed! 🎉', 'success');
  deferredInstallPrompt = null;
};

// Register service worker
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/public/sw.js').catch(() => {});
}

// ── Toast ──────────────────────────────────────────────────────────────────────
window.showToast = function(message, type = 'info', duration = 3500) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
};

// ── Navigation ─────────────────────────────────────────────────────────────────
window.navigate = function(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');

  const navEl = document.getElementById(`nav-${page}`);
  if (navEl) navEl.classList.add('active');

  currentPage = page;
  document.getElementById('topbar-title').textContent =
    { dashboard: 'VitalSync', alerts: 'Alerts', hospital: 'Hospitals', pharmacy: 'Resources', profile: 'My Profile' }[page] || 'VitalSync';

  // Lazy load page content
  if (page === 'alerts') loadAlerts();
  if (page === 'hospital') loadHospitals();
  if (page === 'pharmacy') loadBloodGroups();
  if (page === 'profile') loadProfilePage();
};

function showAppShell() {
  document.getElementById('topbar').classList.add('visible');
  document.getElementById('bottomnav').classList.add('visible');
}

function hideAppShell() {
  document.getElementById('topbar').classList.remove('visible');
  document.getElementById('bottomnav').classList.remove('visible');
}

// ── Auth ───────────────────────────────────────────────────────────────────────
window.switchAuthTab = function(tab) {
  document.querySelectorAll('.auth-tab').forEach((t, i) => {
    t.classList.toggle('active', (i === 0 && tab === 'login') || (i === 1 && tab === 'register'));
  });
  document.getElementById('form-login').style.display = tab === 'login' ? 'flex' : 'none';
  document.getElementById('form-register').style.display = tab === 'register' ? 'flex' : 'none';
};

window.doLogin = async function() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  if (!email || !password) return showToast('Enter email and password', 'error');

  const btn = document.getElementById('login-btn');
  btn.textContent = 'Signing in...'; btn.disabled = true;

  try {
    const data = await api.login(email, password);
    auth.setSession(data.access_token, { id: data.user_id, role: data.role, name: data.full_name });
    onLoginSuccess(data);
  } catch (e) {
    showToast(e.message || 'Login failed', 'error');
  } finally {
    btn.textContent = 'Sign In'; btn.disabled = false;
  }
};

window.doRegister = async function() {
  const data = {
    full_name: document.getElementById('reg-name').value.trim(),
    email: document.getElementById('reg-email').value.trim(),
    password: document.getElementById('reg-password').value,
    phone: document.getElementById('reg-phone').value.trim(),
    role: document.getElementById('reg-role').value,
  };
  if (!data.full_name || !data.email || !data.password) return showToast('Fill in all required fields', 'error');

  const btn = document.getElementById('register-btn');
  btn.textContent = 'Creating...'; btn.disabled = true;

  try {
    const res = await api.register(data);
    auth.setSession(res.access_token, { id: res.user_id, role: res.role, name: res.full_name });
    onLoginSuccess(res);
    showToast('Account created!', 'success');
  } catch (e) {
    showToast(e.message || 'Registration failed', 'error');
  } finally {
    btn.textContent = 'Create Account'; btn.disabled = false;
  }
};

function onLoginSuccess(data) {
  document.getElementById('page-auth').classList.remove('active');
  showAppShell();
  navigate('dashboard');
  initDashboard();

  // Connect WebSocket
  connectAlertStream(data.user_id, handleWsMessage);
}

window.doLogout = function() {
  auth.clearSession();
  hideAppShell();
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-auth').classList.add('active');
  if (trendChart) { trendChart.destroy(); trendChart = null; }
  showToast('Signed out', 'info');
};

// ── WebSocket Message Handler ──────────────────────────────────────────────────
function handleWsMessage(msg) {
  if (msg.type === 'emergency_alert') {
    triggerEmergencyBanner(msg);
    bumpAlertCount();
  } else if (msg.type === 'checkin_reminder') {
    showToast('🩺 Time for your daily check-in!', 'info', 8000);
  } else if (msg.type === 'alert_acknowledged') {
    // handled
  }
}

function triggerEmergencyBanner(msg) {
  const banner = document.getElementById('emergency-banner');
  document.getElementById('emergency-title').textContent = '🚨 ' + (msg.flags?.[0]?.replace(/_/g, ' ') || 'Emergency Detected');
  document.getElementById('emergency-msg').textContent = msg.message || 'Emergency detected. Seek medical help immediately.';
  banner.classList.add('show');

  // Vibrate
  if (navigator.vibrate) navigator.vibrate([300, 100, 300, 100, 300]);
}

document.getElementById('emergency-dismiss').addEventListener('click', () => {
  document.getElementById('emergency-banner').classList.remove('show');
});

function bumpAlertCount() {
  unreadAlerts++;
  const badge = document.getElementById('alert-count');
  badge.textContent = unreadAlerts;
  badge.style.display = 'inline';
  document.getElementById('nav-dot-alerts').classList.add('visible');
}

// ── Dashboard ──────────────────────────────────────────────────────────────────
async function initDashboard() {
  const user = auth.getUser();
  if (!user) return;

  // Hide role-specific nav items based on role
  if (user.role !== 'patient') {
    document.getElementById('nav-alerts').style.display = 'none';
  }

  loadHealthScore();
  loadVitalStats(7);
  loadLatestVitals();
}

async function loadLatestVitals() {
  try {
    const readings = await api.getLatestVitals(1);
    if (readings.length > 0) {
      const r = readings[0];
      updateVitalDisplay(r);
    }
  } catch (e) {
    // Not critical
  }
}

function updateVitalDisplay(r) {
  const hr = r.heart_rate || 0;
  const spo2 = r.spo2 || 0;
  const temp = r.temperature || 0;
  const sys = r.systolic_bp || 0;
  const dia = r.diastolic_bp || 0;
  const status = r.health_status || 'healthy';

  document.getElementById('v-hr').textContent = hr.toFixed(0);
  document.getElementById('v-spo2').textContent = spo2.toFixed(1);
  document.getElementById('v-temp').textContent = temp.toFixed(1);
  document.getElementById('v-bp').textContent = `${sys.toFixed(0)}/${dia.toFixed(0)}`;

  const statusBadge = document.getElementById('dash-status');
  statusBadge.textContent = status.toUpperCase();
  statusBadge.className = `status-badge status-${status}`;

  // Highlight abnormal values
  document.getElementById('v-hr').parentElement.className = `vital-card${hr > 100 || hr < 60 ? ' warn' : ''}${hr > 150 || hr < 40 ? ' alert' : ''}`;
  document.getElementById('v-spo2').parentElement.className = `vital-card${spo2 < 95 ? ' warn' : ''}${spo2 < 90 ? ' alert' : ''}`;
  document.getElementById('v-temp').parentElement.className = `vital-card${temp > 37.5 ? ' warn' : ''}${temp > 39 ? ' alert' : ''}`;
}

async function loadHealthScore() {
  try {
    const scores = await api.getHealthScore();
    const daily = scores.daily || scores.weekly || 75;
    const arc = document.getElementById('score-arc');
    const num = document.getElementById('score-num');
    const desc = document.getElementById('score-desc');

    num.textContent = daily.toFixed(0);
    document.getElementById('score-weekly').textContent = (scores.weekly || '--');
    document.getElementById('score-monthly').textContent = (scores.monthly || '--');

    // Animate arc
    const circumference = 213.6;
    const offset = circumference - (daily / 100) * circumference;
    arc.style.strokeDashoffset = offset;

    // Color based on score
    if (daily >= 80) { arc.style.stroke = 'var(--green)'; desc.textContent = 'Excellent health today! 🌟'; }
    else if (daily >= 60) { arc.style.stroke = 'var(--cyan)'; desc.textContent = 'Good health. Keep it up! 👍'; }
    else if (daily >= 40) { arc.style.stroke = 'var(--yellow)'; desc.textContent = 'Moderate — check in tonight'; }
    else { arc.style.stroke = 'var(--red)'; desc.textContent = 'Needs attention. See a doctor.'; }
  } catch (e) {
    document.getElementById('score-num').textContent = '--';
  }
}

window.loadVitalStats = async function(days = 7) {
  try {
    const data = await api.getVitalStats(days);
    renderTrendChart(data.days || []);
  } catch (e) {
    // Silent
  }
};

function renderTrendChart(days) {
  const canvas = document.getElementById('trend-chart');
  if (!canvas) return;

  if (trendChart) trendChart.destroy();

  // Inline mini chart using Canvas API (no external library needed)
  const ctx = canvas.getContext('2d');
  const W = canvas.offsetWidth || 300;
  const H = canvas.offsetHeight || 120;
  canvas.width = W * window.devicePixelRatio;
  canvas.height = H * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

  if (!days || days.length === 0) {
    ctx.fillStyle = 'rgba(90, 122, 138, 0.5)';
    ctx.font = '12px Space Mono';
    ctx.textAlign = 'center';
    ctx.fillText('No data yet — submit vitals to see trends', W / 2, H / 2);
    return;
  }

  const labels = days.map(d => d.date.slice(5)); // MM-DD
  const hrData = days.map(d => d.avg_heart_rate || 0);
  const spo2Data = days.map(d => d.avg_spo2 || 0);

  const padX = 40, padY = 16;
  const chartW = W - padX * 2;
  const chartH = H - padY * 2;
  const n = labels.length;

  function getY(val, min, max) {
    return padY + chartH - ((val - min) / (max - min || 1)) * chartH;
  }

  function drawLine(data, color, min, max) {
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    data.forEach((v, i) => {
      const x = padX + (i / (n - 1 || 1)) * chartW;
      const y = getY(v, min, max);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Dots
    data.forEach((v, i) => {
      const x = padX + (i / (n - 1 || 1)) * chartW;
      const y = getY(v, min, max);
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    });
  }

  // Grid lines
  ctx.strokeStyle = 'rgba(0,229,255,0.06)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padY + (i / 4) * chartH;
    ctx.beginPath(); ctx.moveTo(padX, y); ctx.lineTo(W - padX, y); ctx.stroke();
  }

  // X labels
  ctx.fillStyle = 'rgba(90,122,138,0.8)';
  ctx.font = '9px Space Mono';
  ctx.textAlign = 'center';
  labels.forEach((lbl, i) => {
    const x = padX + (i / (n - 1 || 1)) * chartW;
    ctx.fillText(lbl, x, H - 2);
  });

  const hrMin = Math.min(...hrData) - 10, hrMax = Math.max(...hrData) + 10;
  drawLine(hrData, '#ff3366', hrMin, hrMax);
  drawLine(spo2Data.map(v => v - 80), '#00e5ff', 0, 20); // normalize SpO2 to same scale

  // Legend
  ctx.fillStyle = '#ff3366'; ctx.fillRect(padX, 4, 10, 3);
  ctx.fillStyle = 'rgba(90,122,138,0.8)'; ctx.font = '8px Space Mono';
  ctx.textAlign = 'left'; ctx.fillText('HR', padX + 13, 9);
  ctx.fillStyle = '#00e5ff'; ctx.fillRect(padX + 35, 4, 10, 3);
  ctx.fillStyle = 'rgba(90,122,138,0.8)'; ctx.fillText('SpO2', padX + 48, 9);
}

// ── Manual Vitals ──────────────────────────────────────────────────────────────
window.submitManualVitals = async function() {
  const hr = parseFloat(document.getElementById('m-hr').value);
  const spo2 = parseFloat(document.getElementById('m-spo2').value);
  const temp = parseFloat(document.getElementById('m-temp').value);
  const sys = parseFloat(document.getElementById('m-bp').value) || 120;

  if (!hr || !spo2 || !temp) return showToast('Fill in at least HR, SpO2, and Temp', 'error');

  try {
    const result = await api.submitVitals({
      heart_rate: hr, spo2, temperature: temp,
      systolic_bp: sys, diastolic_bp: sys * 0.67,
      source: 'manual'
    });
    updateVitalDisplay({ heart_rate: hr, spo2, temperature: temp, systolic_bp: sys, diastolic_bp: sys * 0.67, health_status: result.status });
    showToast(`Vitals saved — Status: ${result.status.toUpperCase()}`, result.status === 'healthy' ? 'success' : 'error');

    if (result.emergency) {
      triggerEmergencyBanner({ message: result.analysis.notes, flags: result.analysis.emergency_flags });
    }

    loadHealthScore();
    loadVitalStats(7);
  } catch (e) {
    showToast(e.message || 'Failed to submit vitals', 'error');
  }
};

window.submitDemoVitals = async function() {
  // Simulate realistic vital signs
  const demo = {
    heart_rate: 68 + Math.random() * 15,
    spo2: 97 + Math.random() * 2,
    temperature: 36.5 + Math.random() * 0.8,
    systolic_bp: 115 + Math.random() * 15,
    diastolic_bp: 75 + Math.random() * 10,
    ecg_value: 0.45 + Math.random() * 0.1,
    source: 'simulator'
  };
  document.getElementById('m-hr').value = demo.heart_rate.toFixed(0);
  document.getElementById('m-spo2').value = demo.spo2.toFixed(1);
  document.getElementById('m-temp').value = demo.temperature.toFixed(1);
  document.getElementById('m-bp').value = demo.systolic_bp.toFixed(0);

  try {
    const result = await api.submitVitals(demo);
    updateVitalDisplay({ ...demo, health_status: result.status });
    showToast(`Demo vitals: ${result.status.toUpperCase()} (${(result.analysis.confidence * 100).toFixed(0)}% confidence)`, 'success');
    loadHealthScore();
    loadVitalStats(7);
  } catch (e) {
    showToast('Connect backend to test: ' + e.message, 'error');
  }
};

// ── Alerts ─────────────────────────────────────────────────────────────────────
window.loadAlerts = async function() {
  const container = document.getElementById('alerts-list');
  container.innerHTML = '<div class="center"><div class="spinner"></div></div>';

  try {
    const alerts = await api.getAlerts();
    unreadAlerts = 0;
    document.getElementById('alert-count').style.display = 'none';
    document.getElementById('nav-dot-alerts').classList.remove('visible');

    if (alerts.length === 0) {
      container.innerHTML = `<div class="empty-state"><div class="icon">✅</div><p>No alerts yet. You're in great health!</p></div>`;
      return;
    }

    container.innerHTML = alerts.map(a => `
      <div class="alert-item ${a.severity}" id="alert-${a.id}">
        <div class="alert-top">
          <span class="alert-type text-${a.severity === 'emergency' ? 'red' : a.severity === 'warning' ? 'yellow' : 'cyan'}">${a.alert_type.replace(/_/g, ' ')}</span>
          <span class="alert-time">${formatTime(a.created_at)}</span>
        </div>
        <p class="alert-msg">${a.message}</p>
        ${!a.is_acknowledged ? `<button class="btn btn-ghost btn-sm" style="margin-top:8px" onclick="ackAlert(${a.id})">Acknowledge</button>` : '<span style="font-size:11px;color:var(--text-dim);font-family:var(--mono)">✓ ACKNOWLEDGED</span>'}
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p>Failed to load alerts. Check backend connection.</p></div>`;
  }
};

window.ackAlert = async function(id) {
  try {
    await api.acknowledgeAlert(id);
    document.getElementById(`alert-${id}`).querySelector('button')?.replaceWith(
      Object.assign(document.createElement('span'), { textContent: '✓ ACKNOWLEDGED', style: 'font-size:11px;color:var(--text-dim);font-family:var(--mono)' })
    );
    showToast('Alert acknowledged', 'success');
  } catch (e) {
    showToast('Failed to acknowledge', 'error');
  }
};

// ── Check-in Modal ─────────────────────────────────────────────────────────────
window.openCheckinModal = async function() {
  try {
    const { questions } = await api.getCheckinQuestions();
    const container = document.getElementById('checkin-questions');
    container.innerHTML = questions.map(q => `
      <div class="checkin-q">
        <label>${q.question}</label>
        ${q.type === 'text' ? `<textarea id="ci-${q.id}" placeholder="Type here..." rows="2"></textarea>` :
          q.type === 'select' ? `<select id="ci-${q.id}">${q.options.map(o => `<option>${o}</option>`).join('')}</select>` :
          `<div class="slider-row">
            <input type="range" id="ci-${q.id}" min="${q.min||0}" max="${q.max||10}" value="${Math.floor(((q.min||0)+(q.max||10))/2)}" oninput="this.nextElementSibling.textContent=this.value">
            <span class="slider-val">${Math.floor(((q.min||0)+(q.max||10))/2)}</span>
          </div>`
        }
      </div>
    `).join('');
    document.getElementById('checkin-result').innerHTML = '';
    openModal('modal-checkin');
  } catch (e) {
    showToast('Failed to load questions — check backend', 'error');
  }
};

window.submitCheckin = async function() {
  const btn = document.getElementById('checkin-submit-btn');
  btn.textContent = 'Analyzing... 🔬'; btn.disabled = true;

  const data = {
    food: document.getElementById('ci-food')?.value || '',
    symptoms: document.getElementById('ci-symptoms')?.value || '',
    diet: document.getElementById('ci-diet')?.value || '',
    sleep_hours: parseFloat(document.getElementById('ci-sleep_hours')?.value || 7),
    exercise_minutes: parseFloat(document.getElementById('ci-exercise_minutes')?.value || 0),
    stress_level: parseInt(document.getElementById('ci-stress_level')?.value || 5),
    water_intake: parseFloat(document.getElementById('ci-water_intake')?.value || 8),
  };

  try {
    const result = await api.submitCheckin(data);
    const analysis = result.analysis;
    const score = result.health_score;

    const warningColors = { green: 'var(--green)', yellow: 'var(--yellow)', orange: '#ff8c00', red: 'var(--red)' };
    const warnColor = warningColors[analysis.warning_level] || 'var(--cyan)';

    document.getElementById('checkin-result').innerHTML = `
      <div style="border:1px solid ${warnColor};border-radius:12px;padding:16px;background:${warnColor}15">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <span style="font-weight:800;font-size:15px">Daily Analysis</span>
          <span style="font-size:24px;font-weight:800;font-family:var(--mono);color:${warnColor}">${score.toFixed(0)}</span>
        </div>
        <p style="font-size:13px;color:var(--text-mid);margin-bottom:12px">${analysis.overall_assessment || ''}</p>
        ${(analysis.recommendations || []).length > 0 ? `
          <div style="margin-top:8px">
            <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin-bottom:6px">RECOMMENDATIONS</p>
            ${analysis.recommendations.map(r => `<div style="font-size:12px;color:var(--text);padding:4px 0;border-bottom:1px solid var(--border)">→ ${r}</div>`).join('')}
          </div>
        ` : ''}
        ${analysis.diet_advice ? `<p style="font-size:12px;color:var(--text-mid);margin-top:10px">🥗 ${analysis.diet_advice}</p>` : ''}
        ${analysis.follow_up_needed ? `<p style="font-size:12px;color:var(--red);margin-top:8px">⚠️ ${analysis.follow_up_reason}</p>` : ''}
      </div>
    `;
    loadHealthScore();
    showToast(`Check-in complete! Score: ${score.toFixed(0)}/100`, 'success');
  } catch (e) {
    document.getElementById('checkin-result').innerHTML = `<p style="color:var(--red);font-size:13px">${e.message}</p>`;
    showToast('Check-in failed: ' + e.message, 'error');
  } finally {
    btn.textContent = 'Analyze My Health'; btn.disabled = false;
  }
};

// ── AI Prescription ─────────────────────────────────────────────────────────────
window.openAIPrescription = function() {
  document.getElementById('rx-symptoms').value = '';
  document.getElementById('rx-result').innerHTML = '';
  openModal('modal-rx');
};

window.submitRxRequest = async function() {
  const symptoms = document.getElementById('rx-symptoms').value.trim();
  if (!symptoms) return showToast('Describe your symptoms first', 'error');

  const btn = document.getElementById('rx-btn');
  btn.textContent = 'Consulting AI... 🤖'; btn.disabled = true;

  try {
    const result = await api.getAiPrescription(symptoms);

    if (!result.can_treat_at_home) {
      document.getElementById('rx-result').innerHTML = `
        <div style="background:var(--red-dim);border:1px solid var(--red);border-radius:10px;padding:14px">
          <p style="font-size:14px;font-weight:700;color:var(--red)">⚠️ Please see a doctor</p>
          <p style="font-size:13px;color:var(--text-mid);margin-top:6px">${result.condition_assessment}</p>
        </div>`;
      return;
    }

    const meds = result.medicines || [];
    document.getElementById('rx-result').innerHTML = `
      <div class="rx-card">
        <p style="font-size:13px;font-weight:700;color:var(--cyan);margin-bottom:10px">${result.condition_assessment}</p>
        ${meds.length > 0 ? `
          <p style="font-size:10px;font-family:var(--mono);color:var(--text-dim);margin-bottom:8px">MEDICATIONS</p>
          ${meds.map(m => `
            <div class="med-item">
              <div class="med-name">${m.name}</div>
              <div class="med-dose">${m.dosage} · ${m.frequency} · ${m.duration}</div>
              ${m.notes ? `<div style="font-size:11px;color:var(--text-dim);margin-top:2px">${m.notes}</div>` : ''}
            </div>`).join('')}
        ` : ''}
        ${(result.home_remedies || []).length > 0 ? `
          <div style="margin-top:12px">
            <p style="font-size:10px;font-family:var(--mono);color:var(--text-dim);margin-bottom:6px">HOME REMEDIES</p>
            ${result.home_remedies.map(r => `<p style="font-size:12px;color:var(--text-mid)">• ${r}</p>`).join('')}
          </div>` : ''}
        <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
          <p style="font-size:10px;color:var(--text-dim)">SEE A DOCTOR IF:</p>
          ${(result.see_doctor_if || []).map(r => `<p style="font-size:11px;color:var(--yellow)">⚠️ ${r}</p>`).join('')}
        </div>
        <p style="font-size:10px;color:var(--text-dim);margin-top:10px;font-style:italic">${result.disclaimer}</p>
      </div>`;
  } catch (e) {
    document.getElementById('rx-result').innerHTML = `<p style="color:var(--red);font-size:13px">${e.message}</p>`;
  } finally {
    btn.textContent = 'Get AI Advice'; btn.disabled = false;
  }
};

// ── Hospital ───────────────────────────────────────────────────────────────────
async function loadHospitals(city = '') {
  const container = document.getElementById('hospital-list');
  container.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const hospitals = await api.listHospitals(city ? { city } : {});
    if (hospitals.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="icon">🏥</div><p>No hospitals found. Try a different city.</p></div>';
      return;
    }
    container.innerHTML = hospitals.map(h => `
      <div class="hospital-card" onclick="showHospitalDetail(${h.id})">
        <div class="hospital-name">${h.name}</div>
        <div class="hospital-meta">📍 ${h.address || ''}, ${h.city || ''} · 📞 ${h.phone || 'N/A'}</div>
        <div class="bed-grid">
          ${['general','semi_special','special','icu'].map(type => {
            const b = h.beds[type];
            return `<div class="bed-item ${b.available === 0 ? 'no-avail' : ''}">
              <div class="bed-avail">${b.available}</div>
              <div class="bed-type">${type.replace('_',' ').toUpperCase()}</div>
              <div style="font-size:9px;color:var(--text-dim);font-family:var(--mono)">₹${b.price_per_day || 0}/d</div>
            </div>`;
          }).join('')}
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${h.has_ambulance ? '<span style="font-size:10px;background:var(--green-dim);color:var(--green);padding:3px 8px;border-radius:10px;font-family:var(--mono)">🚑 Ambulance</span>' : ''}
          ${(h.specializations||[]).slice(0,2).map(s => `<span style="font-size:10px;background:var(--cyan-dim);color:var(--cyan);padding:3px 8px;border-radius:10px;font-family:var(--mono)">${s}</span>`).join('')}
        </div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p>Failed to load hospitals. ${e.message}</p></div>`;
  }
}

window.searchHospitals = function() {
  const city = document.getElementById('hospital-search').value.trim();
  loadHospitals(city);
};

window.showHospitalDetail = async function(id) {
  const body = document.getElementById('hospital-modal-body');
  body.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  openModal('modal-hospital');

  try {
    const h = await api.getHospital(id);
    document.getElementById('hospital-modal-name').textContent = h.name;

    body.innerHTML = `
      <p style="font-size:12px;color:var(--text-mid);margin-bottom:14px">📍 ${h.address}, ${h.city} · 📞 ${h.phone}</p>
      <div class="bed-grid" style="margin-bottom:16px">
        ${Object.entries(h.beds).map(([type, b]) => `
          <div class="bed-item ${b.available === 0 ? 'no-avail' : ''}">
            <div class="bed-avail">${b.available}/${b.total}</div>
            <div class="bed-type">${type.replace('_',' ')}</div>
            <div style="font-size:9px;color:var(--text-dim);font-family:var(--mono)">₹${b.price_per_day || 0}/day</div>
          </div>`).join('')}
      </div>
      <div style="font-size:12px;color:var(--text-mid);margin-bottom:16px">
        <span>Consultation: <strong class="text-cyan">₹${h.consultation_fee || 0}</strong></span>
        ${h.has_ambulance ? `&nbsp;·&nbsp;<span>Ambulance: <strong class="text-cyan">₹${h.ambulance_fee || 0}</strong></span>` : ''}
      </div>

      <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin-bottom:10px">BOOK APPOINTMENT</p>
      <select id="book-type" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;margin-bottom:8px;outline:none">
        <option value="consultation">Consultation</option>
        <option value="admission">Admission</option>
        <option value="emergency">Emergency</option>
      </select>
      <select id="book-bed" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;margin-bottom:8px;outline:none">
        <option value="">No bed required</option>
        <option value="general">General (₹${h.beds.general.price_per_day}/day)</option>
        <option value="semi_special">Semi-Special (₹${h.beds.semi_special.price_per_day}/day)</option>
        <option value="special">Special (₹${h.beds.special.price_per_day}/day)</option>
        <option value="icu">ICU (₹${h.beds.icu.price_per_day}/day)</option>
      </select>
      <label style="display:flex;align-items:center;gap:8px;margin-bottom:12px;font-size:13px;cursor:pointer">
        <input type="checkbox" id="book-ambulance" ${!h.has_ambulance ? 'disabled' : ''}> Request Ambulance ${h.has_ambulance ? `(₹${h.ambulance_fee})` : '(N/A)'}
      </label>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" style="flex:1" onclick="bookHospital(${id})">Book Now</button>
        <button class="btn btn-ghost btn-sm" onclick="estimateBudget(${id})">💰 Estimate</button>
      </div>
      <div id="budget-result" style="margin-top:12px"></div>
      <div id="booking-result" style="margin-top:12px"></div>
    `;
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">${e.message}</p>`;
  }
};

window.bookHospital = async function(hospitalId) {
  const bookingType = document.getElementById('book-type').value;
  const bedType = document.getElementById('book-bed').value || null;
  const ambulance = document.getElementById('book-ambulance').checked;

  try {
    const result = await api.bookHospital({ hospital_id: hospitalId, booking_type: bookingType, bed_type: bedType, ambulance_requested: ambulance });
    document.getElementById('booking-result').innerHTML = `
      <div style="background:var(--green-dim);border:1px solid rgba(0,255,135,0.2);border-radius:10px;padding:12px">
        <p style="font-size:13px;font-weight:700;color:var(--green)">✅ Booking Confirmed!</p>
        <p style="font-size:12px;color:var(--text-mid);margin-top:4px">ID: #${result.booking_id} · Est. Cost: ₹${result.estimated_cost?.toFixed(0) || 0}</p>
        ${result.ambulance_requested ? '<p style="font-size:12px;color:var(--yellow);margin-top:4px">🚑 Ambulance requested</p>' : ''}
      </div>`;
    showToast('Booking confirmed!', 'success');
  } catch (e) {
    showToast(e.message || 'Booking failed', 'error');
  }
};

window.estimateBudget = async function(hospitalId) {
  const diagnosis = prompt('Enter diagnosis/condition for budget estimate:');
  if (!diagnosis) return;

  try {
    const result = await api.estimateBudget({ hospital_id: hospitalId, diagnosis });
    document.getElementById('budget-result').innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px">
        <p style="font-size:12px;font-weight:700;margin-bottom:8px">💰 Budget Estimate for "${diagnosis}"</p>
        <p style="font-size:18px;font-weight:800;font-family:var(--mono);color:var(--cyan)">₹${result.estimated_min?.toLocaleString()} – ₹${result.estimated_max?.toLocaleString()}</p>
        ${result.insurance_tip ? `<p style="font-size:11px;color:var(--text-dim);margin-top:6px">💡 ${result.insurance_tip}</p>` : ''}
        ${(result.cost_saving_tips || []).map(t => `<p style="font-size:11px;color:var(--text-mid)">• ${t}</p>`).join('')}
      </div>`;
  } catch (e) {
    showToast(e.message, 'error');
  }
};

// ── Pharmacy ───────────────────────────────────────────────────────────────────
window.switchTab = function(btn, tabId) {
  btn.closest('.page').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.closest('.page').querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(tabId).classList.add('active');
};

async function loadBloodGroups() {
  try {
    bloodGroupData = await api.getAllBloodGroups();
    renderBloodGrid();
  } catch (e) {
    // Silent fail
  }
}

function renderBloodGrid(selectedGroup = null) {
  const GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];
  const grid = document.getElementById('blood-grid');
  if (!grid) return;
  grid.innerHTML = GROUPS.map(bg => `
    <div class="blood-btn ${selectedGroup === bg ? 'selected' : ''}" onclick="searchBloodGroup('${bg}')">
      <div class="blood-type">${bg}</div>
      <div class="blood-units">${bloodGroupData[bg] || 0} banks</div>
    </div>
  `).join('');
}

window.searchBloodGroup = async function(bloodGroup) {
  renderBloodGrid(bloodGroup);
  const container = document.getElementById('blood-results');
  container.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const results = await api.searchBlood(bloodGroup);
    if (results.length === 0) {
      container.innerHTML = `<div class="empty-state"><p>No ${bloodGroup} blood available nearby.</p></div>`;
      return;
    }
    container.innerHTML = results.map(r => `
      <div class="result-card">
        <div class="result-name">${r.blood_bank.name}</div>
        <div class="result-meta">📍 ${r.blood_bank.address} · 📞 ${r.blood_bank.phone}</div>
        <div class="result-price">${r.units_available} units of ${r.blood_group} available</div>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = `<p style="color:var(--red);font-size:13px">${e.message}</p>`;
  }
};

window.searchMedicine = async function() {
  const name = document.getElementById('med-search').value.trim();
  if (!name) return showToast('Enter a medicine name', 'error');

  const container = document.getElementById('medicine-results');
  container.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const results = await api.searchMedicine(name);
    if (results.length === 0) {
      container.innerHTML = `<div class="empty-state"><p>No results for "${name}"</p></div>`;
      return;
    }
    container.innerHTML = results.map(r => `
      <div class="result-card">
        <div class="result-name">${r.medicine_name}</div>
        <div style="font-size:11px;color:var(--text-dim);font-family:var(--mono)">${r.generic_name || ''}</div>
        <div class="result-meta">📍 ${r.pharmacy.name} · ${r.pharmacy.city} · 📞 ${r.pharmacy.phone}</div>
        <div class="result-price">₹${r.price_per_unit}/${r.unit} · ${r.quantity_available} in stock ${r.requires_prescription ? '· 📋 Rx needed' : ''}</div>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = `<p style="color:var(--red);font-size:13px">${e.message}</p>`;
  }
};

window.searchPharmacies = async function() {
  const city = document.getElementById('pharm-city').value.trim();
  const container = document.getElementById('pharmacy-list-results');
  container.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const pharmacies = await api.listPharmacies(city ? { city } : {});
    if (pharmacies.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No pharmacies found.</p></div>';
      return;
    }
    container.innerHTML = pharmacies.map(p => `
      <div class="result-card">
        <div class="result-name">${p.name} ${p.is_blood_bank ? '🩸' : '💊'}</div>
        <div class="result-meta">📍 ${p.address} · ${p.city} · 📞 ${p.phone}</div>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = `<p style="color:var(--red);font-size:13px">${e.message}</p>`;
  }
};

// ── Profile Page ───────────────────────────────────────────────────────────────
async function loadProfilePage() {
  const user = auth.getUser();
  if (!user) return;

  document.getElementById('pf-name').textContent = user.name || 'User';
  document.getElementById('pf-role').textContent = user.role?.toUpperCase() || 'PATIENT';

  try {
    const profile = await api.getProfile();
    document.getElementById('pf-email').textContent = profile.email;
  } catch (e) {}

  // Show role-specific sections
  document.getElementById('patient-sections').style.display = user.role === 'patient' ? 'block' : 'none';
  document.getElementById('hospital-sections').style.display = user.role === 'hospital' ? 'block' : 'none';
  document.getElementById('pharmacy-sections').style.display = ['pharmacy', 'blood_bank'].includes(user.role) ? 'block' : 'none';
}

window.openProfileEdit = async function() {
  try {
    const profile = await api.getProfile();
    const p = profile.profile;
    const modal = document.createElement('div');
    modal.className = 'modal-backdrop open';
    modal.innerHTML = `
      <div class="modal">
        <div class="modal-hdr">
          <h3>Medical Profile</h3>
          <button class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px">
          ${[
            ['Date of Birth', 'pf-dob', 'date', p.date_of_birth || ''],
            ['Blood Group', 'pf-bg', 'text', p.blood_group || ''],
            ['Gender', 'pf-gender', 'text', p.gender || ''],
            ['Height (cm)', 'pf-height', 'number', p.height_cm || ''],
            ['Weight (kg)', 'pf-weight', 'number', p.weight_kg || ''],
            ['Emergency Contact Name', 'pf-ecname', 'text', p.emergency_contact_name || ''],
            ['Emergency Contact Phone', 'pf-ecphone', 'tel', p.emergency_contact_phone || ''],
            ['Device ID (IoT)', 'pf-device', 'text', p.device_id || ''],
          ].map(([lbl, id, type, val]) => `
            <div class="form-group">
              <label>${lbl}</label>
              <input type="${type}" id="${id}" value="${val}" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;font-family:var(--display)">
            </div>`).join('')}
          <div class="form-group">
            <label>Known Allergies</label>
            <textarea id="pf-allergies" rows="2" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;resize:vertical;font-family:var(--display)">${p.allergies || ''}</textarea>
          </div>
          <button class="btn btn-primary btn-block" onclick="saveProfile(this)">Save Profile</button>
        </div>
      </div>`;
    document.getElementById('app').appendChild(modal);
  } catch (e) {
    showToast('Failed to load profile', 'error');
  }
};

window.saveProfile = async function(btn) {
  btn.textContent = 'Saving...'; btn.disabled = true;
  try {
    await api.updateProfile({
      date_of_birth: document.getElementById('pf-dob')?.value || null,
      blood_group: document.getElementById('pf-bg')?.value || null,
      gender: document.getElementById('pf-gender')?.value || null,
      height_cm: parseFloat(document.getElementById('pf-height')?.value) || null,
      weight_kg: parseFloat(document.getElementById('pf-weight')?.value) || null,
      emergency_contact_name: document.getElementById('pf-ecname')?.value || null,
      emergency_contact_phone: document.getElementById('pf-ecphone')?.value || null,
      device_id: document.getElementById('pf-device')?.value || null,
      allergies: document.getElementById('pf-allergies')?.value || null,
    });
    btn.closest('.modal-backdrop').remove();
    showToast('Profile updated!', 'success');
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.textContent = 'Save Profile'; btn.disabled = false;
  }
};

// ── Family Manager ─────────────────────────────────────────────────────────────
window.openFamilyManager = async function() {
  openModal('modal-family');
  await refreshFamilyList();
};

async function refreshFamilyList() {
  const container = document.getElementById('family-list');
  try {
    const members = await api.getFamily();
    if (members.length === 0) {
      container.innerHTML = '<p style="font-size:13px;color:var(--text-dim);text-align:center;padding:16px">No family members added yet</p>';
      return;
    }
    container.innerHTML = members.map(m => `
      <div class="family-item">
        <div class="family-left">
          <div class="family-avatar">👤</div>
          <div>
            <div class="family-name">${m.member_name}</div>
            <div class="family-rel">${m.relationship_type} · ${m.member_phone}</div>
          </div>
        </div>
        <button class="family-del" onclick="removeFamilyMember(${m.id})">✕</button>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = `<p style="color:var(--red);font-size:13px">${e.message}</p>`;
  }
}

window.addFamilyMember = async function() {
  const name = document.getElementById('fam-name').value.trim();
  const phone = document.getElementById('fam-phone').value.trim();
  const rel = document.getElementById('fam-rel').value;
  if (!name || !phone) return showToast('Name and phone required', 'error');

  try {
    await api.addFamilyMember({ member_name: name, member_phone: phone, relationship_type: rel });
    document.getElementById('fam-name').value = '';
    document.getElementById('fam-phone').value = '';
    await refreshFamilyList();
    showToast(`${name} added`, 'success');
  } catch (e) {
    showToast(e.message, 'error');
  }
};

window.removeFamilyMember = async function(id) {
  try {
    await api.removeFamilyMember(id);
    await refreshFamilyList();
    showToast('Removed', 'info');
  } catch (e) {
    showToast(e.message, 'error');
  }
};

// ── Digital Records ────────────────────────────────────────────────────────────
window.openDigitalRecords = async function() {
  openModal('modal-records');
  const container = document.getElementById('records-content');
  container.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const data = await api.getRecords();
    const rxs = data.prescriptions || [];
    const labs = data.lab_reports || [];

    container.innerHTML = `
      <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin-bottom:10px">PRESCRIPTIONS (${rxs.length})</p>
      ${rxs.length === 0 ? '<p style="font-size:13px;color:var(--text-dim)">No prescriptions yet</p>' : rxs.map(rx => `
        <div class="rx-card" style="margin-bottom:10px">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px">
            <span style="font-size:12px;font-weight:700">${rx.prescribed_by}</span>
            <span style="font-size:10px;font-family:var(--mono);color:var(--text-dim)">${rx.valid_until || ''}</span>
          </div>
          <p style="font-size:12px;color:var(--text-mid)">${rx.diagnosis || 'General'}</p>
          ${rx.is_ai_generated ? '<span style="font-size:10px;background:var(--cyan-dim);color:var(--cyan);padding:2px 6px;border-radius:6px;font-family:var(--mono)">AI GENERATED</span>' : ''}
        </div>`).join('')}
      <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin:16px 0 10px">LAB REPORTS (${labs.length})</p>
      ${labs.length === 0 ? '<p style="font-size:13px;color:var(--text-dim)">No lab reports uploaded</p>' : labs.map(r => `
        <div class="rx-card">
          <div style="font-size:13px;font-weight:700">${r.report_type}</div>
          <div style="font-size:11px;color:var(--text-dim);font-family:var(--mono)">${r.report_date}</div>
        </div>`).join('')}
    `;
  } catch (e) {
    container.innerHTML = `<p style="color:var(--red)">${e.message}</p>`;
  }
};

// ── Hospital Management ────────────────────────────────────────────────────────
window.openHospitalMgmt = async function() {
  openModal('modal-hospital-mgmt');
  const body = document.getElementById('hospital-mgmt-body');
  body.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const h = await api.getHospitalProfile();
    body.innerHTML = `
      <p style="font-size:12px;color:var(--text-mid);margin-bottom:16px">Update bed availability and pricing</p>
      ${[
        ['General Beds Available', 'hm-gen-avail', h.beds?.general?.available || 0],
        ['Semi-Special Beds Available', 'hm-semi-avail', h.beds?.semi_special?.available || 0],
        ['Special Beds Available', 'hm-spec-avail', h.beds?.special?.available || 0],
        ['ICU Beds Available', 'hm-icu-avail', h.beds?.icu?.available || 0],
        ['Consultation Fee (₹)', 'hm-consult', h.consultation_fee || 0],
        ['Ambulance Fee (₹)', 'hm-ambulance', h.ambulance_fee || 0],
      ].map(([lbl, id, val]) => `
        <div class="form-group" style="margin-bottom:10px">
          <label style="font-size:11px;font-family:var(--mono);color:var(--text-dim);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px;display:block">${lbl}</label>
          <input type="number" id="${id}" value="${val}" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;width:100%;font-family:var(--display)">
        </div>`).join('')}
      <button class="btn btn-primary btn-block" onclick="saveHospitalData(this)">Save Changes</button>
    `;
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">${e.message}</p>`;
  }
};

window.saveHospitalData = async function(btn) {
  btn.textContent = 'Saving...'; btn.disabled = true;
  try {
    await api.updateHospitalProfile({
      general_beds_available: parseInt(document.getElementById('hm-gen-avail').value),
      semi_special_beds_available: parseInt(document.getElementById('hm-semi-avail').value),
      special_beds_available: parseInt(document.getElementById('hm-spec-avail').value),
      icu_beds_available: parseInt(document.getElementById('hm-icu-avail').value),
      consultation_fee: parseFloat(document.getElementById('hm-consult').value),
      ambulance_fee: parseFloat(document.getElementById('hm-ambulance').value),
    });
    showToast('Hospital data updated!', 'success');
    closeModal('modal-hospital-mgmt');
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.textContent = 'Save Changes'; btn.disabled = false;
  }
};

window.openIncomingBookings = async function() {
  openModal('modal-bookings');
  const body = document.getElementById('bookings-body');
  body.innerHTML = '<div class="center"><div class="spinner"></div></div>';
  try {
    const bookings = await api.getIncomingBookings();
    if (bookings.length === 0) {
      body.innerHTML = '<div class="empty-state"><p>No bookings yet</p></div>';
      return;
    }
    body.innerHTML = bookings.map(b => `
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;margin-bottom:6px">
          <span style="font-size:13px;font-weight:700">#${b.id} — ${b.booking_type}</span>
          <span style="font-size:11px;font-family:var(--mono);color:${b.status==='confirmed'?'var(--green)':b.status==='pending'?'var(--yellow)':'var(--text-dim)'}">${b.status.toUpperCase()}</span>
        </div>
        <p style="font-size:12px;color:var(--text-mid)">Patient ID: ${b.patient_id} · ₹${b.estimated_cost || 0}</p>
        ${b.ambulance_requested ? '<p style="font-size:11px;color:var(--yellow)">🚑 Ambulance requested</p>' : ''}
        ${b.status === 'pending' ? `
          <div style="display:flex;gap:6px;margin-top:10px">
            <button class="btn btn-primary btn-sm" onclick="updateBooking(${b.id},'confirmed')">Confirm</button>
            <button class="btn btn-ghost btn-sm" onclick="updateBooking(${b.id},'cancelled')">Cancel</button>
          </div>` : ''}
      </div>`).join('');
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">${e.message}</p>`;
  }
};

window.updateBooking = async function(id, status) {
  try {
    await api.updateBookingStatus(id, status);
    showToast(`Booking ${status}`, 'success');
    openIncomingBookings();
  } catch (e) {
    showToast(e.message, 'error');
  }
};

// ── Pharmacy Management ────────────────────────────────────────────────────────
window.openPharmacyMgmt = async function() {
  openModal('modal-pharmacy-mgmt');
  const body = document.getElementById('pharmacy-mgmt-body');
  body.innerHTML = '<div class="center"><div class="spinner"></div></div>';

  const user = auth.getUser();
  const isBloodBank = user?.role === 'blood_bank';

  try {
    let content = '';

    if (!isBloodBank) {
      // Medicine inventory
      const meds = await api.getMyInventory();
      content += `
        <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin-bottom:10px">CURRENT INVENTORY (${meds.length} items)</p>
        <div style="max-height:200px;overflow-y:auto;margin-bottom:16px">
          ${meds.map(m => `
            <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:12px">
              <span>${m.medicine_name}</span>
              <span style="font-family:var(--mono);color:var(--cyan)">${m.quantity_available} ${m.unit}s</span>
            </div>`).join('') || '<p style="color:var(--text-dim);font-size:12px">No inventory yet</p>'}
        </div>
        <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin-bottom:10px">ADD / UPDATE MEDICINE</p>
        <div style="display:flex;flex-direction:column;gap:8px">
          <input type="text" id="pm-name" placeholder="Medicine name" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;font-family:var(--display)">
          <input type="text" id="pm-generic" placeholder="Generic name" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;font-family:var(--display)">
          <input type="number" id="pm-qty" placeholder="Quantity available" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;font-family:var(--display)">
          <input type="number" id="pm-price" placeholder="Price per unit (₹)" style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;font-family:var(--display)">
          <button class="btn btn-primary btn-sm" onclick="saveMedicine()">Add / Update</button>
        </div>`;
    }

    // Blood inventory (for blood banks)
    if (isBloodBank || true) {
      const blood = await api.getMyBloodInventory().catch(() => []);
      const GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'];
      content += `
        <p style="font-size:11px;font-family:var(--mono);color:var(--text-dim);margin:16px 0 10px">BLOOD INVENTORY</p>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:12px">
          ${GROUPS.map(bg => {
            const inv = blood.find(b => b.blood_group === bg);
            return `<div style="text-align:center;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:8px">
              <div style="font-size:14px;font-weight:700;font-family:var(--mono);color:var(--cyan)">${bg}</div>
              <div style="font-size:11px;color:var(--text-dim)">${inv?.units_available || 0}u</div>
            </div>`;
          }).join('')}
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <select id="pb-group" style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none">
            ${GROUPS.map(bg => `<option value="${bg}">${bg}</option>`).join('')}
          </select>
          <input type="number" id="pb-units" placeholder="Units" style="flex:1;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;color:var(--text);font-size:13px;outline:none;font-family:var(--display)">
          <button class="btn btn-primary btn-sm" onclick="saveBlood()">Update</button>
        </div>`;
    }

    body.innerHTML = content;
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">${e.message}</p>`;
  }
};

window.saveMedicine = async function() {
  const name = document.getElementById('pm-name')?.value.trim();
  const qty = parseInt(document.getElementById('pm-qty')?.value);
  const price = parseFloat(document.getElementById('pm-price')?.value);
  if (!name || !qty || !price) return showToast('Fill all fields', 'error');

  try {
    await api.addMedicine({ medicine_name: name, generic_name: document.getElementById('pm-generic')?.value || '', quantity_available: qty, price_per_unit: price, unit: 'tablet' });
    showToast(`${name} updated`, 'success');
    openPharmacyMgmt();
  } catch (e) { showToast(e.message, 'error'); }
};

window.saveBlood = async function() {
  const group = document.getElementById('pb-group')?.value;
  const units = parseInt(document.getElementById('pb-units')?.value);
  if (!units) return showToast('Enter units', 'error');
  try {
    await api.updateBloodInventory({ blood_group: group, units_available: units });
    showToast(`${group} inventory updated`, 'success');
    openPharmacyMgmt();
  } catch (e) { showToast(e.message, 'error'); }
};

// ── Modal Helpers ──────────────────────────────────────────────────────────────
window.openModal = function(id) {
  document.getElementById(id)?.classList.add('open');
};
window.closeModal = function(id) {
  document.getElementById(id)?.classList.remove('open');
};

// Close modal on backdrop click
document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) backdrop.classList.remove('open');
  });
});

// ── Utilities ──────────────────────────────────────────────────────────────────
function formatTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString();
}

// ── Init ───────────────────────────────────────────────────────────────────────
(function init() {
  // Check if already logged in
  if (auth.isLoggedIn()) {
    document.getElementById('page-auth').classList.remove('active');
    showAppShell();
    navigate('dashboard');
    initDashboard();

    const user = auth.getUser();
    if (user) connectAlertStream(user.id, handleWsMessage);
  }
})();
