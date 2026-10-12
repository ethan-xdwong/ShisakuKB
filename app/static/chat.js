'use strict';

(function () {
  const form = document.getElementById('ask-form');
  const questionInput = document.getElementById('question');
  const retrieveOnlyInput = document.getElementById('retrieve-only');
  const submitButton = document.getElementById('submit-button');
  const messages = document.getElementById('messages');
  const viewer = document.getElementById('kb-viewer');
  let pending = false;

  initPaneSplitter();

  if (!form || !questionInput || !retrieveOnlyInput || !submitButton || !messages || !viewer) {
    return;
  }

  questionInput.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && event.shiftKey === false) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    ask();
  });

  function ask() {
    const question = questionInput.value.trim();
    if (question.length === 0 || pending) {
      return;
    }
    pending = true;
    submitButton.disabled = true;
    appendUser(question);
    const bot = appendBot();
    const retrieveOnly = retrieveOnlyInput.checked === true;
    let answer = '';

    fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: question,
        retrieve_only: retrieveOnly
      })
    }).then(function (response) {
      if (!response.ok || !response.body) {
        return response.json().catch(function () {
          return {};
        }).then(function (payload) {
          const detail = payload && typeof payload.detail === 'string' ? payload.detail : '提问失败';
          showError(bot.error, detail);
        });
      }
      return readStream(response.body, function (eventName, payload) {
        if (eventName === 'sources') {
          bot.sourceItems = Array.isArray(payload.sources) ? payload.sources : [];
          renderSources(bot.sources, bot.sourceItems);
          bot.sourceLabel.hidden = bot.sourceItems.length === 0;
        } else if (eventName === 'delta' && typeof payload.text === 'string') {
          answer += payload.text;
          renderAnswer(bot.answer, answer, bot.sourceItems);
        } else if (eventName === 'error' && typeof payload.message === 'string') {
          showError(bot.error, payload.message);
        } else if (eventName === 'done' && retrieveOnly && answer.length === 0 && bot.sourceItems.length > 0) {
          renderAnswer(bot.answer, '未调用模型，以下为检索到的段落。', bot.sourceItems);
        }
        messages.scrollTop = messages.scrollHeight;
      });
    }).catch(function () {
      showError(bot.error, '无法连接问答服务。');
    }).then(function () {
      pending = false;
      submitButton.disabled = false;
    });
  }

  function appendUser(question) {
    const article = document.createElement('article');
    const paragraph = document.createElement('p');
    article.className = 'message message-user';
    paragraph.textContent = question;
    article.appendChild(paragraph);
    messages.appendChild(article);
  }

  function appendBot() {
    const article = document.createElement('article');
    const answer = document.createElement('p');
    const error = document.createElement('p');
    const sourceLabel = document.createElement('p');
    const sources = document.createElement('ol');
    article.className = 'message message-bot';
    answer.className = 'answer';
    error.className = 'error';
    error.hidden = true;
    sourceLabel.className = 'source-label';
    sourceLabel.textContent = '来源';
    sourceLabel.hidden = true;
    sources.className = 'source-list';
    article.appendChild(answer);
    article.appendChild(error);
    article.appendChild(sourceLabel);
    article.appendChild(sources);
    messages.appendChild(article);
    article.addEventListener('click', function (event) {
      const target = event.target;
      const link = target && target.closest ? target.closest('a[href^="/kb/"]') : null;
      if (link === null || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      viewer.src = link.getAttribute('href');
    });
    return {
      sources: sources,
      answer: answer,
      error: error,
      sourceLabel: sourceLabel,
      sourceItems: []
    };
  }

  function renderSources(list, sources) {
    const items = Array.isArray(sources) ? sources : [];
    list.textContent = '';
    items.forEach(function (source, index) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      const title = document.createElement('span');
      const url = document.createElement('span');
      const meta = document.createElement('span');
      const excerpt = document.createElement('span');
      const href = source.url || '';
      link.className = 'source-card';
      link.href = href;
      title.className = 'source-title';
      title.textContent = '[' + (index + 1) + '] ' + (source.title || '');
      url.className = 'source-url';
      url.textContent = href;
      meta.className = 'source-meta';
      meta.textContent = (source.breadcrumb || '') + ' · 相关度 ' + Number(source.score || 0).toFixed(2);
      excerpt.className = 'source-excerpt';
      excerpt.textContent = source.excerpt || '';
      link.appendChild(title);
      link.appendChild(url);
      link.appendChild(meta);
      link.appendChild(excerpt);
      item.appendChild(link);
      list.appendChild(item);
    });
  }

  function renderAnswer(container, text, sources) {
    const items = Array.isArray(sources) ? sources : [];
    const pattern = /\[(\d+)\]/g;
    let lastIndex = 0;
    let matched = pattern.exec(text);
    container.textContent = '';
    while (matched !== null) {
      container.appendChild(document.createTextNode(text.slice(lastIndex, matched.index)));
      const source = items[Number(matched[1]) - 1];
      if (source && source.url) {
        const link = document.createElement('a');
        link.className = 'cite';
        link.href = source.url;
        link.textContent = matched[0];
        link.title = source.title || '';
        container.appendChild(link);
      } else {
        container.appendChild(document.createTextNode(matched[0]));
      }
      lastIndex = matched.index + matched[0].length;
      matched = pattern.exec(text);
    }
    container.appendChild(document.createTextNode(text.slice(lastIndex)));
  }

  function showError(node, message) {
    node.hidden = false;
    node.textContent = message;
  }

  function readStream(stream, onEvent) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    function pump() {
      return reader.read().then(function (result) {
        if (result.done) {
          if (buffer.trim().length > 0) {
            emit(buffer, onEvent);
          }
          return;
        }
        buffer += decoder.decode(result.value, { stream: true }).replace(/\r\n/g, '\n');
        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1) {
          emit(buffer.slice(0, boundary), onEvent);
          buffer = buffer.slice(boundary + 2);
          boundary = buffer.indexOf('\n\n');
        }
        return pump();
      });
    }
    return pump();
  }

  function emit(raw, onEvent) {
    let eventName = 'message';
    const dataLines = [];
    raw.split('\n').forEach(function (line) {
      if (line.indexOf('event:') === 0) {
        eventName = line.slice(6).trim();
      } else if (line.indexOf('data:') === 0) {
        dataLines.push(line.slice(5).trim());
      }
    });
    if (dataLines.length === 0) {
      return;
    }
    let payload;
    try {
      payload = JSON.parse(dataLines.join('\n'));
    } catch (error) {
      onEvent('error', { message: '回答内容无法解析。' });
      return;
    }
    onEvent(eventName, payload);
  }

  function initPaneSplitter() {
    const shell = document.querySelector('.shell');
    const splitter = document.getElementById('pane-splitter');
    if (!shell || !splitter) {
      return;
    }
    const storageKey = 'hs-pane-split';
    const minViewer = 280;
    const minChat = 280;
    const minViewerHeight = 160;
    const minChatHeight = 220;
    const keyStep = 24;
    const narrowQuery = window.matchMedia('(max-width: 900px)');
    let saved = readSaved();

    applySaved();

    splitter.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) {
        return;
      }
      event.preventDefault();
      splitter.setPointerCapture(event.pointerId);
      shell.classList.add('is-resizing');
      const bounds = shell.getBoundingClientRect();
      const vertical = narrowQuery.matches;

      function move(moveEvent) {
        resizeTo(vertical, bounds, vertical ? moveEvent.clientY : moveEvent.clientX);
      }

      function stop(stopEvent) {
        splitter.removeEventListener('pointermove', move);
        splitter.removeEventListener('pointerup', stop);
        splitter.removeEventListener('pointercancel', stop);
        shell.classList.remove('is-resizing');
        writeSaved();
        if (splitter.hasPointerCapture(stopEvent.pointerId)) {
          splitter.releasePointerCapture(stopEvent.pointerId);
        }
      }

      splitter.addEventListener('pointermove', move);
      splitter.addEventListener('pointerup', stop);
      splitter.addEventListener('pointercancel', stop);
    });

    splitter.addEventListener('keydown', function (event) {
      const vertical = narrowQuery.matches;
      let delta = 0;
      if (vertical && event.key === 'ArrowDown') {
        delta = keyStep;
      } else if (vertical && event.key === 'ArrowUp') {
        delta = -keyStep;
      } else if (!vertical && event.key === 'ArrowRight') {
        delta = keyStep;
      } else if (!vertical && event.key === 'ArrowLeft') {
        delta = -keyStep;
      }
      if (delta === 0) {
        return;
      }
      event.preventDefault();
      const bounds = shell.getBoundingClientRect();
      const current = currentSize(vertical, bounds);
      resizeTo(vertical, bounds, (vertical ? bounds.top : bounds.left) + current + delta);
      writeSaved();
    });

    window.addEventListener('resize', applySaved);
    narrowQuery.addEventListener('change', applySaved);

    function resizeTo(vertical, bounds, pointer) {
      const splitterSize = vertical ? splitter.offsetHeight : splitter.offsetWidth;
      const start = vertical ? bounds.top : bounds.left;
      const total = vertical ? bounds.height : bounds.width;
      const minStart = vertical ? minViewerHeight : minViewer;
      const minEnd = vertical ? minChatHeight : minChat;
      const size = clamp(pointer - start, minStart, total - minEnd - splitterSize);
      shell.classList.add('is-split');
      shell.style.setProperty('--viewer-size', Math.round(size) + 'px');
      if (vertical) {
        saved.viewerHeight = size;
      } else {
        saved.viewerWidth = size;
      }
      updateAria(vertical, size, total - splitterSize);
    }

    function currentSize(vertical, bounds) {
      const declared = parseFloat(shell.style.getPropertyValue('--viewer-size'));
      if (Number.isFinite(declared)) {
        return declared;
      }
      return vertical ? bounds.height * 0.46 : bounds.width - 384;
    }

    function applySaved() {
      const vertical = narrowQuery.matches;
      const bounds = shell.getBoundingClientRect();
      const stored = vertical ? saved.viewerHeight : saved.viewerWidth;
      shell.style.removeProperty('--viewer-size');
      shell.classList.remove('is-split');
      if (typeof stored !== 'number') {
        updateAria(vertical, currentSize(vertical, bounds), vertical ? bounds.height : bounds.width);
        return;
      }
      resizeTo(vertical, bounds, (vertical ? bounds.top : bounds.left) + stored);
    }

    function updateAria(vertical, size, max) {
      const minStart = vertical ? minViewerHeight : minViewer;
      splitter.setAttribute('aria-orientation', vertical ? 'horizontal' : 'vertical');
      splitter.setAttribute('aria-label', vertical ? '调整手册与问答高度' : '调整手册与问答宽度');
      splitter.setAttribute('aria-valuemin', String(minStart));
      splitter.setAttribute('aria-valuemax', String(Math.max(minStart, Math.round(max))));
      splitter.setAttribute('aria-valuenow', String(Math.round(size)));
      splitter.setAttribute('aria-valuetext', Math.round(size) + '像素');
    }

    function readSaved() {
      try {
        const raw = localStorage.getItem(storageKey);
        const data = raw ? JSON.parse(raw) : null;
        if (!data || typeof data !== 'object') {
          return {};
        }
        return {
          viewerWidth: typeof data.viewerWidth === 'number' ? data.viewerWidth : undefined,
          viewerHeight: typeof data.viewerHeight === 'number' ? data.viewerHeight : undefined
        };
      } catch (error) {
        return {};
      }
    }

    function writeSaved() {
      localStorage.setItem(storageKey, JSON.stringify(saved));
    }

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), Math.max(min, max));
    }
  }
}());
