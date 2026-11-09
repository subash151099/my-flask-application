(() => {
  const tokenMeta = document.querySelector('meta[name="csrf-token"]');
  if (!tokenMeta || !tokenMeta.content) return;

  const token = tokenMeta.content;
  const addFormToken = (form) => {
    if (!(form instanceof HTMLFormElement) || form.method.toUpperCase() !== "POST") return;
    let field = form.querySelector('input[name="csrf_token"]');
    if (!field) {
      field = document.createElement("input");
      field.type = "hidden";
      field.name = "csrf_token";
      form.appendChild(field);
    }
    field.value = token;
  };

  document.querySelectorAll("form").forEach(addFormToken);
  document.addEventListener("submit", (event) => addFormToken(event.target), true);

  const nativeFetch = window.fetch;
  window.fetch = (input, init) => {
    const request = input instanceof Request ? input : null;
    const options = init || {};
    const method = String(options.method || (request && request.method) || "GET").toUpperCase();
    const url = new URL(request ? request.url : input, window.location.href);
    if (url.origin !== window.location.origin || ["GET", "HEAD", "OPTIONS"].includes(method)) {
      return nativeFetch.call(window, input, init);
    }

    const headers = new Headers(options.headers || (request && request.headers) || undefined);
    headers.set("X-CSRF-Token", token);
    return nativeFetch.call(window, input, { ...options, headers });
  };
})();
