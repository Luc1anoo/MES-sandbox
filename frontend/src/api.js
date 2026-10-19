async function req(path, options = {}) {
  let response;
  try {
    response = await fetch('/api' + path, {
      headers: {'Content-Type': 'application/json'},
      ...options,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new Error('无法连接后端，请启动 FastAPI（8000 端口）');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => `${item.loc?.join('.') || '请求'}: ${item.msg}`).join('；')
      : 'HTTP ' + response.status;
    throw new Error(message);
  }
  return data;
}
export const api = {
  get: path => req(path),
  post: (path, body) => req(path, {method: 'POST', body}),
  put: (path, body) => req(path, {method: 'PUT', body}),
  patch: (path, body) => req(path, {method: 'PATCH', body}),
  del: path => req(path, {method: 'DELETE'}),
};
