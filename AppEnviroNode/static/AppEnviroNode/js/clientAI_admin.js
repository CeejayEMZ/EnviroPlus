// ============================================================
//  clientAI_admin.js — Admin EnviroAI Chat + Insights (Gemini)
//  Place this file inside:
//  appenviroplus/static/AppEnviroNode/js/clientAI_admin.js
//
//  Replaces the hardcoded random responses in clientai.html
//  and loads real AI insights on page load.
//  Requires window.CAI_CHAT_URL and window.CAI_INSIGHTS_URL
// ============================================================

// ── Chat ─────────────────────────────────────────────────────
const cAI_chatContainer = document.getElementById('cAI-chat-container');
const cAI_chatInput     = document.getElementById('cAI-chat-input');

function cAI_scrollToBottom() {
    if (cAI_chatContainer) cAI_chatContainer.scrollTop = cAI_chatContainer.scrollHeight;
}

function cAI_fillChat(text) {
    if (cAI_chatInput) { cAI_chatInput.value = text; cAI_chatInput.focus(); }
}

function cAI_clearChat() {
    if (cAI_chatContainer) {
        cAI_chatContainer.innerHTML = '';
        cAI_addAIMessage("Chat cleared. How can I assist you with EnviroPlus today?");
    }
}

function cAI_addUserMessage(text) {
    const html = `
        <div class="cAI-chat-msg-wrapper cAI-msg-right cAI-animate-fade-in">
            <div class="cAI-avatar cAI-avatar-user">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <div class="cAI-bubble cAI-bubble-user">${text}</div>
        </div>`;
    if (cAI_chatContainer) {
        cAI_chatContainer.insertAdjacentHTML('beforeend', html);
        cAI_scrollToBottom();
    }
}

function cAI_addAIMessage(text) {
    const html = `
        <div class="cAI-chat-msg-wrapper cAI-animate-fade-in">
            <div class="cAI-avatar cAI-avatar-ai">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
            </div>
            <div class="cAI-bubble cAI-bubble-ai">${text}</div>
        </div>`;
    if (cAI_chatContainer) {
        cAI_chatContainer.insertAdjacentHTML('beforeend', html);
        cAI_scrollToBottom();
    }
}

function cAI_addTyping() {
    const html = `
        <div class="cAI-chat-msg-wrapper cAI-animate-fade-in" id="cAI-typing">
            <div class="cAI-avatar cAI-avatar-ai">
                <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
            </div>
            <div class="cAI-bubble cAI-bubble-ai">&#8226;&#8226;&#8226;</div>
        </div>`;
    if (cAI_chatContainer) {
        cAI_chatContainer.insertAdjacentHTML('beforeend', html);
        cAI_scrollToBottom();
    }
}

function cAI_removeTyping() {
    const el = document.getElementById('cAI-typing');
    if (el) el.remove();
}

async function cAI_handleChatSubmit(e) {
    e.preventDefault();
    if (!cAI_chatInput) return;

    const text = cAI_chatInput.value.trim();
    if (!text) return;

    cAI_addUserMessage(text);
    cAI_chatInput.value = '';
    cAI_chatInput.disabled = true;
    cAI_addTyping();

    try {
        const csrfToken = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1] || '';

        const res = await fetch(window.CAI_CHAT_URL || '/api/chat/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({ message: text })
        });

        const data = await res.json();
        cAI_removeTyping();

        if (data.success && data.reply) {
            cAI_addAIMessage(data.reply);
        } else {
            cAI_addAIMessage("I couldn't generate a response right now. Please try again.");
        }
    } catch (err) {
        cAI_removeTyping();
        cAI_addAIMessage("Connection error. Please check your internet and try again.");
    } finally {
        cAI_chatInput.disabled = false;
        cAI_chatInput.focus();
    }
}

// ── AI Insights loader ────────────────────────────────────────
async function cAI_loadInsights() {
    try {
        const res  = await fetch(window.CAI_INSIGHTS_URL || '/api/ai-insights/');
        const data = await res.json();

        if (!data.success) return;

        const ins = data.insights;
        const sum = data.sensor_summary;

        // Summary text
        const summaryEl = document.getElementById('cAI-summary-text');
        if (summaryEl && ins.summary) summaryEl.textContent = ins.summary;

        // Forecast text
        const forecastEl = document.getElementById('cAI-forecast-text');
        if (forecastEl && ins.forecast) forecastEl.textContent = ins.forecast;

        // Avg AQI value
        const aqiEl = document.getElementById('cAI-avg-aqi');
        if (aqiEl && sum.avg_aqi != null) aqiEl.textContent = sum.avg_aqi;

        // Recommendations list
        const recList = document.getElementById('cAI-recommendations-list');
        if (recList && ins.recommendations && ins.recommendations.length) {
            recList.innerHTML = ins.recommendations
                .map(r => `<li class="cAI-insight-item">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:#10b981;flex-shrink:0"><polyline points="20 6 9 17 4 12"/></svg>
                    <span>${r}</span></li>`)
                .join('');
        }

        // Anomalies list
        const anomList = document.getElementById('cAI-anomalies-list');
        if (anomList && ins.anomalies && ins.anomalies.length) {
            anomList.innerHTML = ins.anomalies
                .map(a => `<li class="cAI-insight-item">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:#f59e0b;flex-shrink:0"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>${a}</span></li>`)
                .join('');
        }

    } catch (err) {
        console.warn('EnviroAI insights load failed:', err);
    }
}

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    // Timestamp updater
    function cAI_updateTime() {
        const el = document.getElementById('cAI-current-time');
        if (el) el.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
    setInterval(cAI_updateTime, 1000);
    cAI_updateTime();

    // Wire up form submit
    const form = document.getElementById('cAI-chat-form');
    if (form) form.addEventListener('submit', cAI_handleChatSubmit);

    cAI_scrollToBottom();

    // Load real AI insights on page load
    cAI_loadInsights();
});
