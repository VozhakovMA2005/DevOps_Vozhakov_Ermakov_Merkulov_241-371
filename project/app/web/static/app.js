/* Общие помощники страниц: обращение к API и показ ошибок.
   Токен доступа лежит в cookie (HttpOnly), поэтому JS его не видит и не может
   утащить — браузер сам приложит его к запросу. */

async function api(method, url, body) {
  const options = {
    method,
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  if (response.status === 204) return null;

  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }

  if (!response.ok) {
    if (response.status === 401 && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
      return null;
    }
    throw new Error(describeError(payload, response.status));
  }
  return payload;
}

function describeError(payload, status) {
  if (!payload || !payload.error) return 'Ошибка ' + status;
  const { code, message, details } = payload.error;
  let text = message || code;
  if (details && details.fields) {
    text += '\n' + details.fields.map(f => `${f.field}: ${f.error}`).join('\n');
  }
  if (payload.request_id) text += `\n\nИдентификатор запроса: ${payload.request_id}`;
  return text;
}

function showError(message) {
  const box = document.getElementById('alert');
  if (!box) return;
  box.textContent = message;
  box.classList.remove('d-none');
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideError() {
  const box = document.getElementById('alert');
  if (box) box.classList.add('d-none');
}

function value(id) {
  const node = document.getElementById(id);
  return node ? node.value.trim() : '';
}

function checked(id) {
  const node = document.getElementById(id);
  return Boolean(node && node.checked);
}

/* Отправка формы: блокируем кнопку, показываем ошибку, при успехе
   перезагружаем страницу — данные приходят с сервера, а не собираются в JS. */
function onSubmit(formId, action) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    hideError();
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try {
      await action();
      window.location.reload();
    } catch (error) {
      showError(error.message);
      if (button) button.disabled = false;
    }
  });
}

async function logout() {
  try {
    await api('POST', '/api/v1/auth/logout');
  } finally {
    window.location.href = '/login';
  }
}
