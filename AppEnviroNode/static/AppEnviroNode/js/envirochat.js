// ============================================================
//  envirochat.js — EnviroAI Public Chat (Gemini-powered)
//  Place this file inside:
//  appenvironode/static/AppEnviroNode/js/envirochat.js
//
//  Replaces the hardcoded generateReply() in health.html.
//  Requires window.ENVIRO_CHAT_API_URL to be set in the HTML.
// ============================================================

(function () {
  const messagesBox   = document.getElementById('messagesBox');
  const chatInput     = document.getElementById('healthChatInput');
  const sendBtn       = document.getElementById('healthChatSend');
  const suggestionChips = document.querySelectorAll('.suggestion-chip');

  // ── helpers ──────────────────────────────────────────────
  function escapeHtml(text) {
    return text
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function appendMessage(message, isUser) {
    const bubble = document.createElement('div');
    bubble.className = 'message ' + (isUser ? 'user' : 'ai');

    if (!isUser) {
      const label = document.createElement('div');
      label.className = 'message-label';
      label.innerHTML = '<i class="fa-solid fa-brain"></i> EnviroNode AI';
      bubble.appendChild(label);
    }

    const text = document.createElement('p');
    text.innerHTML = escapeHtml(message);
    bubble.appendChild(text);
    messagesBox.appendChild(bubble);
    messagesBox.scrollTop = messagesBox.scrollHeight;
    return bubble;
  }

  function appendTyping() {
    const bubble = document.createElement('div');
    bubble.className = 'message ai';
    bubble.id = 'typingBubble';

    const label = document.createElement('div');
    label.className = 'message-label';
    label.innerHTML = '<i class="fa-solid fa-brain"></i> EnviroNode AI';

    const dots = document.createElement('p');
    dots.innerHTML = '<span class="typing-dots">&#8226;&#8226;&#8226;</span>';

    bubble.appendChild(label);
    bubble.appendChild(dots);
    messagesBox.appendChild(bubble);
    messagesBox.scrollTop = messagesBox.scrollHeight;
  }

  function removeTyping() {
    const bubble = document.getElementById('typingBubble');
    if (bubble) bubble.remove();
  }

  // ── main send function ────────────────────────────────────
  async function sendMessage(message) {
    const text = message.trim();
    if (!text) return;

    // Disable input while waiting
    chatInput.value = '';
    chatInput.disabled = true;
    sendBtn.disabled  = true;

    appendMessage(text, true);
    appendTyping();

    try {
      const apiUrl = window.ENVIRO_CHAT_API_URL || '/health/api/chat/';
      const csrfToken = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrftoken='))
        ?.split('=')[1] || '';

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ message: text })
      });

      const data = await response.json();
      removeTyping();

      if (data.success && data.reply) {
        appendMessage(data.reply, false);
      } else {
        appendMessage("Sorry, I couldn't get a response. Please try again.", false);
      }
    } catch (err) {
      removeTyping();
      appendMessage("Connection error. Please check your internet and try again.", false);
    } finally {
      chatInput.disabled = false;
      sendBtn.disabled   = false;
      chatInput.focus();
    }
  }

  // ── event listeners ───────────────────────────────────────
  sendBtn.addEventListener('click', () => sendMessage(chatInput.value));

  chatInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendMessage(chatInput.value);
    }
  });

  suggestionChips.forEach(function (chip) {
    chip.addEventListener('click', function () {
      sendMessage(chip.textContent.trim());
    });
  });

})();
