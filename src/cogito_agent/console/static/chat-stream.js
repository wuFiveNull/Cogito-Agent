/**
 * chat-stream.js — SSE streaming chat for Cogito-Agent Console
 *
 * Reads the /console/chat/stream SSE endpoint via fetch + ReadableStream,
 * incrementally renders markdown (stable prefix / unstable suffix pattern),
 * handles thinking/reasoning panels, tool call cards, usage stats, and errors.
 *
 * htmx continues to power session list, history loading, inspector, etc.
 * Only the chat form submit moves to native JS.
 */
(function () {
  'use strict';

  /* ─── State ────────────────────────────────────────────────────────── */
  let currentAbortController = null;
  let currentState = 'idle'; // 'idle' | 'streaming' | 'interrupted'
  let accumulatedText = '';
  let traceId = '';
  let requestId = '';
  let msgGroupEl = null;
  let assistantBubbleEl = null;
  let textContentEl = null;
  let thinkingPanelEl = null;
  let usageStatsEl = null;
  let toolCardsContainer = null;

  /* ─── SSE Reader (fetch + ReadableStream) ────────────────────────── */
  function createSSEReader(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    /**
     * Parse a complete SSE block into { type, data }.
     * event: <type>\ndata: <json>\n\n
     */
    function parseSSEBlock(block) {
      const lines = block.split('\n');
      let eventType = 'message';
      let dataStr = '';
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          dataStr = line.slice(6);
        }
      }
      let data = {};
      try {
        data = JSON.parse(dataStr);
      } catch (_) {
        data = {};
      }
      return { type: eventType, data: data };
    }

    return {
      /** Read the next complete SSE event from the stream. Returns null on end. */
      async nextEvent() {
        while (true) {
          const eventEnd = buffer.indexOf('\n\n');
          if (eventEnd >= 0) {
            const block = buffer.slice(0, eventEnd);
            buffer = buffer.slice(eventEnd + 2);
            return parseSSEBlock(block);
          }
          const { done, value } = await reader.read();
          if (done) {
            if (buffer.trim()) {
              const ev = parseSSEBlock(buffer);
              buffer = '';
              return ev;
            }
            return null;
          }
          buffer += decoder.decode(value, { stream: true });
        }
      },
      cancel() {
        return reader.cancel();
      },
    };
  }

  /* ─── Escaping ─────────────────────────────────────────────────────── */
  function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ─── Client-Side Markdown Renderer ───────────────────────────────── */
  /**
   * Mirrors the server-side render_safe_markdown in markdown.py.
   * Supports: code fences, inline code, bold, italic, safe links,
   * headings (h3-h5), unordered lists, paragraphs.
   */
  function renderSafeMarkdown(text) {
    if (!text) return '';
    // Escape HTML first — then apply safe patterns
    var html = escapeHtml(text);

    // Inline code: `code`
    html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    // Bold: **text**
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    // Emphasis: *text* (not ** which is already consumed)
    html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
    // Safe links: [text](url) — only http/https allowed
    html = html.replace(
      /\[([^\]\n]+)\]\(([^)\s]+)\)/g,
      function (m, label, url) {
        if (
          !url.startsWith('http://') &&
          !url.startsWith('https://')
        ) {
          return label;
        }
        return (
          '<a href="' +
          url.replace(/"/g, '&quot;') +
          '" target="_blank" rel="noopener noreferrer">' +
          label +
          '</a>'
        );
      }
    );

    // Block-level parsing
    var lines = html.split('\n');
    var output = [];
    var inCode = false;
    var codeLines = [];
    var inParagraph = false;
    var inList = false;

    function closeParagraph() {
      if (inParagraph) {
        output.push('</p>');
        inParagraph = false;
      }
    }
    function closeList() {
      if (inList) {
        output.push('</ul>');
        inList = false;
      }
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var trimmed = line.trim();

      // Code fences
      if (trimmed.startsWith('```')) {
        closeParagraph();
        closeList();
        if (inCode) {
          output.push(
            '<pre><code>' + codeLines.join('\n') + '</code></pre>'
          );
          codeLines = [];
          inCode = false;
        } else {
          inCode = true;
        }
        continue;
      }
      if (inCode) {
        codeLines.push(line);
        continue;
      }

      // Empty line = paragraph / list break
      if (!trimmed) {
        closeParagraph();
        closeList();
        continue;
      }

      // Headings: # ## ###
      var headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (headingMatch) {
        closeParagraph();
        closeList();
        var level = headingMatch[1].length + 2;
        output.push(
          '<h' + level + '>' + headingMatch[2] + '</h' + level + '>'
        );
        continue;
      }

      // Unordered list items: - *
      var listMatch = trimmed.match(/^\s*[-*]\s+(.+)$/);
      if (listMatch) {
        closeParagraph();
        if (!inList) {
          output.push('<ul>');
          inList = true;
        }
        output.push('<li>' + listMatch[1] + '</li>');
        continue;
      }
      closeList();

      // Paragraph text
      if (!inParagraph) {
        output.push('<p>');
        inParagraph = true;
      } else {
        // Add line break within paragraph
        output[output.length - 1] += '<br>';
      }
      output[output.length - 1] += line;
    }

    // Close any open blocks
    if (inCode) {
      output.push('<pre><code>' + codeLines.join('\n') + '</code></pre>');
    }
    closeParagraph();
    closeList();
    return output.join('\n');
  }

  /* ─── Incremental Markdown (stable prefix / unstable suffix) ──────── */
  /**
   * Find the last \n\n boundary that is NOT inside a fenced code block.
   * Returns the index after the boundary, or -1 if none exists.
   */
  function isFenceLine(line) {
    return /^(?:`{3,}|~{3,})/.test(line.trim());
  }

  function findStableBoundary(text) {
    var idx = text.length;
    while (idx > 0) {
      var boundary = text.lastIndexOf('\n\n', idx - 1);
      if (boundary < 0) return -1;
      var splitAt = boundary + 2;
      var prefix = text.slice(0, splitAt);
      var fenceOpen = false;
      var pLines = prefix.split('\n');
      for (var j = 0; j < pLines.length; j++) {
        if (isFenceLine(pLines[j])) fenceOpen = !fenceOpen;
      }
      if (!fenceOpen) return splitAt;
      idx = boundary;
    }
    return -1;
  }

  function updateStreamingContent(container, fullText) {
    if (!container) return;

    // Remove any existing cursor first (will be re-added if still streaming)
    var oldCursor = container.querySelector('.stream-cursor');
    if (oldCursor) oldCursor.remove();

    var boundary = findStableBoundary(fullText);
    var stablePrefix = '';
    var unstableSuffix = fullText;

    if (boundary > 0) {
      stablePrefix = fullText.slice(0, boundary);
      unstableSuffix = fullText.slice(boundary);

      var stableEl = container.querySelector('.stream-stable');
      if (!stableEl) {
        stableEl = document.createElement('div');
        stableEl.className = 'stream-stable';
        container.prepend(stableEl);
      }
      stableEl.innerHTML = renderSafeMarkdown(stablePrefix);
    }

    var unstableEl = container.querySelector('.stream-unstable');
    if (!unstableEl) {
      unstableEl = document.createElement('span');
      unstableEl.className = 'stream-unstable';
      container.appendChild(unstableEl);
    }
    unstableEl.innerHTML = renderSafeMarkdown(unstableSuffix);

    // Live cursor indicator while streaming
    if (currentState === 'streaming') {
      var cursor = document.createElement('span');
      cursor.className = 'stream-cursor';
      cursor.textContent = '█';
      container.appendChild(cursor);
    }
  }

  /* ─── Thinking / Reasoning Parser ─────────────────────────────────── */
  /**
   * Parse <thinking>...</thinking> blocks from text.
   * Returns { visibleText, thinkingText }.
   */
  var THINKING_REGEX = /<thinking>([\s\S]*?)<\/thinking>/g;

  function extractThinking(text) {
    var visible = text;
    var thinking = '';

    var match = THINKING_REGEX.exec(text);
    if (match) {
      thinking = match[1].trim();
      visible = text.replace(THINKING_REGEX, '').trim();
    }

    return { visibleText: visible, thinkingText: thinking };
  }

  function updateThinkingPanel(panelEl, thinkingText) {
    if (!panelEl) return;
    if (!thinkingText) {
      panelEl.style.display = 'none';
      return;
    }
    panelEl.style.display = 'block';
    var contentEl = panelEl.querySelector('.thinking-content');
    if (contentEl) {
      contentEl.textContent = thinkingText;
    }
  }

  /* ─── Tool Call Handlers ──────────────────────────────────────────── */
  function handleToolCallStarted(data) {
    if (!toolCardsContainer) return;
    var round = data.round || 1;
    var count = data.tool_count || 0;
    var card = document.createElement('section');
    card.className = 'turn-card tool-card tool-card-running';
    card.innerHTML =
      '<span class="turn-card-label">Tool round ' +
      round +
      '</span>\n' +
      '<strong>Executing ' +
      count +
      ' capability(ies)…</strong>\n' +
      '<span class="tool-spinner"></span>';
    toolCardsContainer.appendChild(card);
    scrollChat();
  }

  function handleToolCallCompleted(data) {
    if (!toolCardsContainer) return;
    var runningCards = toolCardsContainer.querySelectorAll(
      '.tool-card-running'
    );
    var lastRunning = runningCards[runningCards.length - 1];
    if (!lastRunning) return;
    lastRunning.classList.remove('tool-card-running');
    lastRunning.classList.add('tool-card-done');

    var results = data.tool_results || [];
    var round = data.round || '';
    var itemsHtml = results
      .map(function (r) {
        return (
          '<div class="tool-result-item">\n<strong>' +
          escapeHtml(r.tool || '') +
          '</strong>\n<p>' +
          escapeHtml(
            r.summary || r.error || 'No summary'
          ) +
          '</p>\n</div>'
        );
      })
      .join('');
    lastRunning.innerHTML =
      '<span class="turn-card-label">Tool round ' +
      round +
      '</span>\n' +
      itemsHtml;
    scrollChat();
  }

  function handleApprovalRequired(data) {
    if (!toolCardsContainer) return;
    var card = document.createElement('section');
    card.className = 'turn-card approval-card';
    card.innerHTML =
      '<span class="turn-card-label">Approval required</span>\n' +
      '<strong>Execution paused</strong>\n' +
      '<a href="/console/approval">Review approval ' +
      escapeHtml(data.approval_id || '') +
      '</a>';
    toolCardsContainer.appendChild(card);
    scrollChat();
  }

  /* ─── Error / Final Handlers ──────────────────────────────────────── */
  function handleStreamError(data) {
    var error = data.error || {};
    var code = error.code || 'UNKNOWN';
    var message = error.message || 'An unknown error occurred';

    if (!assistantBubbleEl) return;
    var errorEl = assistantBubbleEl.querySelector('.stream-error');
    if (!errorEl) {
      errorEl = document.createElement('div');
      errorEl.className = 'stream-error';
      assistantBubbleEl.appendChild(errorEl);
    }
    errorEl.innerHTML =
      '<div class="error-banner">\n' +
      '<span class="error-icon">⚠</span>\n' +
      '<div class="error-body">\n<strong>' +
      escapeHtml(code) +
      '</strong>\n' +
      '<div class="error-text">' +
      escapeHtml(message) +
      '</div>\n</div>\n</div>';
    scrollChat();
  }

  function handleStreamFinal(data) {
    var response = data.response || accumulatedText;
    var extracted = extractThinking(response);
    var visibleText = extracted.visibleText;
    var thinkingText = extracted.thinkingText;

    // Final render with full text — no unstable suffix
    if (textContentEl) {
      textContentEl.innerHTML = renderSafeMarkdown(visibleText);
      // Remove stable/unstable containers if they exist
      var stableEl = textContentEl.querySelector('.stream-stable');
      if (stableEl) stableEl.remove();
      var unstableEl = textContentEl.querySelector('.stream-unstable');
      if (unstableEl) unstableEl.remove();
    }

    // Remove streaming border
    var bubble = assistantBubbleEl
      ? assistantBubbleEl.closest('.msg-bubble')
      : null;
    if (bubble) {
      bubble.classList.remove('msg-bubble-streaming');
    }

    // Show usage stats
    if (
      usageStatsEl &&
      (data.input_tokens !== undefined || data.output_tokens !== undefined)
    ) {
      usageStatsEl.style.display = 'flex';
      var latencyStr = '—';
      if (data.latency_ms) {
        latencyStr = (data.latency_ms / 1000).toFixed(1) + 's';
      }
      usageStatsEl.innerHTML =
        '<span class="usage-stat">\n' +
        '<span class="usage-label">Model</span>\n' +
        '<span class="usage-value">' +
        escapeHtml(data.model || 'unknown') +
        '</span>\n</span>\n' +
        '<span class="usage-stat">\n' +
        '<span class="usage-label">Input</span>\n' +
        '<span class="usage-value">' +
        (data.input_tokens || 0) +
        ' tokens</span>\n</span>\n' +
        '<span class="usage-stat">\n' +
        '<span class="usage-label">Output</span>\n' +
        '<span class="usage-value">' +
        (data.output_tokens || 0) +
        ' tokens</span>\n</span>\n' +
        '<span class="usage-stat">\n' +
        '<span class="usage-label">Latency</span>\n' +
        '<span class="usage-value">' +
        latencyStr +
        '</span>\n</span>\n' +
        '<span class="usage-stat">\n' +
        '<button class="turn-inspect-button link-button" data-trace-id="' +
        escapeHtml(data.trace_id || '') +
        '">Inspect</button>\n</span>';

      // Wire inspect button via htmx
      var inspectBtn = usageStatsEl.querySelector('.turn-inspect-button');
      if (inspectBtn && data.trace_id) {
        inspectBtn.addEventListener('click', function () {
          htmx.ajax('GET', '/console/chat/turns/' + encodeURIComponent(data.trace_id), {
            target: '#turn-inspector',
            swap: 'innerHTML',
          });
        });
      }
    }

    // Show trace info in the bubble footer
    if ((traceId || requestId) && bubble) {
      var traceEl = document.createElement('div');
      traceEl.className = 'msg-trace';

      // Remove existing trace if any
      var oldTrace = bubble.querySelector('.msg-trace');
      if (oldTrace) oldTrace.remove();

      var parts = [];
      if (traceId) {
        parts.push(
          'Trace: <code>' +
            escapeHtml(traceId) +
            '</code> · <a href="/console/traces/' +
            encodeURIComponent(traceId) +
            '">View Trace</a>'
        );
      }
      if (requestId) {
        parts.push('Request: <code>' + escapeHtml(requestId) + '</code>');
      }
      traceEl.innerHTML = parts.join(' · ');
      bubble.appendChild(traceEl);
    }

    // Mark the msg-group as completed
    if (msgGroupEl) {
      msgGroupEl.classList.remove('msg-group-streaming');
      msgGroupEl.classList.add('msg-group-completed');
    }

    finalizeTurn('completed');
  }

  function finalizeTurn(state) {
    var cursor = document.querySelector('.stream-cursor');
    if (cursor) cursor.remove();
    currentState = state;
  }

  /* ─── Main Stream Controller ──────────────────────────────────────── */
  async function startStream(message, sessionId, workspaceId, csrfToken) {
    if (currentState === 'streaming') return;

    currentAbortController = new AbortController();
    currentState = 'streaming';
    accumulatedText = '';
    traceId = '';
    requestId = '';
    setTurnState(true);

    // Remove empty state if present
    var chatMessages = document.getElementById('chat-messages');
    var emptyEl = document.getElementById('chat-empty');
    if (emptyEl) emptyEl.remove();

    // Create msg-group placeholder
    msgGroupEl = document.createElement('div');
    msgGroupEl.className = 'msg-group msg-group-streaming';
    msgGroupEl.id = 'msg-group-streaming';

    // User bubble
    var userDiv = document.createElement('div');
    userDiv.className = 'message message-user';
    userDiv.innerHTML =
      '<div class="msg-bubble">\n' +
      '<div class="msg-meta">You</div>\n' +
      '<div class="msg-text">' +
      escapeHtml(message) +
      '</div>\n</div>';
    msgGroupEl.appendChild(userDiv);

    // Assistant bubble with placeholders
    var asstDiv = document.createElement('div');
    asstDiv.className = 'message message-assistant';
    asstDiv.innerHTML =
      '<div class="msg-bubble msg-bubble-streaming">\n' +
      '<div class="msg-meta">Assistant</div>\n' +
      '<details class="thinking-panel" style="display:none">\n' +
      '<summary>Thinking <span class="thinking-toggle">show</span></summary>\n' +
      '<div class="thinking-content"></div>\n' +
      '</details>\n' +
      '<div class="assistant-text-content"></div>\n' +
      '<div class="turn-tool-cards"></div>\n' +
      '<div class="turn-usage-stats" style="display:none"></div>\n' +
      '</div>';
    msgGroupEl.appendChild(asstDiv);
    chatMessages.appendChild(msgGroupEl);

    assistantBubbleEl = asstDiv.querySelector('.msg-bubble');
    textContentEl = asstDiv.querySelector('.assistant-text-content');
    thinkingPanelEl = asstDiv.querySelector('.thinking-panel');
    toolCardsContainer = asstDiv.querySelector('.turn-tool-cards');
    usageStatsEl = asstDiv.querySelector('.turn-usage-stats');

    scrollChat();

    try {
      var formData = new FormData();
      formData.append('message', message);
      formData.append('session_id', sessionId);
      formData.append('workspace_id', workspaceId);

      var response = await fetch('/console/chat/stream', {
        method: 'POST',
        headers: {
          'X-CSRF-Token': csrfToken,
        },
        body: formData,
        signal: currentAbortController.signal,
      });

      if (!response.ok) {
        throw new Error('Server error: ' + response.status);
      }

      var reader = createSSEReader(response);

      while (true) {
        var event = await reader.nextEvent();
        if (event === null) break;

        switch (event.type) {
          case 'metadata':
            traceId = event.data.trace_id || '';
            requestId = event.data.request_id || '';
            break;

          case 'delta':
            var delta = event.data.delta || '';
            accumulatedText += delta;
            var extracted = extractThinking(accumulatedText);
            updateThinkingPanel(thinkingPanelEl, extracted.thinkingText);
            updateStreamingContent(textContentEl, extracted.visibleText);
            scrollChat();
            break;

          case 'tool_call_started':
            handleToolCallStarted(event.data);
            break;

          case 'tool_call_completed':
            handleToolCallCompleted(event.data);
            break;

          case 'approval_required':
            handleApprovalRequired(event.data);
            break;

          case 'error':
            // Error during stream — show and break, finalize after
            handleStreamError(event.data);
            finalizeTurn('error');
            return;

          case 'final':
            handleStreamFinal(event.data);
            // Stream event processing done; don't double-finalize
            return;
        }
      }

      // Stream ended without a final event (edge case)
      // Render accumulated text as-is
      if (accumulatedText) {
        var extractedFinal = extractThinking(accumulatedText);
        if (textContentEl) {
          textContentEl.innerHTML = renderSafeMarkdown(
            extractedFinal.visibleText
          );
        }
      }
      finalizeTurn('completed');
    } catch (err) {
      if (err.name === 'AbortError') {
        // User clicked stop — call interrupt endpoint
        try {
          await fetch('/console/chat/interrupt', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/x-www-form-urlencoded',
              'X-CSRF-Token': csrfToken,
            },
            body:
              'session_id=' +
              encodeURIComponent(sessionId) +
              '&workspace_id=' +
              encodeURIComponent(workspaceId),
          });
        } catch (_) {
          // fire-and-forget
        }
        finalizeTurn('interrupted');
      } else {
        handleStreamError({
          error: { code: 'FETCH_ERROR', message: err.message },
        });
        finalizeTurn('error');
      }
    } finally {
      currentState = 'idle';
      currentAbortController = null;
      setTurnState(false);
      updateSessionList();
    }
  }

  /* ─── Public API ──────────────────────────────────────────────────── */
  window.ChatStream = {
    submit: function (message, sessionId, workspaceId) {
      var csrfMeta = document.querySelector('meta[name="csrf-token"]');
      var csrfToken = csrfMeta ? csrfMeta.content : '';
      return startStream(message, sessionId, workspaceId, csrfToken);
    },
    stop: function () {
      if (currentAbortController && currentState === 'streaming') {
        currentAbortController.abort();
        // Disable button immediately
        var stopBtn = document.getElementById('stop-turn');
        if (stopBtn) stopBtn.disabled = true;
      }
    },
    getState: function () {
      return currentState;
    },
  };

  /* ─── Form Setup ──────────────────────────────────────────────────── */
  function setupChatForm() {
    var form = document.getElementById('chat-form');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var messageInput = document.getElementById('chat-input');
      if (!messageInput) return;
      var message = messageInput.value.trim();
      if (!message) return;

      var sessionInput = form.querySelector(
        'input[name="session_id"]'
      );
      var workspaceInput = form.querySelector(
        'input[name="workspace_id"]'
      );
      var sessionId = sessionInput
        ? sessionInput.value
        : 'console-default';
      var workspaceId = workspaceInput
        ? workspaceInput.value
        : 'default';

      messageInput.value = '';
      messageInput.style.height = 'auto';

      window.ChatStream.submit(message, sessionId, workspaceId);
    });
  }

  /* ─── Global Helpers ───────────────────────────────────────────────── */
  function scrollChat() {
    var el = document.getElementById('chat-messages');
    if (el) el.scrollTop = el.scrollHeight;
  }
  window.scrollChat = scrollChat;

  function setTurnState(running) {
    var workspace = document.querySelector('.chat-workspace');
    var statusEl = document.getElementById('stream-status');
    var stopBtn = document.getElementById('stop-turn');
    var sendBtn = document.querySelector('.btn-send');

    if (workspace) {
      workspace.dataset.streamState = running ? 'running' : 'idle';
    }
    if (statusEl) {
      var textSpan = statusEl.lastElementChild;
      if (textSpan)
        textSpan.textContent = running ? 'Running' : 'Ready';
    }
    if (stopBtn) stopBtn.disabled = !running;
    if (sendBtn) {
      sendBtn.disabled = running;
      sendBtn.classList.toggle('btn-sending', running);
    }
  }
  window.setTurnState = setTurnState;

  // Override the old stopTurn (which used htmx abort)
  window.stopTurn = function () {
    window.ChatStream.stop();
  };

  function updateSessionList() {
    htmx.ajax('GET', '/console/chat/sessions', {
      target: '#session-list',
      swap: 'innerHTML',
    });
  }
  window.updateSessionList = updateSessionList;

  /* ─── Init ─────────────────────────────────────────────────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupChatForm);
  } else {
    setupChatForm();
  }
})();
