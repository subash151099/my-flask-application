document.addEventListener("DOMContentLoaded", () => {
  const modalElement = document.getElementById("loginAdvertisement");
  if (!modalElement) return;

  const image = modalElement.querySelector(".login-ad-image");
  const closeButton = document.getElementById("loginAdvertisementClose");
  if (!image || !closeButton || !window.bootstrap) return;

  const modal = bootstrap.Modal.getOrCreateInstance(modalElement, {
    backdrop: "static",
    keyboard: false
  });

  image.addEventListener("error", () => {
    console.error("Could not load the login advertisement image.");
  }, { once: true });

  const imageReady = image.complete
    ? (image.naturalWidth > 0
      ? Promise.resolve()
      : Promise.reject(new Error("The login advertisement image did not load.")))
    : new Promise((resolve, reject) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", () => reject(new Error("The login advertisement image did not load.")), { once: true });
    });

  imageReady.then(() => {
    return fetch(modalElement.dataset.impressionUrl, { method: "POST" });
  }).then((response) => {
    if (!response.ok) {
      if (response.status !== 409 && response.status !== 404) {
        console.error(`Could not record advertisement impression (${response.status}).`);
      }
      return null;
    }
    return response.json();
  }).then((result) => {
    if (result && result.show) modal.show();
  }).catch((error) => {
    console.error("Could not display the login advertisement.", error);
  });

  closeButton.addEventListener("click", () => {
    fetch(modalElement.dataset.closeUrl, { method: "POST" })
      .then((response) => {
        if (!response.ok) throw new Error(`Could not record advertisement close (${response.status}).`);
        modal.hide();
      })
      .catch((error) => {
        console.error("Could not record the advertisement close action.", error);
        modal.hide();
      });
  });
});
