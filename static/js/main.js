document.addEventListener("DOMContentLoaded", () => {
  const notificationDropdown = document.getElementById("notificationDropdown");
  if (notificationDropdown) {
    notificationDropdown.addEventListener("shown.bs.dropdown", () => {
      fetch(notificationDropdown.dataset.readUrl, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      }).then((response) => {
        if (!response.ok) throw new Error(`Notification read request failed (${response.status}).`);
        const badge = notificationDropdown.querySelector(".dotb");
        if (badge) badge.remove();
      }).catch((error) => console.error("Could not mark notifications as read.", error));
    });
  }

  document.querySelectorAll(".toggle-password").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.target);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      const icon = button.querySelector("i");
      if (icon) icon.className = show ? "bi bi-eye-slash" : "bi bi-eye";
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  const dob = document.getElementById("date_of_birth");
  if (dob) {
    const today = new Date();
    const cutoff = new Date(today.getFullYear() - 18, today.getMonth(), today.getDate());
    dob.max = `${cutoff.getFullYear()}-${String(cutoff.getMonth()+1).padStart(2,"0")}-${String(cutoff.getDate()).padStart(2,"0")}`;
  }

  const registerForm = document.getElementById("registerForm");
  if (registerForm) {
    registerForm.addEventListener("submit", (event) => {
      const password = document.getElementById("password");
      const confirm = document.getElementById("confirm_password");
      if (password.value !== confirm.value) {
        event.preventDefault();
        confirm.setCustomValidity("Passwords do not match.");
        confirm.reportValidity();
      } else {
        confirm.setCustomValidity("");
      }
      if (!registerForm.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      registerForm.classList.add("was-validated");
    });
    document.getElementById("confirm_password").addEventListener("input", function () {
      this.setCustomValidity("");
    });
  }

  const about = document.getElementById("aboutMe");
  const counter = document.getElementById("aboutCount");
  if (about && counter) {
    const update = () => counter.textContent = about.value.length;
    about.addEventListener("input", update);
    update();
  }
});

document.addEventListener("DOMContentLoaded", () => {
  const ph = document.querySelector('input[name="photo"]'), prev = document.getElementById("photoPrev");
  if (ph && prev) ph.addEventListener("change", () => { const f = ph.files[0]; if (f && f.type.startsWith("image/")) prev.innerHTML = `<img class="ph" alt="" src="${URL.createObjectURL(f)}">`; });
  const q = document.getElementById("thq");
  if (q) q.addEventListener("input", () => document.querySelectorAll(".threads .th").forEach(t => t.style.display = t.textContent.toLowerCase().includes(q.value.toLowerCase()) ? "" : "none"));
  setTimeout(() => document.querySelectorAll(".flash-container .alert").forEach(a => bootstrap.Alert.getOrCreateInstance(a).close()), 3000);
});
